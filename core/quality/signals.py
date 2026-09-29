"""Keep private full-text objects in sync with their database lifecycle."""

from django.db.models.signals import post_delete
from django.dispatch import receiver

from core.models import QAFulltextAsset


@receiver(post_delete, sender=QAFulltextAsset)
def delete_fulltext_files(sender, instance, **kwargs):
    for field_name in ('raw_file', 'extracted_text_file'):
        field_file = getattr(instance, field_name, None)
        if field_file and field_file.name:
            field_file.storage.delete(field_file.name)
