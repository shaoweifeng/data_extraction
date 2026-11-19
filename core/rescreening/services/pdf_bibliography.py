"""Versioned, fill-only enrichment for standalone PDF references."""
import json
from django.contrib.auth import get_user_model
from django.db import transaction
from core.bibliography import bibliography_snapshot
from core.fulltext.models import FulltextAsset
from core.models import ActivityLog, Project
from core.rescreening.errors import RescreenError
from core.rescreening.models import RescreenCorpus, RescreenReference, RescreenReferenceRawMetadata, RescreenFulltextBinding
from core.rescreening.services.imports import _require_idle
from core.rescreening.services.source import digest
from core.screening.services.reference_persistence import normalize_doi


def enrich_pdf_references(asset, bibliography, *, apply=True):
    """Owner/project/asset locks also serialize starts, reviews and rebinding.

    A changed bibliography is a new input: retain old bindings, model snapshots,
    and human reviews rather than silently rewriting inputs they were based on.
    """
    fields = bibliography.get('fields', {})
    allowed = ('authors', 'journal', 'publication_year', 'doi')
    changed = []
    expected_text_hash = asset.extracted_text_sha256
    with transaction.atomic():
        owner_id = Project.objects.values_list('owner_id', flat=True).get(pk=asset.project_id)
        get_user_model().objects.select_for_update().get(pk=owner_id)
        project = Project.objects.select_for_update().get(pk=asset.project_id)
        asset = FulltextAsset.objects.select_for_update().get(pk=asset.pk)
        if asset.status != 'ready' or asset.extracted_text_sha256 != expected_text_hash:
            return []
        _require_idle(project)
        if apply and asset.metadata.get('bibliography') != bibliography:
            asset.metadata = {**asset.metadata, 'bibliography': bibliography}
            asset.save(update_fields=['metadata', 'updated_at'])
        refs = RescreenReference.objects.active().filter(project=project, import_batch__source_type='pdf',
            source_key=f'pdf:{asset.asset_key}', current_binding__asset=asset).select_related('current_binding')
        corpus = RescreenCorpus.objects.select_for_update().filter(project=project).first()
        for ref in refs.select_for_update():
            updates = {key: fields[key] for key in allowed if fields.get(key) and not getattr(ref, key)}
            # Never truncate inferred values or replace a partly known author list.
            updates = {key: value for key, value in updates.items()
                       if not RescreenReference._meta.get_field(key).max_length
                       or len(value) <= RescreenReference._meta.get_field(key).max_length}
            if not updates:
                continue
            changed.append({'reference_id': ref.pk, 'fields': list(updates)})
            if not apply:
                continue
            old = ref.raw_metadata_versions.get(input_version=ref.input_version)
            raw = {**old.raw_fields, '_pdf_bibliography': bibliography}
            body = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
            ref.input_version += 1
            RescreenReferenceRawMetadata.objects.create(reference=ref, input_version=ref.input_version,
                raw_fields=raw, raw_size_bytes=len(body), raw_hash=digest(raw), source_format=old.source_format,
                parser_version=bibliography['version'], source_extracted_fields=old.source_extracted_fields,
                source_field_definitions=old.source_field_definitions)
            previous = ref.current_binding
            ref.current_binding = RescreenFulltextBinding.objects.create(reference=ref, asset=asset,
                input_version=ref.input_version, source=previous.source, confirmed_by=previous.confirmed_by,
                provenance={**previous.provenance, 'bibliography_enrichment': bibliography})
            for key, value in updates.items():
                setattr(ref, key, value)
            ref.normalized_doi = normalize_doi(ref.doi)
            ref.record_hash = digest(bibliography_snapshot(ref))
            ref.source_snapshot = {**ref.source_snapshot, 'pdf_bibliography': bibliography}
            ref.save(update_fields=[*updates, 'input_version', 'current_binding', 'normalized_doi',
                                    'record_hash', 'source_snapshot', 'updated_at'])
            ActivityLog.objects.create(project=project, operation_type='rescreen_fulltext_bound',
                operation_detail={'change_kind': 'pdf_bibliography_enriched', 'reference_id': ref.pk,
                                  'asset_id': asset.pk, 'input_version': ref.input_version, 'fields': list(updates)})
        if changed and apply:
            corpus.revision += 1
            corpus.current_run = None
            corpus.save(update_fields=['revision', 'current_run', 'updated_at'])
    return changed


def enrich_when_idle(asset, bibliography):
    try:
        return enrich_pdf_references(asset, bibliography)
    except RescreenError as exc:
        if exc.code != 'rescreen_busy':
            raise
        # Processing the file still succeeds. A later backfill can enrich it.
        return []
