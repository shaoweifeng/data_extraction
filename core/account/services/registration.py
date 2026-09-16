from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from core.models import UserProfile
from core.models_billing import CreditAccount

from ..models import AccountEmail, AgreementAcceptance
from .legal import current_legal_documents
from .verification import IssuedVerificationToken, issue_email_activation_token

User = get_user_model()


@dataclass(frozen=True)
class RegistrationConflict(Exception):
    field: str


@dataclass(frozen=True)
class PendingRegistration:
    user: object
    verification: IssuedVerificationToken


def record_registration_attempt(
    *,
    ip_address: str,
    username: str,
    email: str,
    success: bool,
    fail_reason: str = '',
) -> None:
    """Compatibility hook; V2 audit is recorded by the hashed security-event service."""
    return None


def _create_registration(
    *, username: str, email: str, password: str, is_active: bool,
    acceptance_context: dict | None = None,
):
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
        if acceptance_context:
            AgreementAcceptance.objects.bulk_create([
                AgreementAcceptance(
                    user=user,
                    document_type=document.document_type,
                    version=document.version,
                    content_sha256=document.content_sha256,
                    ip_hash=acceptance_context.get('ip_hash', ''),
                    user_agent_hash=acceptance_context.get('user_agent_hash', ''),
                )
                for document in current_legal_documents()
            ])
        return user


def register_user(
    *, username: str, email: str, password: str, is_active: bool = True,
    acceptance_context: dict | None = None,
):
    """Atomically create all phase-1 account records."""
    if User.objects.filter(email__iexact=email).exists():
        raise RegistrationConflict('email')
    try:
        return _create_registration(
            username=username,
            email=email,
            password=password,
            is_active=is_active,
            acceptance_context=acceptance_context,
        )
    except IntegrityError as exc:
        if User.objects.filter(username=username).exists():
            raise RegistrationConflict('username') from exc
        if AccountEmail.objects.filter(normalized_email=email).exists():
            raise RegistrationConflict('email') from exc
        raise


@transaction.atomic
def register_pending_user(
    *, username: str, email: str, password: str, acceptance_context: dict | None = None,
) -> PendingRegistration:
    user = register_user(
        username=username,
        email=email,
        password=password,
        is_active=False,
        acceptance_context=acceptance_context,
    )
    verification = issue_email_activation_token(user)
    return PendingRegistration(user=user, verification=verification)
