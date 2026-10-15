from django.conf import settings

from core.services.image_validation import ImageValidationError, validate_and_reencode_image


def validate_service_contact_qr(uploaded):
    """Validate and strip metadata from a PNG/JPEG service-contact QR image."""
    validated = validate_and_reencode_image(
        uploaded,
        max_bytes=settings.SERVICE_CONTACT_QR_MAX_BYTES,
        max_pixels=settings.SERVICE_CONTACT_QR_MAX_PIXELS,
    )
    if validated.mime_type not in {'image/png', 'image/jpeg'}:
        raise ImageValidationError('联系二维码仅支持 PNG 或 JPEG 图片')
    return validated
