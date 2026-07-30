"""
数据迁移（阶段一）：
1. 把历史 role in ('researcher','viewer') 归并为 'user'
2. 历史 is_approved=False 的正常用户批量置 True（免审核后避免老用户被锁）
3. 为没有 Profile 的历史 User 补建 Profile
4. 超级用户 role 置为 'admin'
"""
from django.db import migrations


def forwards(apps, schema_editor):
    User = apps.get_model('auth', 'User')
    UserProfile = apps.get_model('core', 'UserProfile')

    # 3. 为没有 Profile 的历史 User 补建 Profile
    for user in User.objects.all():
        UserProfile.objects.get_or_create(
            user=user,
            defaults={
                'role': 'admin' if user.is_superuser else 'user',
                'is_approved': True,
            },
        )

    # 1. role 归并：researcher/viewer -> user
    UserProfile.objects.filter(role__in=['researcher', 'viewer']).update(role='user')

    # 2. 历史 is_approved=False 全部置 True（免审核）
    UserProfile.objects.filter(is_approved=False).update(is_approved=True)

    # 4. 超级用户 role 置 admin
    superuser_ids = User.objects.filter(is_superuser=True).values_list('id', flat=True)
    UserProfile.objects.filter(user_id__in=list(superuser_ids)).update(role='admin')


def backwards(apps, schema_editor):
    # 不可逆的数据归并，回滚为空操作
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_userprofile_concurrency_limit_userprofile_is_banned_and_more'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
