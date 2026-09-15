from django.core.validators import validate_email


def normalize_email_address(value: str) -> str:
    """Normalize and validate the canonical account email value."""
    email = (value or '').strip().lower()
    validate_email(email)
    return email
