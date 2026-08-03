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
from django.utils import timezone
from django.conf import settings
import logging

from core.models import Task
from core.step_config import get_step_config, is_async_step

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
        task_obj = Task.objects.get(id=task_id)
        task_config = task_obj.config or {}

        # ── 阶段四：ai_screen 并发排队 ──────────────────────────────────
        if step_key == 'ai_screen':
            from core.services.concurrency_service import (
                get_user_concurrency, try_acquire, release, get_queue_info
            )
            user = task_obj.created_by
            slots = get_user_concurrency(user)

            acquired = try_acquire(task_id, slots)
            if not acquired:
                # 槽不足 → 更新状态为 queuing，写排队信息到 config，然后 retry
                queue_info = get_queue_info(task_id, slots)
                task_obj = Task.objects.get(id=task_id)
                task_obj.status = 'queuing'

                cfg = task_obj.config or {}
                cfg['queue_info'] = {
                    'position': queue_info['position'],
                    'queue_length': queue_info['queue_length'],
                    'slots_needed': slots,
                    'slots_free': queue_info['slots_free'],
                    'slots_total': queue_info['slots_total'],
                    'updated_at': timezone.now().isoformat(),
                }
                task_obj.config = cfg
                task_obj.save(update_fields=['status', 'config'])

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

            slot_acquired = True
            # 更新 config 清除 queue_info
            task_obj = Task.objects.get(id=task_id)
            cfg = task_obj.config or {}
            cfg.pop('queue_info', None)
            task_obj.config = cfg
            task_obj.save(update_fields=['config'])
        # ────────────────────────────────────────────────────────────────

        executor = StepExecutor(task_id, step_key, project_id)
        executor.config.update(task_config)

        executor.initialize()

        task_obj = Task.objects.get(id=task_id)
        task_obj.celery_task_id = self.request.id
        task_obj.save()

        success = executor.execute()
        executor.finalize(success)

        if success:
            logger.info(f"[Celery] 任务成功完成: task_id={task_id}")
            return True
        else:
            task_obj = Task.objects.get(id=task_id)
            if task_obj.status in ('stopping', 'stopped'):
                logger.info(f"[Celery] 任务被用户暂停: task_id={task_id}")
                return False
            raise Exception("任务执行返回失败状态")

    except Exception as e:
        logger.error(f"[Celery] 任务执行异常: {str(e)}")

        if executor:
            executor.finalize(False, str(e))

        config = get_step_config(step_key)
        retry_policy = config.get("retry_policy", {})
        max_retries = retry_policy.get("max_retries", 0)

        if self.request.retries < max_retries:
            retry_delay = retry_policy.get("retry_delay", 60)
            error_type = type(e).__name__
            retry_on = retry_policy.get("retry_on", [])

            if not retry_on or error_type in retry_on or any(r in str(e) for r in retry_on):
                logger.warning(f"[Celery] 准备重试 ({self.request.retries + 1}/{max_retries}): {str(e)}")
                raise self.retry(countdown=retry_delay, exc=e)

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
    
    running_tasks = Task.objects.filter(status='running')
    
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
                task.status = 'failed'
                task.error_message = f"任务超时（{elapsed:.0f}秒 > {timeout}秒）"
                task.completed_at = timezone.now()
                task.save()
                
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
def wake_queue_head():
    """
    槽位归还后唤醒队首等待任务，让它立即重试而不等 retry countdown。

    只需触发一次：队首任务重试时会再次调用 try_acquire，
    如果仍然拿不到槽（被更早的任务占用），它会重新排队。
    """
    try:
        import redis as redis_lib
        from django.conf import settings as dj_settings

        url = getattr(dj_settings, 'CELERY_BROKER_URL', 'redis://localhost:6379/0')
        r = redis_lib.from_url(url, decode_responses=True)
        head_members = r.zrange('ai_screen:queue', 0, 0)
        if not head_members:
            return

        head = head_members[0]
        task_id_str = head.split(':')[0]
        task_id = int(task_id_str)

        # 找到该 Task 对应的 Celery 任务 ID 并 revoke 延迟，触发立即重试
        # 实际上 Celery retry 任务已经在 countdown 中了，无法直接"加速"
        # 最简单的做法：直接发送一个新的 execute_async_step（如任务仍处于 queuing 状态）
        from django.db import close_old_connections
        close_old_connections()

        task = Task.objects.filter(id=task_id, status='queuing').first()
        if not task:
            return

        # 直接再 dispatch 一次，旧的 retry 任务最终也会因为 try_acquire 成功而运行
        # 为避免双重执行，在 try_acquire 成功后任务状态变为 pending/running，
        # 重复的那次 retry 抢槽时也会成功（已在队列里），执行是幂等的
        execute_async_step.apply_async(
            args=[task.id, task.task_type, task.project_id],
            countdown=0,
        )
        logger.info(f"[并发] 唤醒队首任务 task_id={task_id}")
    except Exception as e:
        logger.debug(f"[并发] wake_queue_head 异常（不影响功能）: {e}")


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
            
            if stage.status == 'completed':
                stage_progress = 100.0
            elif stage.status == 'in_progress':
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
