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

import os
import json
import shutil
import logging
from pathlib import Path
from typing import Dict, Optional, List
from datetime import datetime

from django.utils import timezone
from django.conf import settings
from django.db import transaction

logger = logging.getLogger(__name__)

from core.models import Task, Project, ProjectStage, StageStep, DataFile
from core.step_config import (
    get_step_config, 
    get_stage_definition,
    is_async_step,
    is_manual_step,
    get_sub_steps,
    get_step_order
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
        from .executors.sync_executor import SyncExecutor
        
        executor = SyncExecutor(task.id, step_key, self.project_id)
        
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
        
        # 【修复】先更新任务状态为 'stopping'，让前端知道正在停止中
        task.status = 'stopping'
        task.save()
        
        # 【修复】给执行器1秒时间检测STOP文件
        import time
        time.sleep(1)
        
        # 如果是Celery任务，尝试撤销
        if task.celery_task_id:
            try:
                from celery import Celery
                app = Celery('platform_backend')
                app.control.revoke(task.celery_task_id, terminate=True, wait=True, timeout=3)
            except Exception as e:
                # Celery broker 不可用，但任务状态仍需更新
                # STOP 文件会通知 worker 停止
                logger.warning(f"[Scheduler] 无法连接 Celery broker: {e}，将通过 STOP 文件停止任务")
        
        # 【修复】不在这里删除STOP文件，让执行器在finalize时清理
        # 这样确保执行器能检测到停止信号
        
        # 更新任务状态为 stopped
        task.refresh_from_db()
        if task.status == 'stopping':
            task.status = 'stopped'
            task.completed_at = timezone.now()
            task.save()
        
        return True
    
    def resume_task(self, task_id: int) -> Task:
        """
        恢复任务（断点续传）
        
        Args:
            task_id: 旧任务ID
        
        Returns:
            新任务对象
        """
        old_task = Task.objects.get(id=task_id, project=self.project)
        
        if old_task.status != 'stopped':
            raise ValueError("只能恢复已停止的任务")
        
        # 创建新任务
        new_task = Task.objects.create(
            project=self.project,
            task_type=old_task.task_type,
            status='pending',
            created_by=old_task.created_by,
            config=old_task.config
        )
        
        # 重新执行（执行器会加载checkpoint）
        step_key = old_task.task_type
        config = get_step_config(step_key)
        mode = config.get("execution_mode", "sync")
        
        if mode == "async":
            return self._execute_async(new_task, step_key)
        else:
            return self._execute_sync(new_task, step_key)
    
    # ========================================================================
    # 进度查询
    # ========================================================================
    
    def get_progress(self, task_id: int) -> Dict:
        """
        获取任务进度
        
        Args:
            task_id: 任务ID
        
        Returns:
            进度信息字典
        """
        task = Task.objects.get(id=task_id, project=self.project)
        
        # 尝试读取进度文件
        if task.log_file:
            progress_file = self._get_progress_file_path(task.log_file)
            
            if progress_file and os.path.exists(progress_file):
                try:
                    with open(progress_file, 'r') as f:
                        progress_data = json.load(f)
                        return {
                            "current": progress_data.get("current", 0),
                            "total": progress_data.get("total", 0),
                            "percentage": progress_data.get("percentage", 0.0),
                            "unit": progress_data.get("unit", ""),
                            "elapsed_time": str(timezone.now() - task.started_at) if task.started_at else None,
                            "status": task.status,
                            "last_update": progress_data.get("last_update")
                        }
                except Exception as e:
                    pass
        
        # 回退到任务表的进度字段
        return {
            "current": int(task.progress * 100),
            "total": 100,
            "percentage": task.progress * 100,
            "unit": "%",
            "elapsed_time": str(timezone.now() - task.started_at) if task.started_at else None,
            "status": task.status
        }
    
    def get_stage_progress(self, stage_key: str) -> Dict:
        """
        获取阶段进度（聚合子步骤）
        
        Args:
            stage_key: 阶段标识
        
        Returns:
            聚合的进度信息
        """
        config = get_step_config(stage_key)
        
        # 如果是单步骤，直接返回
        if "sub_steps" not in config:
            return self.get_step_progress(stage_key)
        
        # 聚合子步骤进度
        weights = config.get("monitoring", {}).get("weight_distribution", {})
        total_percentage = 0.0
        
        sub_step_progress = {}
        for step_key, weight in weights.items():
            step_prog = self.get_step_progress(step_key)
            sub_step_progress[step_key] = step_prog
            total_percentage += step_prog.get("percentage", 0) * weight
        
        return {
            "stage_key": stage_key,
            "percentage": round(total_percentage, 2),
            "sub_steps": sub_step_progress
        }
    
    def get_step_progress(self, step_key: str) -> Dict:
        """获取单个步骤的进度"""
        try:
            stage_key = get_step_config(step_key).get("stage_key")
            stage = ProjectStage.objects.get(
                project=self.project,
                stage_key=stage_key
            )
            step = StageStep.objects.get(
                stage=stage,
                step_key=step_key
            )
            
            # 尝试读取进度文件
            latest_task = Task.objects.filter(
                project=self.project,
                task_type=step_key,
                status='running'
            ).order_by('-created_at').first()
            
            if latest_task and latest_task.log_file:
                progress_file = self._get_progress_file_path(latest_task.log_file)
                
                if progress_file and os.path.exists(progress_file):
                    with open(progress_file, 'r') as f:
                        progress_data = json.load(f)
                        return {
                            "step_key": step_key,
                            "status": step.status,
                            "percentage": progress_data.get("percentage", 0.0),
                            "current": progress_data.get("current", 0),
                            "total": progress_data.get("total", 0),
                            "unit": progress_data.get("unit", "")
                        }
            
            return {
                "step_key": step_key,
                "status": step.status,
                "percentage": 100.0 if step.status == 'completed' else 0.0
            }
        
        except Exception as e:
            return {
                "step_key": step_key,
                "status": "not_started",
                "percentage": 0.0
            }
    
    def get_project_progress(self) -> Dict:
        """获取项目整体进度"""
        stages = ProjectStage.objects.filter(project=self.project)
        
        return {
            "project_id": self.project_id,
            "stages": {
                stage.stage_key: self.get_stage_progress(stage.stage_key)
                for stage in stages
            }
        }
    
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
    
    def _get_progress_file_path(self, log_file: str) -> Optional[str]:
        """根据日志文件路径获取进度文件路径"""
        if not log_file:
            return None
        
        # 替换日志文件名中的 "task_" 为 "progress_"
        progress_file = log_file.replace("task_", "progress_").replace(".log", ".json")
        
        full_path = os.path.join(settings.MEDIA_ROOT, progress_file)
        
        return full_path if os.path.exists(full_path) else None
