"""Lifecycle hooks for private screening import assets."""

from django.db.models.signals import post_delete
from django.dispatch import receiver

from core.screening.models import ReferenceImportFile


@receiver(post_delete, sender=ReferenceImportFile)
def delete_private_import_file(sender, instance, **kwargs):
    if instance.raw_file:
        instance.raw_file.delete(save=False)
