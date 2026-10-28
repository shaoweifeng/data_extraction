"""Bounded scans of final SCREEN_1 decisions and their import fingerprint."""
import hashlib
import json

from core.bibliography import bibliography_snapshot
from core.screening.services.final_results import iter_resolved_screening_records
from core.screening.services.screening_run_service import current_completed_screening_run
from core.screening.models import ScreeningReferenceRawMetadata
from core.rescreening.errors import RescreenError
from core.rescreening.models import RescreenReference


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()


def field_definitions(project_id):
    from core.models import StageStep
    metadata = StageStep.objects.filter(stage__project_id=project_id,
        stage__stage_key='SCREEN_1', step_key='field_extraction').values_list('metadata', flat=True).first() or {}
    return {'captured_from': 'stage_at_import', 'metadata': metadata, 'hash': digest(metadata)}


def source_fingerprint(row, raw_hash, definitions_hash=''):
    return digest({'bibliography': bibliography_snapshot(row.reference),
                   'fields': row.result.extracted_fields,
                   'decision': row.final_decision, 'raw_hash': raw_hash,
                   'definitions_hash': definitions_hash})


def source_preview(project, *, batch_size=500):
    run = current_completed_screening_run(project.pk)
    if run is None:
        raise RescreenError('screening_run_required', '没有与当前初筛文献集匹配的已完成筛选运行。', status=409)
    hasher = hashlib.sha256()
    counts = {'included': 0, 'excluded': 0, 'pending': 0, 'conflict': 0}
    new_count, existing_count, changed_count, buffer = 0, 0, 0, []
    differences = []
    definitions_hash = field_definitions(project.pk)['hash']

    def consume(rows):
        raw_hashes = dict(ScreeningReferenceRawMetadata.objects.filter(
            reference_id__in=[row.reference.pk for row in rows],
        ).values_list('reference_id', 'raw_hash'))
        existing = {ref.source_key: ref for ref in RescreenReference.objects.filter(
            project=project, import_batch__status='completed',
            source_key__in=[f'screening:{row.reference.pk}' for row in rows],
        ).only('id', 'source_key', 'source_snapshot', 'record_hash', 'removed_revision')}
        new, old, changed = 0, 0, 0
        for row in rows:
            fingerprint = source_fingerprint(row, raw_hashes.get(row.reference.pk, ''), definitions_hash)
            key = f'screening:{row.reference.pk}'
            saved = existing.get(key)
            hasher.update(digest([row.result.pk, fingerprint]).encode())
            counts[row.final_decision if row.final_decision in counts else 'pending'] += 1
            if saved:
                old += row.final_decision == 'included'
                if saved.source_snapshot.get('source_fingerprint') != fingerprint:
                    changed += 1
                    if len(differences) < 100:
                        differences.append({'reference_id': saved.pk, 'source_reference_id': row.reference.pk,
                                            'current_source_decision': row.final_decision,
                                            'removed': saved.removed_revision is not None})
            elif row.final_decision == 'included':
                new += 1
        return new, old, changed

    for row in iter_resolved_screening_records(run, batch_size=batch_size):
        buffer.append(row)
        if len(buffer) >= batch_size:
            new, old, changed = consume(buffer)
            new_count += new
            existing_count += old
            changed_count += changed
            buffer.clear()
    if buffer:
        new, old, changed = consume(buffer)
        new_count += new
        existing_count += old
        changed_count += changed
    return {
        'run_id': run.pk, 'corpus_revision': run.corpus_revision,
        'field_definitions_hash': definitions_hash,
        'fingerprint': hasher.hexdigest(), 'counts': counts,
        'new_count': new_count, 'existing_count': existing_count,
        'changed_count': changed_count, 'differences': differences,
        'differences_truncated': changed_count > len(differences),
    }
