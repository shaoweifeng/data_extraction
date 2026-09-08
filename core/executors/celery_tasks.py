"""
Celery任务包装 - 数据提取平台

包装异步执行器，添加：
- 任务重试逻辑
- 进度同步
- 错误处理
- 状态更新
- 全局并发排队（阶段四）

使用方式：
    from core.executors.celery_tasks import execute_async_step

    # 启动异步任务
    result = execute_async_step.delay(task_id, step_key, project_id)
"""

from celery import shared_task
from celery.exceptions import Retry
from django.utils import timezone
from django.conf import settings
from django.db import transaction
import logging

from core.models import Task
from core.step_config import get_step_config, is_async_step
from core.workflow.domain.statuses import ProjectStageStatus, TaskStatus
from core.workflow.services.lifecycle import InvalidStateTransition, transition_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def execute_async_step(self, task_id: int, step_key: str, project_id: int):
    """
    Celery异步任务入口。

    对于 ai_screen 步骤，在执行前先尝试抢占全局线程槽：
      - 成功 → 正常执行，完成后归还槽
      - 失败 → 设置 Task.status='queuing'，Celery retry 等待
    """
    logger.info(f"[Celery] 启动异步任务: task_id={task_id}, step={step_key}, project={project_id}")

    if not is_async_step(step_key):
        logger.error(f"[错误] 步骤 {step_key} 不是异步步骤")
        return False

    from .executor import StepExecutor

    executor = None
    task_obj = None
    slots = 0           # 本任务占用的槽数
    slot_acquired = False

    try:
        should_retry_queue = False
        queue_info = None

        # 数据库认领和 AI 槽位申请在同一个项目任务行锁内完成。重复 Celery
        # 投递只能有一个看到 pending/queuing，其余投递看到 running 后直接退出。
        with transaction.atomic():
            task_obj = Task.objects.select_for_update().select_related('created_by').get(id=task_id)
            if task_obj.status not in (TaskStatus.PENDING, TaskStatus.QUEUING):
                logger.info(
                    f"[Celery] 跳过重复或过期投递: task_id={task_id}, status={task_obj.status}"
                )
                return False

            task_config = dict(task_obj.config or {})

            if step_key == 'ai_screen':
                from core.services.concurrency_service import (
                    get_user_concurrency, try_acquire, get_queue_info,
                )

                slots = get_user_concurrency(task_obj.created_by)
                acquired = try_acquire(task_id, slots)
                if not acquired:
                    queue_info = get_queue_info(task_id, slots)
                    task_config['queue_info'] = {
                        'position': queue_info['position'],
                        'queue_length': queue_info['queue_length'],
                        'slots_needed': slots,
                        'slots_free': queue_info['slots_free'],
                        'slots_total': queue_info['slots_total'],
                        'updated_at': timezone.now().isoformat(),
                    }
                    transition_task(
                        task_obj,
                        TaskStatus.QUEUING,
                        updates={'config': task_config},
                        expected_from={TaskStatus.PENDING, TaskStatus.QUEUING},
                    )
                    should_retry_queue = True
                else:
                    slot_acquired = True
                    task_config.pop('queue_info', None)

            if not should_retry_queue:
                claim_updates = {'config': task_config, 'started_at': timezone.now()}
                if self.request.id:
                    claim_updates['celery_task_id'] = self.request.id
                transition_task(
                    task_obj,
                    TaskStatus.RUNNING,
                    updates=claim_updates,
                    expected_from={TaskStatus.PENDING, TaskStatus.QUEUING},
                )

        if should_retry_queue:
            retry_interval = getattr(settings, 'AI_SCREEN_QUEUE_RETRY_INTERVAL', 30)
            max_q_retries = getattr(settings, 'AI_SCREEN_QUEUE_MAX_RETRIES', 120)
            logger.info(
                f"[Celery] task={task_id} 排队等待（位置 {queue_info['position']}），"
                f"{retry_interval}s 后重试（第 {self.request.retries + 1} 次）"
            )
            raise self.retry(
                countdown=retry_interval,
                max_retries=max_q_retries,
                exc=Exception(f"排队等待槽位（位置 {queue_info['position']}）"),
            )

        executor = StepExecutor(task_id, step_key, project_id)
        executor.config.update(task_config)

        executor.initialize()

        success = executor.execute()
        if success:
            executor.finalize(True)
            logger.info(f"[Celery] 任务成功完成: task_id={task_id}")
            return True

        task_obj = Task.objects.get(id=task_id)
        if task_obj.status in (TaskStatus.STOPPING, TaskStatus.STOPPED):
            executor.finalize(False)
            logger.info(f"[Celery] 任务被用户暂停: task_id={task_id}")
            return False
        raise RuntimeError("任务执行返回失败状态")

    except Retry:
        raise
    except Exception as e:
        logger.error(f"[Celery] 任务执行异常: {str(e)}")

        task_obj = Task.objects.filter(id=task_id).first()
        if task_obj and task_obj.status in (TaskStatus.STOPPING, TaskStatus.STOPPED):
            if executor:
                executor.finalize(False, str(e))
            logger.info(f"[Celery] 任务停止后不再重试: task_id={task_id}")
            return False

        config = get_step_config(step_key)
        retry_policy = config.get("retry_policy", {})
        max_retries = retry_policy.get("max_retries", 0)

        if self.request.retries < max_retries:
            retry_delay = retry_policy.get("retry_delay", 60)
            error_type = type(e).__name__
            retry_on = retry_policy.get("retry_on", [])

            if not retry_on or error_type in retry_on or any(r in str(e) for r in retry_on):
                logger.warning(f"[Celery] 准备重试 ({self.request.retries + 1}/{max_retries}): {str(e)}")
                task_obj = Task.objects.get(id=task_id)
                if task_obj.status == TaskStatus.RUNNING:
                    transition_task(
                        task_obj,
                        TaskStatus.PENDING,
                        updates={'error_message': str(e)},
                        expected_from={TaskStatus.RUNNING},
                    )
                if executor:
                    executor.logger.close()
                raise self.retry(countdown=retry_delay, exc=e)

        if executor:
            executor.finalize(False, str(e))
        logger.error(f"[Celery] 任务最终失败: task_id={task_id}, error={str(e)}")
        raise

    finally:
        # 无论成功/失败/停止，都归还槽位
        if slot_acquired and step_key == 'ai_screen' and slots > 0:
            try:
                from core.services.concurrency_service import release
                release(task_id, slots)
            except Exception as e:
                logger.warning(f"[Celery] 归还槽位失败: {e}")


@shared_task(bind=True)
def check_task_timeout(self):
    """
    定期检查任务超时

    遍历所有运行中的任务，检查是否超时
    """
    from core.models import Task
    from core.step_config import get_timeout

    logger.info("[Celery] 检查任务超时...")

    running_tasks = Task.objects.filter(status=TaskStatus.RUNNING)

    for task in running_tasks:
        # 获取超时时间
        timeout = get_timeout(task.task_type)

        if timeout is None:
            continue  # 无超时限制

        # 检查是否超时
        if task.started_at:
            elapsed = (timezone.now() - task.started_at).total_seconds()

            if elapsed > timeout:
                logger.warning(f"[Celery] 任务超时: task_id={task.id}, elapsed={elapsed:.0f}s, timeout={timeout}s")

                # 标记为失败
                try:
                    transition_task(
                        task,
                        TaskStatus.FAILED,
                        updates={
                            'error_message': f"任务超时（{elapsed:.0f}秒 > {timeout}秒）",
                            'completed_at': timezone.now(),
                        },
                        expected_from={TaskStatus.RUNNING},
                    )
                except InvalidStateTransition:
                    # 用户可能恰好在超时检查期间停止了任务，不覆盖更新后的状态。
                    logger.info(f"[Celery] 任务状态已变化，跳过超时失败写入: task_id={task.id}")
                    continue

                # 撤销Celery任务
                if task.celery_task_id:
                    from celery import Celery
                    app = Celery('platform_backend')
                    app.control.revoke(task.celery_task_id, terminate=True)


@shared_task
def cleanup_old_workspaces():
    """
    清理旧的工作区目录

    删除超过30天的已完成任务工作区
    """
    import os
    import shutil
    from datetime import timedelta
    from pathlib import Path

    logger.info("[Celery] 清理旧工作区...")

    workspaces_root = Path(settings.BASE_DIR) / "workspaces"

    if not workspaces_root.exists():
        return

    cutoff = timezone.now() - timedelta(days=30)
    cleaned_count = 0

    for project_dir in workspaces_root.iterdir():
        if not project_dir.is_dir():
            continue

        for task_dir in project_dir.iterdir():
            if not task_dir.is_dir():
                continue

            # 从目录名提取时间戳
            # 格式: {step}_{timestamp}
            try:
                parts = task_dir.name.split('_')
                if len(parts) >= 2:
                    timestamp_str = parts[-1]
                    timestamp = timezone.datetime.strptime(timestamp_str, '%Y%m%d%H%M%S')

                    if timestamp < cutoff:
                        # 删除目录
                        shutil.rmtree(task_dir, ignore_errors=True)
                        cleaned_count += 1
                        logger.debug(f"[清理] 删除: {task_dir}")

            except (ValueError, IndexError):
                continue

    if cleaned_count > 0:
        logger.info(f"[Celery] 清理了 {cleaned_count} 个旧工作区")


@shared_task
def aggregate_project_progress(project_id: int):
    """
    聚合项目进度

    计算项目整体进度并更新项目元数据
    """
    from core.models import Project, ProjectStage
    from core.step_config import get_stage_definition

    logger.info(f"[Celery] 聚合项目进度: project_id={project_id}")

    try:
        project = Project.objects.get(id=project_id)

        stages = ProjectStage.objects.filter(project=project)

        total_progress = 0.0
        stage_count = 0

        for stage in stages:
            stage_def = get_stage_definition(stage.stage_key)
            stage_weight = stage_def.get("weight", 1.0) if stage_def else 1.0

            if stage.status == ProjectStageStatus.COMPLETED:
                stage_progress = 100.0
            elif stage.status == ProjectStageStatus.IN_PROGRESS:
                # 计算子步骤进度
                steps = stage.steps.all()
                if steps.exists():
                    step_progress_sum = sum(
                        s.metadata.get("progress", 0) if s.metadata else 0
                        for s in steps
                    )
                    stage_progress = step_progress_sum / steps.count()
                else:
                    stage_progress = 50.0  # 无子步骤默认50%
            else:
                stage_progress = 0.0

            total_progress += stage_progress * stage_weight
            stage_count += 1

        # 计算平均进度
        overall_progress = total_progress / stage_count if stage_count > 0 else 0.0

        # 更新项目元数据
        if not project.metadata:
            project.metadata = {}

        project.metadata["progress"] = round(overall_progress, 2)
        project.metadata["progress_updated_at"] = timezone.now().isoformat()
        project.save()

        logger.info(f"[Celery] 项目进度更新: {overall_progress:.1f}%")

    except Project.DoesNotExist:
        logger.error(f"[错误] 项目不存在: project_id={project_id}")


@shared_task
def send_task_notification(task_id: int, event: str):
    """
    发送任务通知（WebSocket/邮件）

    Args:
        task_id: 任务ID
        event: 事件类型（started/completed/failed）
    """
    from core.models import Task

    logger.info(f"[Celery] 发送任务通知: task_id={task_id}, event={event}")

    try:
        task = Task.objects.get(id=task_id)

        # TODO: 实现WebSocket推送
        # from channels.layers import get_channel_layer
        # from asgiref.sync import async_to_sync
        #
        # channel_layer = get_channel_layer()
        # async_to_sync(channel_layer.group_send)(
        #     f"project_{task.project_id}",
        #     {
        #         "type": "task_update",
        #         "data": {
        #             "task_id": task_id,
        #             "event": event,
        #             "status": task.status,
        #             "progress": task.progress
        #         }
        #     }
        # )

        logger.debug(f"[通知] task_id={task_id}, event={event}, status={task.status}")

    except Task.DoesNotExist:
        logger.error(f"[错误] 任务不存在: task_id={task_id}")
