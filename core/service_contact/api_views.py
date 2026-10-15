import mimetypes

from django.conf import settings
from django.http import FileResponse, Http404
from django.urls import reverse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.models import ServiceContactSetting


DEFAULT_CONTACT = {
    'display_name': 'MetaFlow 服务助手',
    'wechat_id': '',
    'contact_email': '',
    'service_hours': '',
    'description': '当前处于内测阶段，暂不公开售卖。如需申请使用，请关注平台后续通知。',
    'security_notice': '请勿向任何人提供密码、邮箱验证码或其他账户安全信息。',
    'qr_available': False,
    'qr_url': None,
}


def _active_setting():
    return ServiceContactSetting.objects.filter(singleton_id=1, enabled=True).first()


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def service_contact(request):
    """Return only the contact fields intentionally exposed to signed-in users."""
    if not settings.SERVICE_CONTACT_ENABLED:
        return Response({'enabled': False})

    contact = ServiceContactSetting.objects.filter(singleton_id=1).first()
    if contact is None:
        return Response({'enabled': True, 'configured': False, **DEFAULT_CONTACT})
    if not contact.enabled:
        return Response({'enabled': False})

    has_qr = bool(contact.wechat_qr and contact.wechat_qr.name)
    return Response({
        'enabled': True,
        'configured': True,
        'display_name': contact.display_name,
        'wechat_id': contact.wechat_id,
        'contact_email': contact.contact_email,
        'service_hours': contact.service_hours,
        'description': contact.description,
        'security_notice': contact.security_notice,
        'qr_available': has_qr,
        'qr_url': request.build_absolute_uri(reverse('billing_service_contact_qr')) if has_qr else None,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def service_contact_qr(request):
    """Stream the private QR image after session authentication."""
    if not settings.SERVICE_CONTACT_ENABLED:
        raise Http404
    contact = _active_setting()
    if contact is None or not contact.wechat_qr or not contact.wechat_qr.name:
        raise Http404
    try:
        stream = contact.wechat_qr.open('rb')
    except (FileNotFoundError, OSError):
        raise Http404

    content_type = mimetypes.guess_type(contact.wechat_qr.name)[0] or 'application/octet-stream'
    response = FileResponse(stream, content_type=content_type)
    response['Cache-Control'] = 'private, max-age=300'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Content-Security-Policy'] = "default-src 'none'; sandbox"
    return response
