"""
任务调度器 - 数据提取平台

统一管理所有步骤的执行：
- 根据步骤配置选择正确的执行器
- 处理流水线依赖关系
- 提供统一的启动/停止/恢复接口
- 聚合进度和状态信息

使用方式：
    from core.scheduler import TaskScheduler
    
    scheduler = TaskScheduler(project_id)
    
    # 启动阶段
    task = scheduler.start_stage('SCREEN_1', user_id)
    
    # 启动单步骤
    task = scheduler.start_step('ai_screen', user_id, **kwargs)
    
    # 停止任务
    scheduler.stop_task(task_id)
    
    # 断点续传
    task = scheduler.resume_task(task_id)
"""

import json
import logging
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime

from django.utils import timezone
from django.conf import settings

logger = logging.getLogger(__name__)

from core.models import Task, Project, ProjectStage, StageStep
from core.step_config import (
    get_step_config,
    get_stage_definition,
)


class TaskScheduler:
    """
    任务调度器
    
    核心职责：
    1. 根据步骤配置选择执行方式（sync/async/manual）
    2. 处理流水线依赖关系
    3. 提供统一的状态查询接口
    4. 聚合子步骤进度
    """
    
    def __init__(self, project_id: int):
        self.project_id = project_id
        self.project = Project.objects.get(id=project_id)
    
    # ========================================================================
    # 启动任务
    # ========================================================================
    
    def start_stage(self, stage_key: str, user_id: int, **kwargs) -> Task:
        """
        启动某个阶段
        
        Args:
            stage_key: 阶段标识（SEARCH/SCREEN_1/SCREEN_2等）
            user_id: 启动用户ID
            **kwargs: 额外配置参数
        
        Returns:
            创建的任务对象
        """
        # 获取阶段配置
        stage_config = get_step_config(stage_key)
        stage_def = get_stage_definition(stage_key)
        
        # 检查阶段类型
        mode = stage_config.get("execution_mode", "manual")
        
        if mode == "manual":
            # 手动阶段，只创建任务记录
            return self._create_manual_task(stage_key, user_id, **kwargs)
        
        elif mode == "pipeline":
            # 流水线阶段，依次启动子步骤
            return self._start_pipeline(stage_key, user_id, **kwargs)
        
        else:
            # 单步骤阶段
            return self.start_step(stage_key, user_id, **kwargs)
    
    def start_step(self, step_key: str, user_id: int, **kwargs) -> Task:
        """
        启动单个步骤
        
        Args:
            step_key: 步骤标识（parse/dedup/criteria/ai_screen/export）
            user_id: 启动用户ID
            **kwargs: 额外配置参数（如纳排标准）
        
        Returns:
            创建的任务对象
        """
        config = get_step_config(step_key)
        mode = config.get("execution_mode", "sync")
        
        # 检查依赖
        dependencies = self._check_dependencies(step_key)
        if not dependencies["satisfied"]:
            raise ValueError(f"依赖未满足: {dependencies['missing']}")
        
        # 创建任务
        task = Task.objects.create(
            project=self.project,
            task_type=step_key,
            status='pending',
            created_by_id=user_id,
            config=kwargs
        )
        
        # 根据执行模式调度
        if mode == "sync":
            return self._execute_sync(task, step_key)
        elif mode == "async":
            return self._execute_async(task, step_key)
        elif mode == "manual":
            return task  # 等待用户操作
        else:
            raise ValueError(f"未知的执行模式: {mode}")
    
    # ========================================================================
    # 执行方式
    # ========================================================================
    
    def _execute_sync(self, task: Task, step_key: str) -> Task:
        """同步执行"""
        from .executors.executor import StepExecutor

        executor = StepExecutor(task.id, step_key, self.project_id)
        # 将 Task 的动态 config（含 ai_model 等）合并进 executor.config
        task_config = task.config or {}
        executor.config.update(task_config)
        
        try:
            executor.initialize()
            success = executor.execute()
            executor.finalize(success)
        except Exception as e:
            executor.finalize(False, str(e))
        
        task.refresh_from_db()
        return task
    
    def _execute_async(self, task: Task, step_key: str) -> Task:
        """异步执行（Celery）"""
        from .executors.celery_tasks import execute_async_step
        
        # 更新任务状态
        task.status = 'pending'
        task.save()
        
        # 启动Celery任务
        result = execute_async_step.delay(task.id, step_key, self.project_id)
        
        # 保存Celery任务ID
        task.celery_task_id = result.id
        task.status = 'running'
        task.started_at = timezone.now()
        task.save()
        
        return task
    
    def _start_pipeline(self, stage_key: str, user_id: int, **kwargs) -> Task:
        """
        启动流水线
        
        流程：
        1. 创建流水线主任务
        2. 依次启动子步骤
        3. 遇到手动步骤时暂停等待
        """
        config = get_step_config(stage_key)
        sub_steps = config.get("sub_steps", [])
        
        # 创建流水线任务
        pipeline_task = Task.objects.create(
            project=self.project,
            task_type=stage_key,
            status='running',
            created_by_id=user_id,
            config={"pipeline": sub_steps}
        )
        
        # 依次启动子步骤
        for step_key in sub_steps:
            step_config = get_step_config(step_key)
            
            # 检查是否需要用户确认
            if step_config.get("execution_mode") == "manual":
                # 暂停等待用户操作
                pipeline_task.status = 'waiting_user'
                pipeline_task.save()
                break
            
            # 执行步骤
            self.start_step(step_key, user_id, **kwargs)
            
            # 检查步骤状态
            stage = ProjectStage.objects.get(
                project=self.project,
                stage_key=stage_key
            )
            step = StageStep.objects.get(
                stage=stage,
                step_key=step_key
            )
            
            if step.status == 'failed':
                pipeline_task.status = 'failed'
                pipeline_task.save()
                break
        
        return pipeline_task
    
    def _create_manual_task(self, stage_key: str, user_id: int, **kwargs) -> Task:
        """创建手动任务"""
        return Task.objects.create(
            project=self.project,
            task_type=stage_key,
            status='pending',
            created_by_id=user_id,
            config=kwargs
        )
    
    # ========================================================================
    # 停止/恢复任务
    # ========================================================================
    
    def stop_task(self, task_id: int) -> bool:
        """
        停止任务
        
        Args:
            task_id: 任务ID
        
        Returns:
            True if 成功, False otherwise
        """
        task = Task.objects.get(id=task_id, project=self.project)
        
        if task.status not in ['running', 'pending']:
            return False
        
        # 创建停止信号文件
        step_key = task.task_type
        stop_file = self._create_stop_signal(step_key)
        
        # 更新任务状态为 'stopping'，让前端知道正在停止中
        task.status = 'stopping'
        task.save()
        
        # 不再调用 revoke(terminate=True)：
        # 1. STOP 文件已经足够让执行器优雅停止
        # 2. revoke 会暴力 kill worker 子进程，导致 "signal is aborted without reason" 报错
        # 3. 执行器在下一个检查点检测到 STOP 文件后自行退出并 finalize
        
        # 更新任务状态为 stopped
        # 注意：此处是调度层立即设置 stopped，worker 的 finalize() 也会设置。
        # 为避免竞争条件，resume_task() 会等待 checkpoint 文件实际出现后再续传。
        task.refresh_from_db()
        if task.status == 'stopping':
            task.status = 'stopped'
            task.completed_at = timezone.now()
            task.save()
        
        return True
    
    def resume_task(self, task_id: int) -> Task:
        """
        恢复任务（断点续传）
        
        关键：将旧任务的 checkpoint 路径传给新任务，
        让新任务的执行器能找到上次的断点文件。
        
        查找 checkpoint 的优先级：
        1. task.config["checkpoint_path"]（worker finalize 时写入，最可靠）
        2. task.log_file 同级目录的 checkpoint.json（兜底）
        3. 等待最多 10 秒（处理竞争条件：stop 后立即 resume）
        """
        import time as _time
        old_task = Task.objects.get(id=task_id, project=self.project)
        
        if old_task.status != 'stopped':
            raise ValueError("只能恢复已停止的任务")
        
        config = dict(old_task.config or {})
        
        # 优先级1：从 task.config 中读取 worker 写入的 checkpoint_path
        checkpoint_path_from_config = config.pop("checkpoint_path", None)
        
        # 优先级2：从 log_file 同级目录推断
        checkpoint_from_log = None
        if old_task.log_file:
            from pathlib import Path
            old_log = Path(old_task.log_file)
            candidate = old_log.parent / "checkpoint.json"
            if candidate.exists():
                checkpoint_from_log = str(candidate)
        
        # 决定最终的 checkpoint 路径
        resume_cp = checkpoint_path_from_config or checkpoint_from_log
        
        if not resume_cp:
            # 可能 worker 还没来得及写（竞争条件），最多等 10 秒
            if old_task.log_file:
                from pathlib import Path
                wait_target = Path(old_task.log_file).parent / "checkpoint.json"
                logger.info(f"[续传] checkpoint.json 尚不存在，等待 worker 写入（最多10s）: {wait_target}")
                for _ in range(10):
                    _time.sleep(1)
                    old_task.refresh_from_db()
                    # worker finalize 可能已更新 config
                    fresh_cp = (old_task.config or {}).get("checkpoint_path")
                    if fresh_cp:
                        resume_cp = fresh_cp
                        break
                    if wait_target.exists():
                        resume_cp = str(wait_target)
                        break
                if resume_cp:
                    logger.info(f"[续传] 找到断点文件: {resume_cp}")
                else:
                    logger.warning(f"[续传] 等待超时，未找到 checkpoint.json，将从头开始")
        
        if resume_cp:
            config["resume_checkpoint_path"] = resume_cp
        
        # 记录旧进度，让新任务初始化时能直接写入正确 progress
        config["resume_progress"] = old_task.progress
        # 清理 checkpoint_path（已转移到 resume_checkpoint_path）
        config.pop("checkpoint_path", None)
        
        # 创建新任务
        new_task = Task.objects.create(
            project=self.project,
            task_type=old_task.task_type,
            status='pending',
            created_by=old_task.created_by,
            config=config
        )
        
        # 将旧 stopped 任务标记为 superseded（已被续传替代），避免最近任务列表显示两条
        old_task.status = 'superseded'
        old_task.save()
        
        step_key = old_task.task_type
        step_config = get_step_config(step_key)
        mode = step_config.get("execution_mode", "sync")
        
        if mode == "async":
            return self._execute_async(new_task, step_key)
        else:
            return self._execute_sync(new_task, step_key)
    
    # ========================================================================
    # 辅助方法
    # ========================================================================
    
    def _check_dependencies(self, step_key: str) -> Dict:
        """检查步骤依赖是否满足"""
        config = get_step_config(step_key)
        dependencies = config.get("dependencies", [])
        
        missing = []
        for dep in dependencies:
            # 检查依赖步骤是否完成
            try:
                stage_key = get_step_config(dep).get("stage_key", dep)
                stage = ProjectStage.objects.get(
                    project=self.project,
                    stage_key=stage_key
                )
                
                if stage.status != 'completed':
                    missing.append(dep)
            except Exception:
                missing.append(dep)
        
        return {
            "satisfied": len(missing) == 0,
            "missing": missing
        }
    
    def _create_stop_signal(self, step_key: str) -> str:
        """创建停止信号文件"""
        stop_file = Path(settings.BASE_DIR) / "workspaces" / f"project_{self.project_id}" / f"{step_key}.STOP"
        stop_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(stop_file, 'w') as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "reason": "用户请求停止",
                "step_key": step_key,
                "project_id": self.project_id
            }, f)
        
        return str(stop_file)
    
    # _get_progress_file_path 已迁移到 core/services/progress_service._derive_progress_path
