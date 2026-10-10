"""Shared validation and safe re-encoding for untrusted image uploads."""

from __future__ import annotations

import hashlib
import io
import os
import warnings
from dataclasses import dataclass

from django.core.files.base import ContentFile
from django.core.files.uploadedfile import UploadedFile
from django.utils.text import get_valid_filename
from PIL import Image, ImageOps


class ImageValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ValidatedImage:
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


def _safe_original_name(name: str) -> str:
    basename = os.path.basename(name or 'image')
    return (get_valid_filename(basename) or 'image')[:255]


def validate_and_reencode_image(
    uploaded: UploadedFile,
    *,
    max_bytes: int,
    max_pixels: int,
) -> ValidatedImage:
    """Verify an image by content and return metadata-stripped encoded bytes."""
    if not uploaded or not getattr(uploaded, 'size', 0):
        raise ImageValidationError('上传的图片为空')
    if uploaded.size > max_bytes:
        raise ImageValidationError(f'{uploaded.name} 超过图片大小限制')

    try:
        uploaded.seek(0)
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(uploaded) as probe:
                image_format = (probe.format or '').upper()
                width, height = probe.size
                probe.verify()
        if image_format not in _FORMATS:
            raise ImageValidationError(f'{uploaded.name} 不是支持的图片格式')
        if width <= 0 or height <= 0 or width * height > max_pixels:
            raise ImageValidationError(f'{uploaded.name} 的图片尺寸过大')

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
    except ImageValidationError:
        raise
    except (Image.UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as exc:
        raise ImageValidationError(f'{getattr(uploaded, "name", "图片")} 不是有效图片') from exc

    data = output.getvalue()
    if len(data) > max_bytes:
        raise ImageValidationError(f'{uploaded.name} 处理后仍超过图片大小限制')
    return ValidatedImage(
        content=ContentFile(data, name=f'upload{extension}'),
        original_name=_safe_original_name(uploaded.name),
        mime_type=mime_type,
        file_size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        width=width,
        height=height,
    )
