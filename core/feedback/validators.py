from django.conf import settings
from django.core.files.uploadedfile import UploadedFile

from core.services.image_validation import (
    ImageValidationError,
    ValidatedImage,
    validate_and_reencode_image,
)


class FeedbackImageValidationError(ValueError):
    pass


ValidatedFeedbackImage = ValidatedImage


def validate_feedback_images(files):
    if len(files) > settings.FEEDBACK_MAX_IMAGES:
        raise FeedbackImageValidationError(f'最多上传 {settings.FEEDBACK_MAX_IMAGES} 张图片')
    total_size = sum(getattr(file, 'size', 0) for file in files)
    if total_size > settings.FEEDBACK_MAX_TOTAL_IMAGE_BYTES:
        raise FeedbackImageValidationError('图片总大小超过限制')

    validated = []
    for uploaded in files:
        validated.append(_validate_feedback_image(uploaded))
    return validated


def _validate_feedback_image(uploaded: UploadedFile):
    try:
        return validate_and_reencode_image(
            uploaded,
            max_bytes=settings.FEEDBACK_MAX_IMAGE_BYTES,
            max_pixels=settings.FEEDBACK_MAX_IMAGE_PIXELS,
        )
    except ImageValidationError as exc:
        raise FeedbackImageValidationError(str(exc)) from exc
