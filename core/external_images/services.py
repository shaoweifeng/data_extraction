from dataclasses import dataclass

from django.db import IntegrityError, transaction

from core.services.image_validation import ValidatedImage

from .models import ExternalImageUpload


@dataclass(frozen=True)
class ExternalImageUploadResult:
    upload: ExternalImageUpload
    created: bool


def store_external_image(*, client_request_id, source: str, image: ValidatedImage):
    existing = ExternalImageUpload.objects.filter(client_request_id=client_request_id).first()
    if existing:
        return ExternalImageUploadResult(existing, False)

    saved_file = None
    try:
        with transaction.atomic():
            upload = ExternalImageUpload.objects.create(
                client_request_id=client_request_id,
                source=source,
                original_name=image.original_name,
                mime_type=image.mime_type,
                file_size=image.file_size,
                sha256=image.sha256,
                width=image.width,
                height=image.height,
            )
            upload.file.save(image.content.name, image.content, save=False)
            saved_file = (upload.file.storage, upload.file.name)
            upload.save(update_fields=['file'])
        return ExternalImageUploadResult(upload, True)
    except IntegrityError:
        if saved_file:
            saved_file[0].delete(saved_file[1])
        return ExternalImageUploadResult(
            ExternalImageUpload.objects.get(client_request_id=client_request_id),
            False,
        )
    except Exception:
        if saved_file:
            saved_file[0].delete(saved_file[1])
        raise
