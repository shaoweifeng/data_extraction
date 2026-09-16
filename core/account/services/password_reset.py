from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.utils import timezone

from ..models import AccountEmail, AccountVerificationToken, VerificationPurpose
from .verification import (
    ExpiredVerificationToken,
    InvalidVerificationToken,
    digest_token,
)

User = get_user_model()


@dataclass(frozen=True)
class IssuedPasswordResetToken:
    record: AccountVerificationToken
    raw_token: str


@dataclass(frozen=True)
class PasswordResetResult:
    user: object


@transaction.atomic
def issue_password_reset_token(user) -> IssuedPasswordResetToken:
    identity = AccountEmail.objects.select_for_update().get(user=user)
    if identity.verified_at is None or not user.is_active:
        raise ValueError('password reset requires an active verified account')

    now = timezone.now()
    AccountVerificationToken.objects.select_for_update().filter(
        user=user,
        purpose=VerificationPurpose.PASSWORD_RESET,
        used_at__isnull=True,
        revoked_at__isnull=True,
    ).update(revoked_at=now)
    raw_token = secrets.token_urlsafe(32)
    record = AccountVerificationToken.objects.create(
        user=user,
        account_email=identity,
        purpose=VerificationPurpose.PASSWORD_RESET,
        token_digest=digest_token(raw_token),
        expires_at=now + timedelta(
            minutes=getattr(settings, 'PASSWORD_RESET_TTL_MINUTES', 30),
        ),
    )
    return IssuedPasswordResetToken(record=record, raw_token=raw_token)

@transaction.atomic
def reset_password(raw_token: str, new_password: str) -> PasswordResetResult:
    try:
        token = AccountVerificationToken.objects.select_for_update().select_related(
            'account_email',
        ).get(
            token_digest=digest_token(raw_token),
            purpose=VerificationPurpose.PASSWORD_RESET,
        )
    except AccountVerificationToken.DoesNotExist as exc:
        raise InvalidVerificationToken() from exc

    now = timezone.now()
    if token.used_at is not None or token.revoked_at is not None:
        raise InvalidVerificationToken()
    if token.expires_at <= now:
        raise ExpiredVerificationToken()

    user = User.objects.select_for_update().get(pk=token.user_id)
    identity = token.account_email
    if not user.is_active or identity.verified_at is None or identity.user_id != user.pk:
        raise InvalidVerificationToken()

    validate_password(new_password, user=user)
    user.set_password(new_password)
    user.save(update_fields=['password'])
    token.used_at = now
    token.save(update_fields=['used_at'])
    AccountVerificationToken.objects.filter(
        user=user,
        purpose=VerificationPurpose.PASSWORD_RESET,
        used_at__isnull=True,
        revoked_at__isnull=True,
    ).exclude(pk=token.pk).update(revoked_at=now)
    return PasswordResetResult(user=user)


@transaction.atomic
def change_password(user, new_password: str):
    locked_user = User.objects.select_for_update().get(pk=user.pk)
    locked_user.set_password(new_password)
    locked_user.save(update_fields=['password'])
    return locked_user
