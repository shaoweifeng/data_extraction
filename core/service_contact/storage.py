from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible


@deconstructible
class ServiceContactStorage(FileSystemStorage):
    """Private storage for the service contact QR code."""

    def __init__(self):
        super().__init__(
            location=settings.SERVICE_CONTACT_UPLOAD_ROOT,
            base_url=None,
            file_permissions_mode=0o600,
            directory_permissions_mode=0o700,
        )


service_contact_storage = ServiceContactStorage()
