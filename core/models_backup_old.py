from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.conf import settings
import os
import shutil

class Project(models.Model):
    name = models.CharField(max_length=255, verbose_name="项目名称")
    description = models.TextField(blank=True, null=True, verbose_name="项目描述")
    creator = models.ForeignKey(User, on_delete=models.CASCADE, related_name="projects", verbose_name="创建者")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "项目"
        verbose_name_plural = "项目"

class Stage(models.Model):
    STAGE_TYPES = [
        ('SEARCH', '文献检索'),
        ('SCREEN_1', '文献初筛'),
        ('SCREEN_2', '文献复筛'),
        ('QUALITY', '文献质量评价'),
        ('EXTRACT', '数据提取'),
        ('META', 'Meta分析'),
    ]
    
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="stages", verbose_name="所属项目")
    stage_type = models.CharField(max_length=20, choices=STAGE_TYPES, verbose_name="阶段类型")
    status = models.CharField(max_length=20, default='PENDING', verbose_name="阶段状态") # PENDING, IN_PROGRESS, COMPLETED
    metadata = models.JSONField(default=dict, blank=True, verbose_name="元数据") # 存储纳排标准等额外信息
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        unique_together = ('project', 'stage_type')
        verbose_name = "项目阶段"
        verbose_name_plural = "项目阶段"

def stage_data_upload_path(instance, filename):
    # 将文件存储在 project_<id>/<stage>/<filename> 下，实现物理隔离
    return f"projects/project_{instance.stage.project.id}/{instance.stage.stage_type}/{filename}"

class StageData(models.Model):
    DATA_TYPES = [
        ('INPUT', '输入数据'),
        ('OUTPUT', '输出数据'),
    ]
    
    stage = models.ForeignKey(Stage, on_delete=models.CASCADE, related_name="data", verbose_name="所属阶段")
    file = models.FileField(upload_to=stage_data_upload_path, verbose_name="文件")
    filename = models.CharField(max_length=255, verbose_name="原始文件名")
    data_type = models.CharField(max_length=10, choices=DATA_TYPES, default='INPUT', verbose_name="数据类型")
    description = models.TextField(blank=True, null=True, verbose_name="描述")
    uploaded_at = models.DateTimeField(auto_now_add=True, verbose_name="上传时间")
    source = models.CharField(max_length=50, default='UPLOAD', verbose_name="来源") # UPLOAD, PREVIOUS_STAGE, TOOL_GENERATED

    def __str__(self):
        return f"{self.stage.get_stage_type_display()} - {self.filename}"

    class Meta:
        verbose_name = "阶段数据"
        verbose_name_plural = "阶段数据"

# 保留旧模型以便迁移，但标记为过时（实际可以直接删掉 Document，用 StageData 替代，但为了平滑过渡先留着）
class Document(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="documents", verbose_name="所属项目")
    file = models.FileField(upload_to="documents/%Y/%m/%d/", verbose_name="PDF文件")
    filename = models.CharField(max_length=255, verbose_name="原始文件名")
    uploaded_at = models.DateTimeField(auto_now_add=True, verbose_name="上传时间")
    is_processed = models.BooleanField(default=False, verbose_name="是否已处理")

    def __str__(self):
        return self.filename

    class Meta:
        verbose_name = "文档(旧)"
        verbose_name_plural = "文档(旧)"

class ExtractionTask(models.Model):
    STATUS_CHOICES = [
        ('PENDING', '等待中'),
        ('PROCESSING', '处理中'),
        ('COMPLETED', '已完成'),
        ('FAILED', '失败'),
        ('STOPPED', '已停止'),
    ]
    
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="tasks", verbose_name="所属项目")
    celery_task_id = models.CharField(max_length=255, blank=True, null=True, verbose_name="Celery任务ID")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING', verbose_name="任务状态")
    result_excel = models.FileField(upload_to="results/%Y/%m/%d/", blank=True, null=True, verbose_name="结果Excel")
    logs = models.TextField(blank=True, null=True, verbose_name="运行日志")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    completed_at = models.DateTimeField(blank=True, null=True, verbose_name="完成时间")

    def __str__(self):
        return f"Task {self.id} - {self.status}"

    class Meta:
        verbose_name = "提取任务"
        verbose_name_plural = "提取任务"


@receiver(post_delete, sender=Document)
def _delete_document_file(sender, instance, **kwargs):
    f = getattr(instance, "file", None)
    if not f:
        return
    if not getattr(f, "name", None):
        return
    storage = f.storage
    if storage.exists(f.name):
        storage.delete(f.name)


@receiver(post_delete, sender=ExtractionTask)
def _delete_task_result_excel(sender, instance, **kwargs):
    f = getattr(instance, "result_excel", None)
    if not f:
        return
    if not getattr(f, "name", None):
        return
    storage = f.storage
    if storage.exists(f.name):
        storage.delete(f.name)


@receiver(post_delete, sender=Project)
def _delete_project_workspace(sender, instance, **kwargs):
    # 1. 删除 workspaces/project_<id>
    workspace_base = os.path.join(settings.BASE_DIR, "workspaces")
    workspace_dir = os.path.join(workspace_base, f"project_{instance.id}")
    workspace_base_real = os.path.realpath(workspace_base)
    workspace_dir_real = os.path.realpath(workspace_dir)
    if workspace_dir_real.startswith(workspace_base_real + os.sep) and os.path.exists(workspace_dir_real):
        shutil.rmtree(workspace_dir_real, ignore_errors=True)
    
    # 2. 删除 media/projects/project_<id> (StageData 的存储位置)
    media_project_dir = os.path.join(settings.MEDIA_ROOT, "projects", f"project_{instance.id}")
    media_project_dir_real = os.path.realpath(media_project_dir)
    media_root_real = os.path.realpath(settings.MEDIA_ROOT)
    
    # 安全检查：确保要删除的目录确实在 MEDIA_ROOT 下
    if media_project_dir_real.startswith(media_root_real + os.sep) and os.path.exists(media_project_dir_real):
        shutil.rmtree(media_project_dir_real, ignore_errors=True)
        
@receiver(post_delete, sender=StageData)
def _delete_stage_data_file(sender, instance, **kwargs):
    # 删除 StageData 对应的文件
    if instance.file:
        if os.path.isfile(instance.file.path):
            os.remove(instance.file.path)
