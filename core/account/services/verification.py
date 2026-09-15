from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from core.services.billing_service import grant_credits

from ..models import AccountEmail, AccountVerificationToken, VerificationPurpose

User = get_user_model()


class VerificationError(Exception):
    code = 'invalid_token'


class InvalidVerificationToken(VerificationError):
    code = 'invalid_token'


class ExpiredVerificationToken(VerificationError):
    code = 'expired_token'


@dataclass(frozen=True)
class IssuedVerificationToken:
    record: AccountVerificationToken
    raw_token: str


@dataclass(frozen=True)
class ActivationResult:
    user: object
    already_verified: bool


def digest_token(raw_token: str) -> str:
    return hashlib.sha256((raw_token or '').encode('utf-8')).hexdigest()


@transaction.atomic
def issue_email_activation_token(user) -> IssuedVerificationToken:
    identity = AccountEmail.objects.select_for_update().get(user=user)
    now = timezone.now()
    AccountVerificationToken.objects.filter(
        user=user,
        purpose=VerificationPurpose.EMAIL_ACTIVATION,
        used_at__isnull=True,
        revoked_at__isnull=True,
    ).update(revoked_at=now)

    raw_token = secrets.token_urlsafe(32)
    ttl_hours = getattr(settings, 'EMAIL_VERIFICATION_TTL_HOURS', 24)
    record = AccountVerificationToken.objects.create(
        user=user,
        account_email=identity,
        purpose=VerificationPurpose.EMAIL_ACTIVATION,
        token_digest=digest_token(raw_token),
        expires_at=now + timedelta(hours=ttl_hours),
    )
    return IssuedVerificationToken(record=record, raw_token=raw_token)


@transaction.atomic
def activate_email(raw_token: str) -> ActivationResult:
    digest = digest_token(raw_token)
    try:
        token = AccountVerificationToken.objects.select_for_update().get(
            token_digest=digest,
            purpose=VerificationPurpose.EMAIL_ACTIVATION,
        )
    except AccountVerificationToken.DoesNotExist as exc:
        raise InvalidVerificationToken() from exc

    user = User.objects.select_for_update().get(pk=token.user_id)
    identity = AccountEmail.objects.select_for_update().get(pk=token.account_email_id)
    now = timezone.now()

    if token.used_at is not None:
        if user.is_active and identity.verified_at is not None:
            return ActivationResult(user=user, already_verified=True)
        raise InvalidVerificationToken()
    if token.revoked_at is not None:
        raise InvalidVerificationToken()
    if token.expires_at <= now:
        raise ExpiredVerificationToken()
    if identity.user_id != user.pk:
        raise InvalidVerificationToken()

    identity.verified_at = now
    identity.save(update_fields=['verified_at', 'updated_at'])
    if not user.is_active:
        user.is_active = True
        user.save(update_fields=['is_active'])

    welcome_credits = getattr(settings, 'BILLING_FREE_CREDITS_ON_REGISTER', 200)
    if welcome_credits > 0:
        grant_credits(
            user,
            welcome_credits,
            note='邮箱验证后注册赠送',
            idempotency_key=f'welcome_grant:{user.pk}',
        )

    token.used_at = now
    token.save(update_fields=['used_at'])
    AccountVerificationToken.objects.filter(
        user=user,
        purpose=VerificationPurpose.EMAIL_ACTIVATION,
        used_at__isnull=True,
        revoked_at__isnull=True,
    ).exclude(pk=token.pk).update(revoked_at=now)
    return ActivationResult(user=user, already_verified=False)
