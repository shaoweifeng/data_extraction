from django.contrib.auth import authenticate
from django.contrib.auth import get_user_model

from ..email import normalize_email_address
from ..models import AccountEmail

User = get_user_model()


def authenticate_identifier(request, identifier: str, password: str):
    """Authenticate by legacy username or a verified canonical email."""
    value = (identifier or '').strip()
    candidate_username = value
    try:
        normalized = normalize_email_address(value)
    except Exception:
        normalized = None

    if normalized:
        identity = AccountEmail.objects.select_related('user').filter(
            normalized_email=normalized,
            verified_at__isnull=False,
            user__is_active=True,
        ).first()
        if identity:
            candidate_username = identity.user.get_username()

    return authenticate(request, username=candidate_username, password=password)
