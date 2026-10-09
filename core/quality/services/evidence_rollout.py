"""Feature-gate the evidence pipeline independently from its master switch."""

from django.conf import settings


VALID_ROLLOUT_MODES = {'disabled', 'admin', 'allowlist', 'all'}


def evidence_retrieval_enabled_for(user) -> bool:
    if not settings.QA_EVIDENCE_RETRIEVAL_ENABLED:
        return False
    mode = settings.QA_EVIDENCE_ROLLOUT_MODE
    if mode == 'disabled':
        return False
    if mode == 'all':
        return True
    if not user or not user.is_authenticated:
        return False
    profile = getattr(user, 'profile', None)
    if user.is_superuser or (profile and profile.role == 'admin'):
        return True
    if mode == 'admin':
        return False
    identities = {str(user.pk), user.username, user.email}
    return bool(identities & settings.QA_EVIDENCE_ROLLOUT_ALLOWLIST)
