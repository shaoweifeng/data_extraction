from collections import Counter

from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone

from core.models import UserProfile
from core.models_billing import CreditAccount

from .email import normalize_email_address
from .models import AccountEmail, AccountVerificationToken

User = get_user_model()


def build_account_audit_report() -> dict:
    """Build a PII-minimized, read-only account consistency report."""
    normalized_emails = []
    empty_emails = 0
    invalid_emails = 0
    for email in User.objects.values_list('email', flat=True).iterator():
        if not (email or '').strip():
            empty_emails += 1
            continue
        try:
            normalized_emails.append(normalize_email_address(email))
        except Exception:
            invalid_emails += 1

    duplicate_groups = sum(
        1 for count in Counter(normalized_emails).values() if count > 1
    )
    account_email_table_present = (
        AccountEmail._meta.db_table in connection.introspection.table_names()
    )
    account_email_mismatches = 0
    account_emails_total = 0
    account_emails_unverified = 0
    if account_email_table_present:
        account_emails_total = AccountEmail.objects.count()
        account_emails_unverified = AccountEmail.objects.filter(verified_at__isnull=True).count()
        for identity in AccountEmail.objects.select_related('user').iterator():
            try:
                user_email = normalize_email_address(identity.user.email)
            except Exception:
                account_email_mismatches += 1
                continue
            if user_email != identity.normalized_email:
                account_email_mismatches += 1

    verification_table_present = (
        AccountVerificationToken._meta.db_table in connection.introspection.table_names()
    )
    verification_tokens_active = 0
    if verification_table_present:
        verification_tokens_active = AccountVerificationToken.objects.filter(
            used_at__isnull=True,
            revoked_at__isnull=True,
            expires_at__gt=timezone.now(),
        ).count()

    report = {
        'users_total': User.objects.count(),
        'users_missing_profile': User.objects.exclude(
            pk__in=UserProfile.objects.values('user_id'),
        ).count(),
        'users_missing_credit_account': User.objects.exclude(
            pk__in=CreditAccount.objects.values('user_id'),
        ).count(),
        'users_without_email': empty_emails,
        'users_with_invalid_email': invalid_emails,
        'duplicate_email_groups': duplicate_groups,
        'account_email_table_present': account_email_table_present,
        'account_emails_total': account_emails_total,
        'account_emails_unverified': account_emails_unverified,
        'account_email_mismatches': account_email_mismatches,
        'pending_users': User.objects.filter(is_active=False, is_staff=False).count(),
        'verification_table_present': verification_table_present,
        'verification_tokens_active': verification_tokens_active,
        'negative_credit_accounts': CreditAccount.objects.filter(balance__lt=0).count(),
    }
    issue_fields = (
        'users_missing_profile',
        'users_missing_credit_account',
        'users_with_invalid_email',
        'duplicate_email_groups',
        'account_email_mismatches',
        'negative_credit_accounts',
    )
    report['has_integrity_issues'] = any(report[field] for field in issue_fields)
    return report
