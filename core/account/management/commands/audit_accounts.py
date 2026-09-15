import json

from django.core.management.base import BaseCommand, CommandError

from core.account.selectors import build_account_audit_report


class Command(BaseCommand):
    help = '只读检查账户、邮箱身份和积分账户的数据完整性'

    def add_arguments(self, parser):
        parser.add_argument('--json', action='store_true', dest='as_json')
        parser.add_argument('--fail-on-issues', action='store_true')

    def handle(self, *args, **options):
        report = build_account_audit_report()
        if options['as_json']:
            self.stdout.write(json.dumps(report, ensure_ascii=False, sort_keys=True))
        else:
            labels = {
                'users_total': '用户总数',
                'users_missing_profile': '缺少 Profile',
                'users_missing_credit_account': '缺少积分账户',
                'users_without_email': '空邮箱用户',
                'users_with_invalid_email': '非法邮箱用户',
                'duplicate_email_groups': '重复邮箱组',
                'account_email_table_present': '邮箱身份表已创建',
                'account_emails_total': '邮箱身份总数',
                'account_emails_unverified': '未验证邮箱身份',
                'account_email_mismatches': '邮箱身份不一致',
                'pending_users': '未激活普通用户',
                'verification_table_present': '验证 Token 表已创建',
                'verification_tokens_active': '有效验证 Token',
                'negative_credit_accounts': '负余额账户',
            }
            for field, label in labels.items():
                self.stdout.write(f'{label}: {report[field]}')
            status = '发现需要处理的数据问题' if report['has_integrity_issues'] else '未发现数据完整性问题'
            self.stdout.write(status)

        if options['fail_on_issues'] and report['has_integrity_issues']:
            raise CommandError('账户审计发现数据完整性问题')
