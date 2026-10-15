import core.service_contact.storage
import core.models
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0045_correct_bibliography_identifier_backfill'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ServiceContactSetting',
            fields=[
                ('singleton_id', models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False)),
                ('enabled', models.BooleanField(default=False, verbose_name='启用咨询入口')),
                ('display_name', models.CharField(default='MetaFlow 服务助手', max_length=100, verbose_name='联系人名称')),
                ('wechat_id', models.CharField(blank=True, default='', max_length=100, verbose_name='微信号')),
                ('wechat_qr', models.ImageField(blank=True, storage=core.service_contact.storage.ServiceContactStorage(), upload_to=core.models.service_contact_qr_upload_path, verbose_name='微信二维码')),
                ('contact_email', models.EmailField(blank=True, default='', max_length=254, verbose_name='联系邮箱')),
                ('service_hours', models.CharField(blank=True, default='', max_length=200, verbose_name='服务时间')),
                ('description', models.CharField(blank=True, default='当前处于内测阶段，暂不公开售卖。', max_length=500, verbose_name='页面说明')),
                ('security_notice', models.CharField(blank=True, default='请勿向任何人提供密码、邮箱验证码或其他账户安全信息。', max_length=500, verbose_name='安全提示')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='最后更新时间')),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='service_contact_updates', to=settings.AUTH_USER_MODEL, verbose_name='最后更新人')),
            ],
            options={
                'verbose_name': '服务联系方式',
                'verbose_name_plural': '服务联系方式',
                'db_table': 'plat_service_contact_setting',
            },
        ),
    ]
