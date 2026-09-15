from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from core.models import RegistrationLog, UserProfile
from core.models_billing import CreditAccount

from ..models import AccountEmail

User = get_user_model()


@dataclass(frozen=True)
class RegistrationConflict(Exception):
    field: str


def record_registration_attempt(
    *,
    ip_address: str,
    username: str,
    email: str,
    success: bool,
    fail_reason: str = '',
) -> None:
    """Audit registration attempts without making logging a write-path dependency."""
    try:
        RegistrationLog.objects.create(
            ip_address=ip_address,
            username=(username or '(空)')[:150],
            email=(email or '')[:254],
            success=success,
            fail_reason=(fail_reason or '')[:200],
        )
    except Exception:
        pass


def _create_registration(*, username: str, email: str, password: str, is_active: bool):
    with transaction.atomic():
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            is_active=is_active,
        )
        UserProfile.objects.get_or_create(
            user=user,
            defaults={
                'role': 'admin' if user.is_superuser else 'user',
                'is_approved': True,
            },
        )
        CreditAccount.objects.get_or_create(
            user=user,
            defaults={'balance': 0, 'total_granted': 0, 'total_consumed': 0},
        )
        AccountEmail.objects.create(
            user=user,
            email=email,
            normalized_email=email,
        )
        return user


def register_user(*, username: str, email: str, password: str, is_active: bool = True):
    """Atomically create all phase-1 account records."""
    if User.objects.filter(email__iexact=email).exists():
        raise RegistrationConflict('email')
    try:
        return _create_registration(
            username=username,
            email=email,
            password=password,
            is_active=is_active,
        )
    except IntegrityError as exc:
        if User.objects.filter(username=username).exists():
            raise RegistrationConflict('username') from exc
        if AccountEmail.objects.filter(normalized_email=email).exists():
            raise RegistrationConflict('email') from exc
        raise
