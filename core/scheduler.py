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

import logging
from typing import Dict

from django.utils import timezone
from django.db import transaction

logger = logging.getLogger(__name__)

from core.models import Task, Project, ProjectStage
from core.step_config import get_step_config
from core.workflow.domain.statuses import ProjectStageStatus, TaskStatus
from core.workflow.runtime import WorkspaceManager
from core.workflow.services.lifecycle import InvalidStateTransition, transition_task
from core.workflow.services.task_launcher import create_step_task


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
        # 检查阶段类型
        mode = stage_config.get("execution_mode", "manual")

        if mode == "manual":
            # 手动阶段，只创建任务记录
            return self._create_manual_task(stage_key, user_id, **kwargs)

        elif mode == "pipeline":
            raise ValueError(
                f"阶段 {stage_key} 的 Pipeline 尚未实现，请从步骤接口逐项启动"
            )

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

        # 所有可执行步骤通过同一个带项目行锁的创建边界，防止重复启动。
        task = create_step_task(
            self.project_id,
            step_key,
            user_id,
            kwargs,
            exclusive=mode != "manual",
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
            if executor.task_obj is not None:
                executor.finalize(False, str(e))
            else:
                transition_task(
                    task,
                    TaskStatus.FAILED,
                    updates={'error_message': str(e), 'completed_at': timezone.now()},
                    expected_from={TaskStatus.PENDING},
                )

        task.refresh_from_db()
        return task

    def _execute_async(self, task: Task, step_key: str) -> Task:
        """异步执行（Celery）"""
        from .executors.celery_tasks import execute_async_step

        # 启动 Celery；broker 不可用时不能留下永久 pending 的幽灵任务。
        try:
            result = execute_async_step.delay(task.id, step_key, self.project_id)
        except Exception as exc:
            transition_task(
                task,
                TaskStatus.FAILED,
                updates={'error_message': f'任务派发失败: {exc}', 'completed_at': timezone.now()},
                expected_from={TaskStatus.PENDING},
            )
            raise

        # 调度器只保存 broker id；RUNNING 只能由真正开始执行的 worker 写入。
        task.celery_task_id = result.id
        task.save(update_fields=['celery_task_id', 'updated_at'])

        return task

    def _create_manual_task(self, stage_key: str, user_id: int, **kwargs) -> Task:
        """创建手动任务"""
        return create_step_task(
            self.project_id,
            stage_key,
            user_id,
            kwargs,
            exclusive=False,
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

        if task.status not in (TaskStatus.QUEUING, TaskStatus.RUNNING, TaskStatus.PENDING):
            return False

        if task.status == TaskStatus.QUEUING and task.task_type == 'ai_screen':
            from core.services.concurrency_service import cancel_queue, get_user_concurrency

            cancel_queue(task.id, get_user_concurrency(task.created_by))

        # 创建停止信号文件
        step_key = task.task_type
        self._create_stop_signal(task.id, step_key)

        # 更新任务状态为 'stopping'，让前端知道正在停止中
        try:
            transition_task(
                task,
                TaskStatus.STOPPING,
                expected_from={TaskStatus.QUEUING, TaskStatus.RUNNING, TaskStatus.PENDING},
            )
        except InvalidStateTransition:
            return False

        # 不再调用 revoke(terminate=True)：
        # 1. STOP 文件已经足够让执行器优雅停止
        # 2. revoke 会暴力 kill worker 子进程，导致 "signal is aborted without reason" 报错
        # 3. 执行器在下一个检查点检测到 STOP 文件后自行退出并 finalize

        # 更新任务状态为 stopped
        # 注意：此处是调度层立即设置 stopped，worker 的 finalize() 也会设置。
        # 为避免竞争条件，resume_task() 会等待 checkpoint 文件实际出现后再续传。
        task.refresh_from_db()
        if task.status == TaskStatus.STOPPING:
            transition_task(
                task,
                TaskStatus.STOPPED,
                updates={'completed_at': timezone.now()},
                expected_from={TaskStatus.STOPPING},
            )

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

        if old_task.status != TaskStatus.STOPPED:
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

        step_key = old_task.task_type
        step_config = get_step_config(step_key)
        mode = step_config.get("execution_mode", "sync")

        # 锁顺序统一为 Project -> Task，与普通启动相同，避免启动和恢复互相死锁。
        with transaction.atomic():
            Project.objects.select_for_update().get(pk=self.project_id)
            old_task = Task.objects.select_for_update().get(id=task_id, project=self.project)
            if old_task.status != TaskStatus.STOPPED:
                raise ValueError("只能恢复已停止的任务")

            # 锁内重新合并一次，避免 worker 在等待期间刚写入的 checkpoint 被旧对象覆盖。
            locked_config = dict(old_task.config or {})
            latest_checkpoint = locked_config.pop("checkpoint_path", None)
            if latest_checkpoint:
                locked_config["resume_checkpoint_path"] = latest_checkpoint
            elif resume_cp:
                locked_config["resume_checkpoint_path"] = resume_cp
            locked_config["resume_progress"] = old_task.progress

            new_task = create_step_task(
                self.project_id,
                step_key,
                old_task.created_by_id,
                locked_config,
                exclusive=mode != "manual",
            )

            # 将旧 stopped 任务标记为 superseded（已被续传替代），避免最近任务列表显示两条
            transition_task(
                old_task,
                TaskStatus.SUPERSEDED,
                expected_from={TaskStatus.STOPPED},
            )

        if mode == "async":
            return self._execute_async(new_task, step_key)
        if mode == "sync":
            return self._execute_sync(new_task, step_key)
        # 手动步骤恢复后继续等待用户操作，不应进入同步执行器。
        if mode == "manual":
            return new_task
        raise ValueError(f"未知的执行模式: {mode}")

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

                if stage.status != ProjectStageStatus.COMPLETED:
                    missing.append(dep)
            except Exception:
                missing.append(dep)

        return {
            "satisfied": len(missing) == 0,
            "missing": missing
        }

    def _create_stop_signal(self, task_id: int, step_key: str) -> str:
        """创建停止信号文件"""
        manager = WorkspaceManager(self.project_id, step_key, task_id)
        return str(manager.create_stop_signal("用户请求停止"))

    # _get_progress_file_path 已迁移到 core/services/progress_service._derive_progress_path
