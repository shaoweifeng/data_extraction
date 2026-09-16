import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('account', '0003_alter_accountverificationtoken_purpose_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AgreementAcceptance',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('document_type', models.CharField(choices=[('terms', '服务协议'), ('privacy', '隐私政策')], max_length=16)),
                ('version', models.CharField(max_length=32, verbose_name='版本')),
                ('content_sha256', models.CharField(max_length=64, verbose_name='内容摘要')),
                ('ip_hash', models.CharField(blank=True, max_length=64, verbose_name='IP 摘要')),
                ('user_agent_hash', models.CharField(blank=True, max_length=64, verbose_name='User-Agent 摘要')),
                ('accepted_at', models.DateTimeField(auto_now_add=True, verbose_name='接受时间')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='agreement_acceptances', to=settings.AUTH_USER_MODEL, verbose_name='用户')),
            ],
            options={'db_table': 'plat_agreement_acceptance', 'verbose_name': '协议接受记录', 'verbose_name_plural': '协议接受记录'},
        ),
        migrations.CreateModel(
            name='AccountSecurityEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event_type', models.CharField(db_index=True, max_length=48, verbose_name='事件类型')),
                ('outcome', models.CharField(db_index=True, max_length=16, verbose_name='结果')),
                ('user_id_snapshot', models.PositiveBigIntegerField(blank=True, null=True)),
                ('identifier_hash', models.CharField(blank=True, db_index=True, max_length=64)),
                ('ip_masked', models.CharField(blank=True, max_length=64, verbose_name='脱敏 IP')),
                ('ip_hash', models.CharField(blank=True, db_index=True, max_length=64)),
                ('user_agent_hash', models.CharField(blank=True, max_length=64)),
                ('detail', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='account_security_events', to=settings.AUTH_USER_MODEL, verbose_name='用户')),
            ],
            options={'db_table': 'plat_account_security_event', 'verbose_name': '账户安全事件', 'verbose_name_plural': '账户安全事件'},
        ),
        migrations.CreateModel(
            name='AccountAdminAuditEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('target_user_id_snapshot', models.PositiveBigIntegerField(blank=True, null=True)),
                ('target_username_snapshot', models.CharField(blank=True, max_length=150)),
                ('action', models.CharField(db_index=True, max_length=48, verbose_name='操作')),
                ('reason', models.CharField(blank=True, max_length=500, verbose_name='原因')),
                ('before', models.JSONField(blank=True, default=dict)),
                ('after', models.JSONField(blank=True, default=dict)),
                ('ip_hash', models.CharField(blank=True, max_length=64)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('actor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='account_admin_actions', to=settings.AUTH_USER_MODEL, verbose_name='管理员')),
                ('target_user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='account_admin_audit_events', to=settings.AUTH_USER_MODEL, verbose_name='目标用户')),
            ],
            options={'db_table': 'plat_account_admin_audit_event', 'verbose_name': '账户管理审计', 'verbose_name_plural': '账户管理审计'},
        ),
        migrations.AddConstraint(model_name='agreementacceptance', constraint=models.UniqueConstraint(fields=('user', 'document_type', 'version'), name='account_agreement_acceptance_uniq')),
        migrations.AddIndex(model_name='agreementacceptance', index=models.Index(fields=['document_type', 'version', '-accepted_at'], name='account_ag_documen_1e2dbf_idx')),
        migrations.AddIndex(model_name='accountsecurityevent', index=models.Index(fields=['event_type', 'outcome', '-created_at'], name='account_acc_event_t_8fe639_idx')),
        migrations.AddIndex(model_name='accountadminauditevent', index=models.Index(fields=['action', '-created_at'], name='account_acc_action_577ece_idx')),
    ]
