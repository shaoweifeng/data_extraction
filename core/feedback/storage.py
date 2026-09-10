from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible


@deconstructible
class FeedbackStorage(FileSystemStorage):
    """不公开 base_url 的反馈附件存储。附件只能通过鉴权 API 读取。"""

    def __init__(self):
        super().__init__(
            location=settings.FEEDBACK_UPLOAD_ROOT,
            base_url=None,
            file_permissions_mode=0o600,
            directory_permissions_mode=0o700,
        )


feedback_storage = FeedbackStorage()
