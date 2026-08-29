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


# ============================================================================
# 注册防刷日志（阶段五）
# ============================================================================

class RegistrationLog(models.Model):
    """
    记录每次注册请求（成功与失败均记录）。

    用途：
      - 同 IP 24h 内注册次数限流（REGISTER_IP_LIMIT 可配）
      - 运营排查异常注册行为
      - 预留：邮箱验证关联（email_verified 字段，当前默认 False）

    注意：IP 地址取自 X-Forwarded-For 或 REMOTE_ADDR，
          部署在反向代理后需确保 TRUSTED_PROXY_IPS 配置正确。
    """
    ip_address     = models.GenericIPAddressField(verbose_name="注册IP")
    username       = models.CharField(max_length=150, verbose_name="用户名")
    email          = models.EmailField(blank=True, default='', verbose_name="邮箱")
    success        = models.BooleanField(default=True, verbose_name="是否注册成功")
    fail_reason    = models.CharField(max_length=200, blank=True, default='', verbose_name="失败原因")
    # 预留字段：邮箱验证开关启用后使用
    email_verified = models.BooleanField(default=False, verbose_name="邮箱已验证")
    created_at     = models.DateTimeField(auto_now_add=True, verbose_name="记录时间")

    class Meta:
        db_table        = 'plat_registrationlog'
        verbose_name    = "注册日志"
        verbose_name_plural = "注册日志"
        indexes         = [
            models.Index(fields=['ip_address', 'created_at'], name='idx_reg_ip_time'),
        ]
        ordering = ['-created_at']

    def __str__(self):
        status = '成功' if self.success else f'失败({self.fail_reason})'
        return f"{self.ip_address} → {self.username} [{status}] {self.created_at:%Y-%m-%d %H:%M}"


# ============================================================================
# 人工检查（ManualReview）
# ============================================================================

class ManualReview(models.Model):
    """
    人工审阅覆写记录。

    AI 初筛完成后，研究者可对每篇文献的纳排决定进行人工复核并覆写。
    Export 步骤优先使用人工决定；未覆写的文献保留 AI 原始判断。

    关键设计：
    - ai_decision / ai_reason 冗余存储 AI 原始判断，人工决定单独存 decision 列，两者独立
    - decision 支持三态：included / excluded / pending（待定）
    - unique_together(project, source_xml) 保证每篇文献只有一条覆写记录（upsert 语义）
    - 重新 AI 筛选后不清空本表，前端展示时标注"AI已重新筛选"提示
    """

    DECISION_CHOICES = [
        ('included', '纳入'),
        ('excluded', '排除'),
        ('pending',  '待定'),
        ('conflict', '分歧（待人工定夺）'),
    ]

    CONSENSUS_CHOICES = [
        ('included', '一致纳入'),
        ('excluded', '一致排除'),
        ('conflict', '存在分歧'),
        ('pending',  '待处理'),
    ]

    project     = models.ForeignKey(
        Project, on_delete=models.CASCADE,
        related_name='manual_reviews', verbose_name="所属项目"
    )
    step        = models.ForeignKey(
        StageStep, on_delete=models.CASCADE,
        related_name='manual_reviews', verbose_name="所属步骤（review）"
    )
    source_xml  = models.CharField(max_length=500, verbose_name="对应 XML 文件名")

    # AI 原始判断（冗余，独立列）
    ai_decision = models.CharField(
        max_length=20, blank=True, default='',
        verbose_name="AI 原始决定 (included/excluded/conflict/error)"
    )
    ai_reason   = models.TextField(
        blank=True, default='',
        verbose_name="AI 排除理由（原文）"
    )

    # 多模型交叉验证结果（单模型时为空列表，向后兼容）
    multi_model_results = models.JSONField(
        default=list, blank=True,
        verbose_name="多模型筛选结果",
        help_text='[{"model_id": "gpt-4o", "model_name": "GPT-4o", "decision": "included", "reason": "", "tokens": {}}]'
    )
    # 共识结论（单模型时 = ai_decision；多模型时为合并后结论）
    consensus = models.CharField(
        max_length=20,
        choices=CONSENSUS_CHOICES,
        default='pending',
        verbose_name="多模型共识结论",
    )

    # 人工决定（独立列）
    decision    = models.CharField(
        max_length=20, choices=DECISION_CHOICES,
        verbose_name="人工最终决定"
    )
    reason      = models.TextField(blank=True, default='', verbose_name="人工标注理由")

    # 是否覆写了 AI 判断
    is_override = models.BooleanField(
        default=False,
        verbose_name="是否与 AI 判断不同（人工覆写）"
    )

    # 备注列表（每次 append，保留历史）
    # 格式：[{"content": "...", "created_at": "ISO8601", "user": "username"}, ...]
    notes = models.JSONField(
        default=list, blank=True,
        verbose_name="备注列表",
        help_text='[{"content": "备注内容", "created_at": "2024-01-01T12:00:00", "user": "admin"}]'
    )

    reviewer    = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='manual_reviews', verbose_name="审阅人"
    )
    reviewed_at = models.DateTimeField(auto_now=True, verbose_name="最后审阅时间")
    created_at  = models.DateTimeField(auto_now_add=True, verbose_name="首次创建时间")

    class Meta:
        db_table        = 'plat_manualreview'
        verbose_name    = "人工审阅记录"
        verbose_name_plural = "人工审阅记录"
        unique_together = ('project', 'source_xml')
        ordering        = ['-reviewed_at']
        indexes         = [
            models.Index(fields=['project', 'decision'],   name='idx_mr_project_decision'),
            models.Index(fields=['project', 'consensus'],  name='idx_mr_project_consensus'),
        ]

    def __str__(self):
        return f"{self.project.name} | {self.source_xml} | {self.get_decision_display()}"


# ============================================================================
# 文献质量评价模块（QUALITY_EVAL）
# 全部表前缀 plat_qa_，对已有表零改动
# ============================================================================

class QAReference(models.Model):
    """待评价文献"""
    SOURCE_CHOICES = [
        ('screening_import',   '从初筛/复筛导入'),
        ('bibliography_upload','上传题录'),
        ('fulltext_upload',    '上传全文文件'),
    ]
    FULLTEXT_STATUS_CHOICES = [
        ('available', '已有全文'),
        ('pending',   '待获取'),
        ('missing',   '无全文'),
        ('error',     '错误'),
    ]
    METHOD_CHOICES = [
        ('QUADAS2',  'QUADAS-2'),
        ('NOS',      'NOS'),
        ('ROB2',     'RoB 2'),
        ('AMSTAR2',  'AMSTAR 2'),
        ('ROBINS_I', 'ROBINS-I'),
    ]
    EVAL_MODE_CHOICES = [
        ('single', '单模型评价'),
        ('dual',   '双模型校验'),
    ]
    AI_STATUS_CHOICES = [
        ('pending',             '待评价'),
        ('running',             '评价中'),
        ('completed',           '已完成'),
        ('failed',              '失败'),
        ('skipped_no_fulltext', '跳过（无全文/摘要）'),
        ('skipped_no_method',   '跳过（未选方法）'),
        ('abstract_only',       '基于摘要评价'),
    ]
    REVIEW_STATUS_CHOICES = [
        ('not_started', '未开始'),
        ('partial',     '部分确认'),
        ('confirmed',   '已确认'),
    ]

    project        = models.ForeignKey(Project,   on_delete=models.CASCADE, related_name='qa_references', verbose_name="所属项目")
    title          = models.CharField(max_length=500, verbose_name="文献标题")
    first_author   = models.CharField(max_length=200, blank=True, default='', verbose_name="第一作者")
    year           = models.IntegerField(null=True, blank=True, verbose_name="发表年份")
    journal        = models.CharField(max_length=300, blank=True, default='', verbose_name="期刊")
    abstract       = models.TextField(blank=True, default='', verbose_name="摘要")
    doi            = models.CharField(max_length=200, blank=True, default='', verbose_name="DOI")
    source_type    = models.CharField(max_length=50, choices=SOURCE_CHOICES, default='fulltext_upload', verbose_name="来源类型")
    source_ref_id  = models.IntegerField(null=True, blank=True, verbose_name="来源文献ID（初筛/复筛导入时）")
    fulltext_file  = models.ForeignKey(DataFile, null=True, blank=True, on_delete=models.SET_NULL, related_name='qa_references', verbose_name="全文PDF文件")
    fulltext_status= models.CharField(max_length=20, choices=FULLTEXT_STATUS_CHOICES, default='pending', verbose_name="全文状态")
    quality_method = models.CharField(max_length=20, choices=METHOD_CHOICES, blank=True, default='', verbose_name="质量评价方法")
    eval_mode      = models.CharField(max_length=20, choices=EVAL_MODE_CHOICES, blank=True, default='', verbose_name="评价模式")
    selected_models= models.JSONField(default=list, blank=True, verbose_name="选择的模型ID列表")
    ai_eval_status = models.CharField(max_length=30, choices=AI_STATUS_CHOICES, default='pending', verbose_name="AI评价状态")
    review_status  = models.CharField(max_length=20, choices=REVIEW_STATUS_CHOICES, default='not_started', verbose_name="人工审阅状态")
    created_at     = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at     = models.DateTimeField(auto_now=True,     verbose_name="更新时间")

    class Meta:
        db_table             = 'plat_qa_reference'
        verbose_name         = "待评价文献"
        verbose_name_plural  = "待评价文献"
        ordering             = ['id']
        indexes = [
            models.Index(fields=['project', 'quality_method'], name='idx_qar_proj_method'),
            models.Index(fields=['project', 'review_status'],  name='idx_qar_proj_review'),
        ]

    def __str__(self):
        return f"[{self.quality_method}] {self.title[:60]}"


class QASignalItem(models.Model):
    """信号问题评价结果（每篇文献×每条信号问题一行）"""
    RESULT_TYPE_CHOICES = [
        ('bias_risk',     '风险偏倚'),
        ('applicability', '适用性担忧'),
    ]
    CONSISTENCY_CHOICES = [
        ('single',     '单模型'),
        ('consistent', '模型一致'),
        ('divergent',  '模型分歧'),
        ('partial',    '部分生成'),
        ('failed',     '生成失败'),
    ]

    qa_ref           = models.ForeignKey(QAReference, on_delete=models.CASCADE, related_name='signal_items', verbose_name="所属文献")
    quality_method   = models.CharField(max_length=20, verbose_name="评价方法")
    domain           = models.CharField(max_length=50, verbose_name="领域key")
    result_type      = models.CharField(max_length=20, choices=RESULT_TYPE_CHOICES, verbose_name="结果类型")
    signal_key       = models.CharField(max_length=100, verbose_name="信号问题标识符")
    signal_question  = models.CharField(max_length=500, verbose_name="信号问题")
    signal_description = models.CharField(max_length=1000, blank=True, default='', verbose_name="中文释义")
    options          = models.JSONField(default=list, verbose_name="可选值列表")
    # 单模型结果
    ai_judgment      = models.CharField(max_length=50, blank=True, default='', verbose_name="单模型AI判断")
    ai_reason        = models.TextField(blank=True, default='', verbose_name="单模型判断理由")
    ai_evidence      = models.TextField(blank=True, default='', verbose_name="证据原文")
    ai_evidence_page = models.CharField(max_length=100, blank=True, default='', verbose_name="证据位置")
    # 双模型结果
    model1_id        = models.CharField(max_length=100, blank=True, default='', verbose_name="模型1 ID")
    model1_judgment  = models.CharField(max_length=50, blank=True, default='', verbose_name="模型1判断")
    model1_reason    = models.TextField(blank=True, default='', verbose_name="模型1理由")
    model2_id        = models.CharField(max_length=100, blank=True, default='', verbose_name="模型2 ID")
    model2_judgment  = models.CharField(max_length=50, blank=True, default='', verbose_name="模型2判断")
    model2_reason    = models.TextField(blank=True, default='', verbose_name="模型2理由")
    consistency      = models.CharField(max_length=20, choices=CONSISTENCY_CHOICES, default='single', verbose_name="一致性状态")
    system_recommendation = models.CharField(max_length=50, blank=True, default='', verbose_name="系统推荐结果")
    pre_selected     = models.CharField(max_length=50, blank=True, default='', verbose_name="页面预选值")
    # 人工确认
    human_judgment   = models.CharField(max_length=50, blank=True, default='', verbose_name="人工最终判断")
    is_modified      = models.BooleanField(default=False, verbose_name="是否修改了AI判断")
    original_ai_judgment = models.CharField(max_length=50, blank=True, default='', verbose_name="修改前原AI判断")
    is_confirmed     = models.BooleanField(default=False, verbose_name="是否已人工确认")
    confirmed_by     = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='qa_confirmations', verbose_name="确认人")
    confirmed_at     = models.DateTimeField(null=True, blank=True, verbose_name="确认时间")
    created_at       = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        db_table            = 'plat_qa_signal_item'
        verbose_name        = "信号问题评价结果"
        verbose_name_plural = "信号问题评价结果"
        ordering            = ['qa_ref', 'domain', 'id']
        indexes = [
            models.Index(fields=['qa_ref', 'domain'],       name='idx_qasi_ref_domain'),
            models.Index(fields=['qa_ref', 'is_confirmed'], name='idx_qasi_ref_confirmed'),
        ]

    def __str__(self):
        return f"{self.qa_ref_id} | {self.domain} | {self.signal_key}"


class QADomainResult(models.Model):
    """领域汇总结果（每篇文献×每个领域一行，自动聚合）"""
    RESULT_CHOICES = [
        ('low',     '低风险/低担忧'),
        ('high',    '高风险/高担忧'),
        ('unclear', '不清楚'),
        ('pending', '待确认'),
        ('na',      '不适用'),
    ]

    qa_ref          = models.ForeignKey(QAReference, on_delete=models.CASCADE, related_name='domain_results', verbose_name="所属文献")
    domain          = models.CharField(max_length=50, verbose_name="领域key")
    domain_name     = models.CharField(max_length=100, blank=True, default='', verbose_name="领域显示名称")
    bias_risk_result           = models.CharField(max_length=20, choices=RESULT_CHOICES, default='pending', verbose_name="风险偏倚结果")
    applicability_result       = models.CharField(max_length=20, choices=RESULT_CHOICES, default='pending', verbose_name="适用性担忧结果")
    bias_all_confirmed         = models.BooleanField(default=False, verbose_name="风险偏倚全部已确认")
    applicability_all_confirmed= models.BooleanField(default=False, verbose_name="适用性全部已确认")
    updated_at      = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table            = 'plat_qa_domain_result'
        verbose_name        = "领域汇总结果"
        verbose_name_plural = "领域汇总结果"
        ordering            = ['qa_ref', 'domain']
        unique_together     = [('qa_ref', 'domain')]

    def __str__(self):
        return f"{self.qa_ref_id} | {self.domain} | BR:{self.bias_risk_result}"


class QAChart(models.Model):
    """图表生成记录"""
    project      = models.ForeignKey(Project,  on_delete=models.CASCADE, related_name='qa_charts', verbose_name="所属项目")
    quality_method = models.CharField(max_length=20, verbose_name="评价方法")
    chart_types  = models.JSONField(default=list, verbose_name="图表类型列表")
    ref_ids      = models.JSONField(default=list, verbose_name="参与作图的文献ID列表")
    image_file   = models.ForeignKey(DataFile, null=True, blank=True, on_delete=models.SET_NULL, related_name='qa_charts_image', verbose_name="导出图片文件")
    excel_file   = models.ForeignKey(DataFile, null=True, blank=True, on_delete=models.SET_NULL, related_name='qa_charts_excel', verbose_name="导出Excel文件")
    generated_at = models.DateTimeField(null=True, blank=True, verbose_name="图表生成时间")
    created_at   = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        db_table            = 'plat_qa_chart'
        verbose_name        = "图表生成记录"
        verbose_name_plural = "图表生成记录"
        ordering            = ['-created_at']

    def __str__(self):
        return f"{self.project.name} | {self.quality_method} | {self.generated_at}"
