from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.conf import settings
from django.utils.text import slugify
from django.utils import timezone
import os
import shutil
import uuid


# ============================================================================
# 用户与权限管理
# ============================================================================

class UserProfile(models.Model):
    """用户配置文件"""
    ROLE_CHOICES = [
        ('admin', '管理员'),
        ('user', '普通用户'),
        # 以下为旧值，保留仅为兼容历史数据迁移，不再新用
        ('researcher', '研究者'),
        ('viewer', '访客'),
    ]
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile', verbose_name="用户")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='user', verbose_name="角色")
    quota_projects = models.IntegerField(default=10, verbose_name="项目配额")
    quota_storage_mb = models.IntegerField(default=5120, verbose_name="存储配额(MB)")
    # 免审核后 is_approved 语义弱化（默认 True），封禁统一走 is_banned
    is_approved = models.BooleanField(default=True, verbose_name="是否已审核")
    is_banned = models.BooleanField(default=False, verbose_name="是否被封禁")
    concurrency_limit = models.IntegerField(default=2, verbose_name="AI筛选并发档位")
    approved_at = models.DateTimeField(null=True, blank=True, verbose_name="审核时间")
    approved_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, 
                                     related_name='approved_users', verbose_name="审核人")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")
    
    class Meta:
        db_table = 'plat_userprofile'
        verbose_name = "用户配置"
        verbose_name_plural = "用户配置"

    @property
    def is_admin(self):
        """是否管理员：role=admin 或 Django 超级用户"""
        return self.role == 'admin' or self.user.is_superuser
    
    def __str__(self):
        return f"{self.user.username} ({self.get_role_display()})"


class Permission(models.Model):
    """系统权限"""
    CATEGORY_CHOICES = [
        ('user', '用户管理'),
        ('project', '项目管理'),
        ('stage', '阶段管理'),
        ('task', '任务管理'),
        ('file', '文件管理'),
        ('system', '系统管理'),
    ]
    
    code = models.CharField(max_length=100, unique=True, verbose_name="权限代码")
    name = models.CharField(max_length=255, verbose_name="权限名称")
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES, verbose_name="权限分类")
    description = models.TextField(blank=True, verbose_name="权限描述")
    is_system = models.BooleanField(default=True, verbose_name="是否系统权限")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    
    class Meta:
        db_table = 'plat_permission'
        verbose_name = "权限"
        verbose_name_plural = "权限"
        ordering = ['category', 'code']
    
    def __str__(self):
        return f"{self.code} - {self.name}"


class UserPermission(models.Model):
    """用户权限关系"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='custom_permissions', verbose_name="用户")
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE, verbose_name="权限")
    granted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, 
                                    related_name='granted_permissions', verbose_name="授权人")
    granted_at = models.DateTimeField(auto_now_add=True, verbose_name="授权时间")
    expires_at = models.DateTimeField(null=True, blank=True, verbose_name="过期时间")
    
    class Meta:
        db_table = 'plat_userpermission'
        verbose_name = "用户权限"
        verbose_name_plural = "用户权限"
        unique_together = ('user', 'permission')
    
    def __str__(self):
        return f"{self.user.username} - {self.permission.code}"


class RoleTemplate(models.Model):
    """角色权限模板"""
    name = models.CharField(max_length=100, unique=True, verbose_name="模板名称")
    description = models.TextField(blank=True, verbose_name="模板描述")
    is_system = models.BooleanField(default=True, verbose_name="是否系统预设")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")
    
    class Meta:
        db_table = 'plat_roletemplate'
        verbose_name = "角色模板"
        verbose_name_plural = "角色模板"
    
    def __str__(self):
        return self.name


class RoleTemplatePermission(models.Model):
    """角色模板-权限关联"""
    role_template = models.ForeignKey(RoleTemplate, on_delete=models.CASCADE, 
                                       related_name='template_permissions', verbose_name="角色模板")
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE, verbose_name="权限")
    
    class Meta:
        db_table = 'plat_roletemplatepermission'
        verbose_name = "角色模板权限"
        verbose_name_plural = "角色模板权限"
        unique_together = ('role_template', 'permission')


# ============================================================================
# 项目管理
# ============================================================================

class ProjectQuerySet(models.QuerySet):
    def for_user(self, user):
        """返回用户有权访问的项目"""
        if user.is_superuser:
            return self

        # 管理员角色可查看全部项目
        profile = getattr(user, 'profile', None)
        if profile and profile.role == 'admin':
            return self

        # 兼容旧 RBAC：拥有 project.view_all 权限也可查看全部
        if UserPermission.objects.filter(
            user=user,
            permission__code='project.view_all'
        ).exists():
            return self
        
        # 仅返回自己的项目
        return self.filter(owner=user)


class Project(models.Model):
    """项目"""
    STATUS_CHOICES = [
        ('active', '活跃'),
        ('archived', '已归档'),
        ('deleted', '已删除'),
    ]
    
    name = models.CharField(max_length=255, verbose_name="项目名称")
    slug = models.SlugField(max_length=100, unique=True, blank=True, verbose_name="URL标识")
    description = models.TextField(blank=True, verbose_name="项目描述")
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='owned_projects', verbose_name="所有者")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active', verbose_name="状态")
    metadata = models.JSONField(default=dict, blank=True, verbose_name="元数据")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")
    
    objects = ProjectQuerySet.as_manager()
    
    class Meta:
        db_table = 'plat_project'
        verbose_name = "项目"
        verbose_name_plural = "项目"
        ordering = ['-created_at']
    
    def __str__(self):
        return self.name
    
    def save(self, *args, **kwargs):
        if not self.slug:
            # 自动生成 slug
            base_slug = slugify(self.name[:50])
            if not base_slug:
                base_slug = f"project-{uuid.uuid4().hex[:8]}"
            
            slug = base_slug
            counter = 1
            while Project.objects.filter(slug=slug).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug
        
        super().save(*args, **kwargs)


# ============================================================================
# 阶段与步骤
# ============================================================================

class ProjectStage(models.Model):
    """项目阶段"""
    STATUS_CHOICES = [
        ('pending', '未开始'),
        ('in_progress', '进行中'),
        ('completed', '已完成'),
        ('skipped', '已跳过'),
    ]
    
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='stages', verbose_name="所属项目")
    stage_key = models.CharField(max_length=50, verbose_name="阶段标识")
    name = models.CharField(max_length=255, verbose_name="阶段名称")
    order = models.IntegerField(default=0, verbose_name="排序")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name="状态")
    started_at = models.DateTimeField(null=True, blank=True, verbose_name="开始时间")
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name="完成时间")
    metadata = models.JSONField(default=dict, blank=True, verbose_name="元数据")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")
    
    class Meta:
        db_table = 'plat_projectstage'
        verbose_name = "项目阶段"
        verbose_name_plural = "项目阶段"
        unique_together = ('project', 'stage_key')
        ordering = ['project', 'order']
    
    def __str__(self):
        return f"{self.project.name} - {self.name}"


class StageStep(models.Model):
    """阶段步骤"""
    STATUS_CHOICES = [
        ('pending', '未开始'),
        ('in_progress', '进行中'),
        ('completed', '已完成'),
        ('failed', '失败'),
        ('skipped', '已跳过'),
    ]
    
    stage = models.ForeignKey(ProjectStage, on_delete=models.CASCADE, related_name='steps', verbose_name="所属阶段")
    step_key = models.CharField(max_length=50, verbose_name="步骤标识")
    name = models.CharField(max_length=255, verbose_name="步骤名称")
    order = models.IntegerField(default=0, verbose_name="排序")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name="状态")
    can_skip = models.BooleanField(default=True, verbose_name="是否可跳过")
    started_at = models.DateTimeField(null=True, blank=True, verbose_name="开始时间")
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name="完成时间")
    metadata = models.JSONField(default=dict, blank=True, verbose_name="元数据")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")
    
    class Meta:
        db_table = 'plat_stagestep'
        verbose_name = "阶段步骤"
        verbose_name_plural = "阶段步骤"
        unique_together = ('stage', 'step_key')
        ordering = ['stage', 'order']
    
    def __str__(self):
        return f"{self.stage.name} - {self.name}"


# ============================================================================
# 文件管理
# ============================================================================

def data_file_upload_path(instance, filename):
    """文件上传路径"""
    # 处理 project 可能为 None 的情况（在保存之前）
    try:
        project_id = instance.project.id if instance.project else 'unknown'
    except:
        project_id = 'unknown'
    
    stage_key = instance.stage.stage_key if instance.stage else 'general'
    category = instance.data_category if hasattr(instance, 'data_category') else 'unknown'
    
    return f"projects/project_{project_id}/stages/{stage_key}/{category}/{filename}"


class DataFile(models.Model):
    """数据文件"""
    SOURCE_CHOICES = [
        ('upload', '用户上传'),
        ('tool_generated', '工具生成'),
        ('imported', '导入'),
    ]
    
    CATEGORY_CHOICES = [
        ('input', '输入数据'),
        ('output', '输出数据'),
        ('intermediate', '中间数据'),
    ]
    
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='files', verbose_name="所属项目")
    stage = models.ForeignKey(ProjectStage, null=True, blank=True, on_delete=models.CASCADE, 
                               related_name='files', verbose_name="所属阶段")
    step = models.ForeignKey(StageStep, null=True, blank=True, on_delete=models.CASCADE, 
                              related_name='files', verbose_name="所属步骤")
    
    filename = models.CharField(max_length=255, verbose_name="文件名")
    file = models.FileField(upload_to=data_file_upload_path, verbose_name="文件")
    file_size = models.BigIntegerField(default=0, verbose_name="文件大小(字节)")
    file_type = models.CharField(max_length=50, blank=True, verbose_name="文件类型")
    data_category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='input', verbose_name="数据类别")
    source = models.CharField(max_length=50, choices=SOURCE_CHOICES, default='upload', verbose_name="来源")
    description = models.TextField(blank=True, verbose_name="描述")
    metadata = models.JSONField(default=dict, blank=True, verbose_name="元数据")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, verbose_name="创建者")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")
    
    class Meta:
        db_table = 'plat_datafile'
        verbose_name = "数据文件"
        verbose_name_plural = "数据文件"
        ordering = ['-created_at']
    
    def __str__(self):
        return self.filename
    
    def save(self, *args, **kwargs):
        # 自动提取文件类型
        if not self.file_type and self.filename:
            self.file_type = self.filename.split('.')[-1].lower() if '.' in self.filename else ''
        
        # 自动计算文件大小
        if self.file and not self.file_size:
            self.file_size = self.file.size
        
        super().save(*args, **kwargs)


class DataFileVersion(models.Model):
    """文件版本历史"""
    data_file = models.ForeignKey(DataFile, on_delete=models.CASCADE, related_name='versions', verbose_name="数据文件")
    version = models.IntegerField(verbose_name="版本号")
    file_path = models.CharField(max_length=500, verbose_name="文件路径")
    file_size = models.BigIntegerField(default=0, verbose_name="文件大小(字节)")
    change_summary = models.TextField(blank=True, verbose_name="变更说明")
    metadata = models.JSONField(default=dict, blank=True, verbose_name="元数据")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, verbose_name="创建者")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    
    class Meta:
        db_table = 'plat_datafileversion'
        verbose_name = "文件版本"
        verbose_name_plural = "文件版本"
        unique_together = ('data_file', 'version')
        ordering = ['data_file', '-version']
    
    def __str__(self):
        return f"{self.data_file.filename} v{self.version}"


# ============================================================================
# 任务管理
# ============================================================================

class Task(models.Model):
    """后台任务"""
    STATUS_CHOICES = [
        ('queuing', '排队等待'),
        ('pending', '等待中'),
        ('running', '运行中'),
        ('completed', '已完成'),
        ('failed', '失败'),
        ('stopped', '已停止'),
        ('superseded', '已被续传替代'),
    ]
    
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='tasks', verbose_name="所属项目")
    stage = models.ForeignKey(ProjectStage, null=True, blank=True, on_delete=models.CASCADE, 
                               related_name='tasks', verbose_name="所属阶段")
    step = models.ForeignKey(StageStep, null=True, blank=True, on_delete=models.CASCADE, 
                              related_name='tasks', verbose_name="所属步骤")
    
    task_type = models.CharField(max_length=50, verbose_name="任务类型")
    celery_task_id = models.CharField(max_length=255, blank=True, verbose_name="Celery任务ID")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name="状态")
    progress = models.FloatField(default=0.0, verbose_name="进度(0-1)")
    result = models.JSONField(null=True, blank=True, verbose_name="任务结果")
    logs = models.TextField(blank=True, verbose_name="运行日志")
    log_file = models.CharField(max_length=500, blank=True, verbose_name="日志文件路径")
    error_message = models.TextField(blank=True, verbose_name="错误信息")
    config = models.JSONField(default=dict, blank=True, verbose_name="任务配置")
    started_at = models.DateTimeField(null=True, blank=True, verbose_name="开始时间")
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name="完成时间")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, verbose_name="创建者")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")
    
    class Meta:
        db_table = 'plat_task'
        verbose_name = "任务"
        verbose_name_plural = "任务"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.task_type} - {self.get_status_display()}"


# ============================================================================
# 操作日志
# ============================================================================

class ActivityLog(models.Model):
    """用户操作日志（文件上传/删除、纳排标准增删等）"""
    OPERATION_TYPES = [
        ('file_add', '添加文献索引'),
        ('file_delete', '删除文献索引'),
        ('criteria_add', '添加纳排标准'),
        ('criteria_delete', '删除纳排标准'),
        ('task_start_parse', '启动文献解析'),
        ('task_start_dedup', '启动文献去重'),
        ('task_start_ai_screen', '启动AI初筛'),
        ('task_start_export', '启动结果归纳'),
        ('task_stop', '暂停任务'),
        ('task_resume', '继续任务'),
        ('task_abandon', '放弃任务'),
        ('prompt_set', '自定义Prompt'),
        ('prompt_reset', '重置默认Prompt'),
        ('model_select', '切换AI模型'),
        ('field_extraction_add', '添加提取字段'),
        ('field_extraction_delete', '删除提取字段'),
    ]

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='activity_logs', verbose_name="所属项目")
    operation_type = models.CharField(max_length=50, choices=OPERATION_TYPES, verbose_name="操作类型")
    operation_detail = models.JSONField(default=dict, blank=True, verbose_name="操作详情")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, verbose_name="操作者")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="操作时间")

    class Meta:
        db_table = 'plat_activity_log'
        verbose_name = "操作日志"
        verbose_name_plural = "操作日志"
        ordering = ['-created_at']


# ============================================================================
# 信号：User 创建时自动创建 UserProfile（免审核，注册即可用）
# ============================================================================

@receiver(post_save, sender=User)
def ensure_user_profile(sender, instance, created, **kwargs):
    """
    User 创建时自动建立 UserProfile 兜底，避免注册/创建用户时遗漏。
    - 超级用户默认 role=admin，其余默认 role=user。
    - is_approved=True（免审核），封禁统一走 is_banned。
    - 用 get_or_create 防止重复创建导致 IntegrityError。
    """
    if created:
        UserProfile.objects.get_or_create(
            user=instance,
            defaults={
                'role': 'admin' if instance.is_superuser else 'user',
                'is_approved': True,
            },
        )


@receiver(post_delete, sender=DataFile)
def delete_file_on_model_delete(sender, instance, **kwargs):
    """删除数据文件模型时同时删除物理文件"""
    if instance.file:
        if os.path.isfile(instance.file.path):
            os.remove(instance.file.path)


@receiver(post_delete, sender=Project)
def delete_project_directory(sender, instance, **kwargs):
    """删除项目时清理目录"""
    project_dir = os.path.join(settings.MEDIA_ROOT, f"projects/project_{instance.id}")
    if os.path.isdir(project_dir):
        shutil.rmtree(project_dir, ignore_errors=True)
