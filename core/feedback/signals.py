from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import FeedbackAttachment


@receiver(post_delete, sender=FeedbackAttachment)
def delete_feedback_attachment_file(sender, instance, **kwargs):
    if instance.file:
        instance.file.storage.delete(instance.file.name)

