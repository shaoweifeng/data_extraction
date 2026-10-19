import hashlib
import hmac
import ipaddress
import json

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Model, QuerySet
from django.db.models.manager import BaseManager

from ..models import AccountAdminAuditEvent, AccountSecurityEvent


def private_fingerprint(value, purpose='account-security'):
    if not value:
        return ''
    key = f'{settings.SECRET_KEY}:{purpose}'.encode()
    return hmac.new(key, str(value).strip().casefold().encode(), hashlib.sha256).hexdigest()


def masked_ip(value):
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return ''
    network = ipaddress.ip_network(
        f'{address}/{24 if address.version == 4 else 48}', strict=False,
    )
    return str(network)


def request_fingerprints(request):
    from .client_ip import get_client_ip
    ip = get_client_ip(request)
    user_agent = request.META.get('HTTP_USER_AGENT', '')[:1000]
    return {
        'ip_masked': masked_ip(ip),
        'ip_hash': private_fingerprint(ip, 'ip'),
        'user_agent_hash': private_fingerprint(user_agent, 'user-agent'),
    }


def audit_json_value(value):
    """Convert Admin form values into stable JSON without losing audit context."""
    if isinstance(value, dict):
        return {str(key): audit_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [audit_json_value(item) for item in value]
    if isinstance(value, (QuerySet, BaseManager)):
        return [audit_json_value(item) for item in value.all()]
    if isinstance(value, Model):
        return {'id': value.pk, 'label': str(value)}
    try:
        return json.loads(json.dumps(value, cls=DjangoJSONEncoder))
    except (TypeError, ValueError):
        return str(value)


def record_security_event(*, request, event_type, outcome, user=None, identifier='', detail=None):
    try:
        AccountSecurityEvent.objects.create(
            event_type=event_type,
            outcome=outcome,
            user=user if getattr(user, 'pk', None) else None,
            user_id_snapshot=getattr(user, 'pk', None),
            identifier_hash=private_fingerprint(identifier, 'identifier'),
            detail=detail or {},
            **request_fingerprints(request),
        )
    except Exception:
        # Security telemetry must not make authentication unavailable.
        return None


def record_admin_event(*, request, action, target_user=None, reason='', before=None, after=None):
    return AccountAdminAuditEvent.objects.create(
        actor=request.user if request.user.is_authenticated else None,
        target_user=target_user,
        target_user_id_snapshot=getattr(target_user, 'pk', None),
        target_username_snapshot=getattr(target_user, 'username', ''),
        action=action,
        reason=(reason or '')[:500],
        before=audit_json_value(before or {}),
        after=audit_json_value(after or {}),
        ip_hash=request_fingerprints(request)['ip_hash'],
    )
