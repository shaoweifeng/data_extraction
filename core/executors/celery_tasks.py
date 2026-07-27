"""
Celery任务包装 - 数据提取平台

包装异步执行器，添加：
- 任务重试逻辑
- 进度同步
- 错误处理
- 状态更新

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
    Celery异步任务入口
    
    Args:
        self: Celery任务实例
        task_id: 任务ID
        step_key: 步骤标识
        project_id: 项目ID
    
    Returns:
        bool: True if 成功, False if 失败
    
    Raises:
        Exception: 重试次数用尽后抛出
    """
    logger.info(f"[Celery] 启动异步任务: task_id={task_id}, step={step_key}, project={project_id}")
    
    # 检查步骤是否为异步
    if not is_async_step(step_key):
        logger.error(f"[错误] 步骤 {step_key} 不是异步步骤")
        return False
    
    # 导入执行器（延迟导入避免循环依赖）
    from .executor import StepExecutor

    executor = None
    task_obj = None

    try:
        # 从 Task 模型读取 config（断点续传时包含 resume_checkpoint_path）
        task_obj = Task.objects.get(id=task_id)
        task_config = task_obj.config or {}

        # 创建执行器实例
        executor = StepExecutor(task_id, step_key, project_id)
        # 将 Task 模型的 config 合并到 executor.config（纳排标准、断点续传路径等）
        executor.config.update(task_config)
        
        # 初始化任务
        executor.initialize()
        
        # 保存Celery任务ID
        task_obj = Task.objects.get(id=task_id)
        task_obj.celery_task_id = self.request.id
        task_obj.save()
        
        # 执行任务
        success = executor.execute()
        
        # 收尾
        executor.finalize(success)
        
        if success:
            logger.info(f"[Celery] 任务成功完成: task_id={task_id}")
            return True
        else:
            # 检查是否是用户主动暂停（不是执行失败）
            task_obj = Task.objects.get(id=task_id)
            if task_obj.status in ('stopping', 'stopped'):
                logger.info(f"[Celery] 任务被用户暂停: task_id={task_id}")
                return False  # 正常结束，不触发重试和失败弹窗
            # 真正的执行失败，触发重试
            raise Exception("任务执行返回失败状态")
    
    except Exception as e:
        logger.error(f"[Celery] 任务执行异常: {str(e)}")
        
        # 收尾（标记为失败）
        if executor:
            executor.finalize(False, str(e))
        
        # 判断是否可重试
        config = get_step_config(step_key)
        retry_policy = config.get("retry_policy", {})
        max_retries = retry_policy.get("max_retries", 0)
        
        if self.request.retries < max_retries:
            retry_delay = retry_policy.get("retry_delay", 60)
            
            # 判断错误类型是否在重试列表中
            error_type = type(e).__name__
            retry_on = retry_policy.get("retry_on", [])
            
            if not retry_on or error_type in retry_on or any(r in str(e) for r in retry_on):
                logger.warning(f"[Celery] 准备重试 ({self.request.retries + 1}/{max_retries}): {str(e)}")
                raise self.retry(countdown=retry_delay, exc=e)
        
        # 重试次数用尽，记录最终失败
        logger.error(f"[Celery] 任务最终失败: task_id={task_id}, error={str(e)}")
        raise


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
