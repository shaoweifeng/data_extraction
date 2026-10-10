from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import ExternalImageUpload


@receiver(post_delete, sender=ExternalImageUpload)
def delete_external_image_file(sender, instance, **kwargs):
    if instance.file:
        instance.file.storage.delete(instance.file.name)
