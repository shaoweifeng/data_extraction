import hashlib
import io
import os
import warnings
from dataclasses import dataclass

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import UploadedFile
from django.utils.text import get_valid_filename
from PIL import Image, ImageOps


class FeedbackImageValidationError(ValueError):
    pass


@dataclass
class ValidatedFeedbackImage:
    content: ContentFile
    original_name: str
    mime_type: str
    file_size: int
    sha256: str
    width: int
    height: int


_FORMATS = {
    'JPEG': ('image/jpeg', '.jpg'),
    'PNG': ('image/png', '.png'),
    'WEBP': ('image/webp', '.webp'),
}


def _safe_original_name(name):
    basename = os.path.basename(name or 'image')
    return (get_valid_filename(basename) or 'image')[:255]


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
    if uploaded.size > settings.FEEDBACK_MAX_IMAGE_BYTES:
        raise FeedbackImageValidationError(f'{uploaded.name} 超过单张图片大小限制')

    try:
        uploaded.seek(0)
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(uploaded) as probe:
                image_format = (probe.format or '').upper()
                width, height = probe.size
                probe.verify()
        if image_format not in _FORMATS:
            raise FeedbackImageValidationError(f'{uploaded.name} 不是支持的图片格式')
        if width * height > settings.FEEDBACK_MAX_IMAGE_PIXELS:
            raise FeedbackImageValidationError(f'{uploaded.name} 的图片尺寸过大')

        uploaded.seek(0)
        with Image.open(uploaded) as source:
            image = ImageOps.exif_transpose(source)
            width, height = image.size
            output = io.BytesIO()
            mime_type, extension = _FORMATS[image_format]
            if image_format == 'JPEG':
                if image.mode not in ('RGB', 'L'):
                    image = image.convert('RGB')
                image.save(output, format='JPEG', quality=90, optimize=True)
            elif image_format == 'WEBP':
                image.save(output, format='WEBP', quality=90, method=4)
            else:
                image.save(output, format='PNG', optimize=True)
    except FeedbackImageValidationError:
        raise
    except (Image.UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as exc:
        raise FeedbackImageValidationError(f'{uploaded.name} 不是有效图片') from exc

    data = output.getvalue()
    if len(data) > settings.FEEDBACK_MAX_IMAGE_BYTES:
        raise FeedbackImageValidationError(f'{uploaded.name} 处理后仍超过单张图片大小限制')
    stored_name = f'upload{extension}'
    return ValidatedFeedbackImage(
        content=ContentFile(data, name=stored_name),
        original_name=_safe_original_name(uploaded.name),
        mime_type=mime_type,
        file_size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        width=width,
        height=height,
    )
