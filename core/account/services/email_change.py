from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone

from ..email import normalize_email_address
from ..models import AccountEmail, AccountEmailChangeRequest
from .verification import ExpiredVerificationToken, InvalidVerificationToken, digest_token

User = get_user_model()


class EmailChangeConflict(Exception):
    pass


@dataclass(frozen=True)
class IssuedEmailChangeToken:
    record: AccountEmailChangeRequest
    raw_token: str


@dataclass(frozen=True)
class EmailChangeResult:
    user: object
    old_verified_email: str | None
    new_email: str


@transaction.atomic
def issue_email_change_token(user, new_email: str) -> IssuedEmailChangeToken:
    normalized = normalize_email_address(new_email)
    User.objects.select_for_update().get(pk=user.pk)
    current = AccountEmail.objects.select_for_update().filter(user=user).first()
    if current and current.normalized_email == normalized:
        raise EmailChangeConflict('新邮箱不能与当前邮箱相同')
    if AccountEmail.objects.filter(normalized_email=normalized).exclude(user=user).exists():
        raise EmailChangeConflict('该邮箱已被使用')

    now = timezone.now()
    AccountEmailChangeRequest.objects.select_for_update().filter(
        user=user,
        used_at__isnull=True,
        revoked_at__isnull=True,
    ).update(revoked_at=now)
    raw_token = secrets.token_urlsafe(32)
    from django.conf import settings
    record = AccountEmailChangeRequest.objects.create(
        user=user,
        new_email=normalized,
        normalized_new_email=normalized,
        token_digest=digest_token(raw_token),
        expires_at=now + timedelta(
            hours=getattr(settings, 'EMAIL_CHANGE_TOKEN_TTL_HOURS', 24),
        ),
    )
    return IssuedEmailChangeToken(record=record, raw_token=raw_token)


@transaction.atomic
def confirm_email_change(raw_token: str) -> EmailChangeResult:
    try:
        request = AccountEmailChangeRequest.objects.select_for_update().get(
            token_digest=digest_token(raw_token),
        )
    except AccountEmailChangeRequest.DoesNotExist as exc:
        raise InvalidVerificationToken() from exc

    now = timezone.now()
    if request.used_at is not None or request.revoked_at is not None:
        raise InvalidVerificationToken()
    if request.expires_at <= now:
        raise ExpiredVerificationToken()

    user = User.objects.select_for_update().get(pk=request.user_id)
    if not user.is_active:
        raise InvalidVerificationToken()
    current = AccountEmail.objects.select_for_update().filter(user=user).first()
    old_verified_email = current.email if current and current.verified_at else None
    if AccountEmail.objects.filter(
        normalized_email=request.normalized_new_email,
    ).exclude(user=user).exists():
        raise EmailChangeConflict('该邮箱已被其他账号使用')

    try:
        if current:
            current.email = request.new_email
            current.normalized_email = request.normalized_new_email
            current.verified_at = now
            current.save(update_fields=['email', 'normalized_email', 'verified_at', 'updated_at'])
        else:
            AccountEmail.objects.create(
                user=user,
                email=request.new_email,
                normalized_email=request.normalized_new_email,
                verified_at=now,
            )
    except IntegrityError as exc:
        raise EmailChangeConflict('该邮箱已被其他账号使用') from exc

    user.email = request.new_email
    user.save(update_fields=['email'])
    request.used_at = now
    request.save(update_fields=['used_at'])
    AccountEmailChangeRequest.objects.filter(
        user=user,
        used_at__isnull=True,
        revoked_at__isnull=True,
    ).exclude(pk=request.pk).update(revoked_at=now)
    return EmailChangeResult(
        user=user,
        old_verified_email=old_verified_email,
        new_email=request.new_email,
    )
