"""Secure creation helpers for administrator-issued recharge codes."""

import re
import secrets

from django.db import IntegrityError, transaction

from core.models_billing import RechargeCode


# 32 unambiguous symbols: each random character contributes exactly 5 bits.
RECHARGE_CODE_ALPHABET = '23456789ABCDEFGHJKLMNPQRSTUVWXYZ'
RECHARGE_CODE_GROUPS = 3
RECHARGE_CODE_GROUP_LENGTH = 5
RECHARGE_CODE_CREATE_ATTEMPTS = 20


def normalize_recharge_code_prefix(value: str | None) -> str:
    """Return a short, readable prefix containing only uppercase letters/digits."""
    normalized = re.sub(r'[^A-Z0-9]', '', (value or '').strip().upper())[:10]
    return normalized or 'CODE'


def generate_secure_recharge_code(prefix: str | None = None) -> str:
    """Generate a 75-bit random code such as ``LITE-ABCDE-FGHJK-MNPQR``."""
    safe_prefix = normalize_recharge_code_prefix(prefix)
    groups = [
        ''.join(secrets.choice(RECHARGE_CODE_ALPHABET) for _ in range(RECHARGE_CODE_GROUP_LENGTH))
        for _ in range(RECHARGE_CODE_GROUPS)
    ]
    return '-'.join([safe_prefix, *groups])


def create_secure_recharge_code(*, prefix: str | None = None, **fields) -> RechargeCode:
    """Create one validated code, retrying the practically impossible unique collision."""
    for _ in range(RECHARGE_CODE_CREATE_ATTEMPTS):
        obj = RechargeCode(code=generate_secure_recharge_code(prefix), **fields)
        obj.full_clean(validate_unique=False)
        try:
            # The savepoint keeps an outer batch transaction usable after a
            # concurrent unique-key collision.
            with transaction.atomic():
                obj.save(force_insert=True)
            return obj
        except IntegrityError:
            continue
    raise RuntimeError('无法生成唯一兑换码，请稍后重试')
