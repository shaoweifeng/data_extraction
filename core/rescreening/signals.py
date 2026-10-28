"""Delete private physical assets when their owning rows are removed."""
from django.db.models.signals import post_delete, post_save
from django.db import transaction
from django.dispatch import receiver
from core.fulltext.models import FulltextAsset
from core.rescreening.models import RescreenImportFile, RescreenExport, RescreenCorpus, RescreenCriteriaRevision, RescreenRun, RescreenReviewEvent


@receiver(post_save, sender=RescreenCorpus)
@receiver(post_save, sender=RescreenCriteriaRevision)
@receiver(post_save, sender=RescreenRun)
@receiver(post_save, sender=RescreenReviewEvent)
def invalidate_rescreen_stage(sender, instance, **kwargs):
    from core.models import ProjectStage
    if sender is RescreenCorpus:
        project_id = instance.project_id
    elif sender is RescreenReviewEvent:
        project_id = instance.review.reference.project_id
    else:
        project_id = instance.corpus.project_id
    ProjectStage.objects.filter(project_id=project_id, stage_key='SCREEN_2').update(status='in_progress', completed_at=None)


@receiver(post_delete, sender=RescreenExport)
def delete_export_file(sender, instance, **kwargs):
    if instance.output:
        storage, name = instance.output.storage, instance.output.name
        transaction.on_commit(lambda: storage.delete(name), using=kwargs.get('using'))


@receiver(post_delete, sender=RescreenImportFile)
def delete_import_file(sender, instance, **kwargs):
    if instance.raw_file:
        storage, name = instance.raw_file.storage, instance.raw_file.name
        transaction.on_commit(lambda: storage.delete(name), using=kwargs.get('using'))


@receiver(post_delete, sender=FulltextAsset)
def delete_fulltext_files(sender, instance, **kwargs):
    for name in ('raw_file', 'extracted_text_file', 'chunk_index_file'):
        value = getattr(instance, name)
        if value:
            storage, stored_name = value.storage, value.name
            transaction.on_commit(lambda storage=storage, name=stored_name: storage.delete(name), using=kwargs.get('using'))
