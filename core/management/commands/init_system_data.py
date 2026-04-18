from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from core.models import Permission, RoleTemplate, RoleTemplatePermission, UserProfile

class Command(BaseCommand):
    help = '初始化系统权限、角色模板和超级管理员'
    
    def handle(self, *args, **options):
        self.stdout.write('🚀 开始初始化系统数据...\n')
        
        # 1. 创建权限
        self.stdout.write('📌 步骤 1: 创建系统权限')
        permissions_data = [
            # 用户管理权限
            ('user.view_all', '查看所有用户', 'user', '管理员可查看所有用户列表'),
            ('user.create', '创建用户', 'user', '管理员可创建新用户'),
            ('user.approve', '审核用户', 'user', '审核新注册用户'),
            ('user.edit_quota', '修改用户配额', 'user', '修改用户的项目和存储配额'),
            ('user.grant_permission', '授予权限', 'user', '给用户授予特定权限'),
            ('user.revoke_permission', '撤销权限', 'user', '撤销用户的特定权限'),
            
            # 项目管理权限
            ('project.create', '创建项目', 'project', '普通用户基础权限'),
            ('project.view_own', '查看自己的项目', 'project', '普通用户基础权限'),
            ('project.view_all', '查看所有项目', 'project', '管理员权限'),
            ('project.edit_own', '编辑自己的项目', 'project', '普通用户基础权限'),
            ('project.delete_own', '删除自己的项目', 'project', '普通用户基础权限'),
            ('project.export', '导出项目数据', 'project', '普通用户基础权限'),
            
            # 阶段管理权限
            ('stage.skip', '跳过阶段/步骤', 'stage', '普通用户基础权限'),
            ('stage.reset', '重置阶段状态', 'stage', '高级权限'),
            
            # 任务管理权限
            ('task.start', '启动任务', 'task', '普通用户基础权限'),
            ('task.stop', '停止任务', 'task', '普通用户基础权限'),
            ('task.view_logs', '查看任务日志', 'task', '普通用户基础权限'),
            
            # 文件管理权限
            ('file.upload', '上传文件', 'file', '普通用户基础权限'),
            ('file.download', '下载文件', 'file', '普通用户基础权限'),
            ('file.delete', '删除文件', 'file', '普通用户基础权限'),
            ('file.view_versions', '查看文件版本', 'file', '普通用户基础权限'),
            
            # 系统管理权限
            ('system.view_stats', '查看系统统计', 'system', '管理员权限'),
            ('system.config', '系统配置', 'system', '超级管理员权限'),
        ]
        
        created_permissions = {}
        for code, name, category, desc in permissions_data:
            perm, created = Permission.objects.get_or_create(
                code=code,
                defaults={
                    'name': name,
                    'category': category,
                    'description': desc,
                    'is_system': True
                }
            )
            created_permissions[code] = perm
            if created:
                self.stdout.write(f'  ✅ 创建权限: {code}')
        
        self.stdout.write(f'\n✅ 共创建/确认 {len(permissions_data)} 个权限\n')
        
        # 2. 创建角色模板
        self.stdout.write('📌 步骤 2: 创建角色模板')
        
        # 标准研究者模板
        researcher_template, created = RoleTemplate.objects.get_or_create(
            name='标准研究者',
            defaults={
                'description': '普通研究者，可管理自己的项目',
                'is_system': True
            }
        )
        
        researcher_perms = [
            'project.create', 'project.view_own', 'project.edit_own', 
            'project.delete_own', 'project.export',
            'stage.skip',
            'task.start', 'task.stop', 'task.view_logs',
            'file.upload', 'file.download', 'file.delete', 'file.view_versions'
        ]
        
        for perm_code in researcher_perms:
            if perm_code in created_permissions:
                RoleTemplatePermission.objects.get_or_create(
                    role_template=researcher_template,
                    permission=created_permissions[perm_code]
                )
        
        if created:
            self.stdout.write(f'  ✅ 创建角色模板: 标准研究者（{len(researcher_perms)} 项权限）')
        
        # 管理员模板
        admin_template, created = RoleTemplate.objects.get_or_create(
            name='管理员',
            defaults={
                'description': '系统管理员，可管理用户和查看所有项目',
                'is_system': True
            }
        )
        
        admin_perms = [
            'user.view_all', 'user.create', 'user.approve', 'user.edit_quota',
            'user.grant_permission', 'user.revoke_permission',
            'project.view_all',
            'system.view_stats'
        ] + researcher_perms  # 管理员拥有研究者的所有权限
        
        for perm_code in admin_perms:
            if perm_code in created_permissions:
                RoleTemplatePermission.objects.get_or_create(
                    role_template=admin_template,
                    permission=created_permissions[perm_code]
                )
        
        if created:
            self.stdout.write(f'  ✅ 创建角色模板: 管理员（{len(set(admin_perms))} 项权限）')
        
        self.stdout.write('\n✅ 角色模板创建完成\n')
        
        # 3. 创建超级管理员（如果不存在）
        self.stdout.write('📌 步骤 3: 创建超级管理员')
        
        if not User.objects.filter(is_superuser=True).exists():
            admin_user = User.objects.create_superuser(
                username='admin',
                email='admin@example.com',
                password='admin123'  # 首次登录后应修改
            )
            
            # 确保有 Profile
            profile, _ = UserProfile.objects.get_or_create(
                user=admin_user,
                defaults={
                    'role': 'admin',
                    'quota_projects': -1,  # 无限
                    'quota_storage_mb': -1,  # 无限
                    'is_approved': True
                }
            )
            
            self.stdout.write('  ✅ 创建超级管理员账号:')
            self.stdout.write('     用户名: admin')
            self.stdout.write('     密码: admin123')
            self.stdout.write('     ⚠️  请首次登录后立即修改密码！')
        else:
            self.stdout.write('  ℹ️  超级管理员已存在，跳过')
        
        self.stdout.write('\n🎉 系统数据初始化完成！\n')
        self.stdout.write('下一步：运行 python manage.py runserver 启动服务\n')
