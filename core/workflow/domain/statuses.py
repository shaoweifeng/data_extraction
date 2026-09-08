"""任务、步骤和阶段使用的集中状态定义。"""

from django.db import models


class TaskStatus(models.TextChoices):
    QUEUING = 'queuing', '排队等待'
    PENDING = 'pending', '等待中'
    RUNNING = 'running', '运行中'
    WAITING_USER = 'waiting_user', '等待用户操作'
    STOPPING = 'stopping', '正在停止'
    STOPPED = 'stopped', '已停止'
    COMPLETED = 'completed', '已完成'
    FAILED = 'failed', '失败'
    SUPERSEDED = 'superseded', '已被续传替代'


class StageStepStatus(models.TextChoices):
    PENDING = 'pending', '未开始'
    IN_PROGRESS = 'in_progress', '进行中'
    STOPPED = 'stopped', '已停止'
    COMPLETED = 'completed', '已完成'
    FAILED = 'failed', '失败'
    SKIPPED = 'skipped', '已跳过'


class ProjectStageStatus(models.TextChoices):
    PENDING = 'pending', '未开始'
    IN_PROGRESS = 'in_progress', '进行中'
    STOPPED = 'stopped', '已停止'
    COMPLETED = 'completed', '已完成'
    FAILED = 'failed', '失败'
    SKIPPED = 'skipped', '已跳过'
