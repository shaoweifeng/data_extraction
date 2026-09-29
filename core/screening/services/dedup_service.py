"""Database-backed, revision-safe screening reference deduplication."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Callable, Iterator

from django.db import transaction
from django.utils import timezone

from core.screening.models import (
    DedupRun,
    ReferenceDuplicateGroup,
    ReferenceDuplicateMember,
    ScreeningCorpus,
    ScreeningReference,
)
from core.screening.services.import_limits import ImportLimits
from core.screening.services.reference_persistence import normalize_title


RULE_VERSION = 'v1.5.0-normalized-title-v1'
RULE_SNAPSHOT = {
    'primary_rule': 'normalized_title_exact',
    'candidate_key': 'sha256(normalized_title)',
    'secondary_check': 'normalized_title_exact',
    'representative': 'lowest_reference_id',
    'empty_title': 'keep_without_grouping',
    # v1.5.0 used title-only matching. DOI/year remain descriptive fields and do
    # not veto an exact normalized-title match, preserving the regression baseline.
    'doi_conflict': 'does_not_veto_title_match',
    'year_conflict': 'does_not_veto_title_match',
}


class DeduplicationError(RuntimeError):
    """Stable business error raised by the database deduplication service."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class DeduplicationCancelled(DeduplicationError):
    def __init__(self):
        super().__init__('dedup_cancelled', '文献去重已由用户取消。')


@dataclass
class _TitleGroupState:
    representative_id: int
    display_title: str
    group: ReferenceDuplicateGroup | None = None
    member_count: int = 1


def create_dedup_run(*, project, task=None, created_by=None) -> DedupRun:
    """Create a run bound to the currently published corpus revision."""
    with transaction.atomic():
        corpus = ScreeningCorpus.objects.select_for_update().filter(project=project).first()
        if corpus is None or corpus.active_reference_count <= 0:
            raise DeduplicationError('empty_corpus', '当前项目没有可用于去重的已发布文献。')
        return DedupRun.objects.create(
            project=project,
            corpus=corpus,
            corpus_revision=corpus.revision,
            task=task,
            created_by=created_by,
            status=DedupRun.Status.RUNNING,
            rule_version=RULE_VERSION,
            rule_snapshot=RULE_SNAPSHOT,
            total_count=corpus.active_reference_count,
            started_at=timezone.now(),
        )


class _DuplicateMemberWriter:
    """Persist group members in bounded batches while groups are discovered."""

    def __init__(self, run: DedupRun, batch_size: int):
        self.run = run
        self.batch_size = batch_size
        self.pending: list[ReferenceDuplicateMember] = []
        self.sequence = 0
        self.duplicate_count = 0

    def add_duplicate(
        self,
        state: _TitleGroupState,
        *,
        reference_id: int,
        match_key_hash: str,
    ) -> None:
        if state.group is None:
            self.sequence += 1
            state.group = ReferenceDuplicateGroup.objects.create(
                dedup_run=self.run,
                sequence=self.sequence,
                representative_reference_id=state.representative_id,
                match_type='normalized_title',
                match_key_hash=match_key_hash,
                display_title=state.display_title,
                member_count=1,
            )
            self.pending.append(ReferenceDuplicateMember(
                dedup_run=self.run,
                group=state.group,
                reference_id=state.representative_id,
                role=ReferenceDuplicateMember.Role.KEPT,
                match_reason='规范化标题完全一致',
                match_score=1,
            ))

        state.member_count += 1
        self.duplicate_count += 1
        self.pending.append(ReferenceDuplicateMember(
            dedup_run=self.run,
            group=state.group,
            reference_id=reference_id,
            role=ReferenceDuplicateMember.Role.DUPLICATE,
            match_reason='规范化标题完全一致',
            match_score=1,
        ))
        if len(self.pending) >= self.batch_size:
            self.flush()

    def finish_hash_bucket(self, states: dict[str, _TitleGroupState]) -> None:
        changed_groups = []
        for state in states.values():
            if state.group is not None:
                state.group.member_count = state.member_count
                changed_groups.append(state.group)
        if changed_groups:
            ReferenceDuplicateGroup.objects.bulk_update(changed_groups, ['member_count'])

    def flush(self) -> None:
        if not self.pending:
            return
        ReferenceDuplicateMember.objects.bulk_create(
            self.pending,
            batch_size=self.batch_size,
        )
        self.pending = []


def build_dedup_run(
    run_id: int,
    *,
    should_cancel: Callable[[], bool] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> DedupRun:
    """Scan one corpus revision with a DB cursor and persist duplicate relations.

    Candidate lookup uses the stored SHA-256 title hash, but every candidate is
    checked again against the full normalized title. This makes hash collision
    candidates safe and prevents empty titles from being grouped together.
    """
    run = DedupRun.objects.select_related('corpus').get(pk=run_id)
    if run.status != DedupRun.Status.RUNNING:
        raise DeduplicationError('invalid_dedup_state', f'去重运行当前状态为 {run.status}。')

    limits = ImportLimits.from_settings()
    batch_size = max(1, limits.processing_batch_size)
    references = (
        ScreeningReference.objects.filter(project_id=run.project_id, corpus_id=run.corpus_id)
        .active_at(run.corpus_revision)
        .order_by('normalized_title_hash', 'id')
        .values('id', 'title', 'normalized_title_hash')
    )
    actual_total = references.count()
    if actual_total != run.total_count:
        raise DeduplicationError(
            'corpus_count_mismatch',
            f'文献集记录数不一致：预期 {run.total_count}，实际 {actual_total}。',
        )

    writer = _DuplicateMemberWriter(run, batch_size)
    current_hash = None
    title_states: dict[str, _TitleGroupState] = {}
    processed = 0

    try:
        for row in references.iterator(chunk_size=batch_size):
            if should_cancel and processed % batch_size == 0 and should_cancel():
                raise DeduplicationCancelled()

            match_hash = row['normalized_title_hash']
            if current_hash is not None and match_hash != current_hash:
                writer.finish_hash_bucket(title_states)
                title_states = {}
            current_hash = match_hash

            normalized_title = normalize_title(row['title'])
            if normalized_title:
                # Never trust the stored hash alone: verify it and then compare
                # the full normalized title inside the candidate bucket.
                computed_hash = hashlib.sha256(normalized_title.encode('utf-8')).hexdigest()
                if computed_hash != match_hash:
                    raise DeduplicationError(
                        'reference_hash_mismatch',
                        f'文献 {row["id"]} 的规范化标题哈希校验失败。',
                    )
                state = title_states.get(normalized_title)
                if state is None:
                    title_states[normalized_title] = _TitleGroupState(
                        representative_id=row['id'],
                        display_title=row['title'],
                    )
                else:
                    writer.add_duplicate(
                        state,
                        reference_id=row['id'],
                        match_key_hash=match_hash,
                    )

            processed += 1
            if on_progress and (processed % batch_size == 0 or processed == actual_total):
                on_progress(processed, actual_total)

        writer.finish_hash_bucket(title_states)
        writer.flush()
        DedupRun.objects.filter(pk=run.id, status=DedupRun.Status.RUNNING).update(
            total_count=actual_total,
            kept_count=actual_total - writer.duplicate_count,
            duplicate_count=writer.duplicate_count,
            group_count=writer.sequence,
            failed_count=0,
            updated_at=timezone.now(),
        )
        run.refresh_from_db()
        return run
    except DeduplicationCancelled:
        cancel_dedup_run(run.id)
        raise
    except Exception:
        fail_dedup_run(run.id)
        raise


def iter_kept_references(run: DedupRun) -> Iterator[ScreeningReference]:
    """Yield kept references for the temporary file-backed downstream bridge."""
    duplicate_ids = ReferenceDuplicateMember.objects.filter(
        dedup_run=run,
        role=ReferenceDuplicateMember.Role.DUPLICATE,
    ).values('reference_id')
    queryset = (
        ScreeningReference.objects.filter(project_id=run.project_id, corpus_id=run.corpus_id)
        .active_at(run.corpus_revision)
        .exclude(id__in=duplicate_ids)
        .order_by('id')
        .select_related('source_file')
    )
    batch_size = max(1, ImportLimits.from_settings().processing_batch_size)
    yield from queryset.iterator(chunk_size=batch_size)


def complete_dedup_run(run_id: int) -> DedupRun:
    """Atomically publish a built run only if its corpus revision is still current."""
    try:
        return _complete_dedup_run(run_id)
    except DeduplicationError:
        fail_dedup_run(run_id)
        raise


def _complete_dedup_run(run_id: int) -> DedupRun:
    with transaction.atomic():
        run = DedupRun.objects.select_for_update().get(pk=run_id)
        corpus = ScreeningCorpus.objects.select_for_update().get(pk=run.corpus_id)
        if run.status != DedupRun.Status.RUNNING:
            raise DeduplicationError('invalid_dedup_state', f'去重运行当前状态为 {run.status}。')
        if corpus.revision != run.corpus_revision:
            raise DeduplicationError(
                'corpus_revision_conflict', '去重期间文献集已发生变化，请重新去重。',
            )
        current_count = ScreeningReference.objects.filter(corpus=corpus).active_at(corpus.revision).count()
        if current_count != run.total_count or current_count != corpus.active_reference_count:
            raise DeduplicationError('corpus_count_mismatch', '去重发布前文献集数量校验失败。')
        if run.kept_count + run.duplicate_count != run.total_count:
            raise DeduplicationError('dedup_count_mismatch', '去重结果数量校验失败。')

        run.status = DedupRun.Status.COMPLETED
        run.finished_at = timezone.now()
        run.save(update_fields=['status', 'finished_at', 'updated_at'])
        corpus.last_dedup_run = run
        corpus.save(update_fields=['last_dedup_run', 'updated_at'])
        return run


def cancel_dedup_run(run_id: int) -> None:
    _finish_unsuccessful_run(run_id, DedupRun.Status.CANCELLED)


def fail_dedup_run(run_id: int) -> None:
    _finish_unsuccessful_run(run_id, DedupRun.Status.FAILED)


def _finish_unsuccessful_run(run_id: int, status: str) -> None:
    with transaction.atomic():
        run = DedupRun.objects.select_for_update().filter(pk=run_id).first()
        if run is None or run.status == DedupRun.Status.COMPLETED:
            return
        run.groups.all().delete()
        run.status = status
        run.kept_count = 0
        run.duplicate_count = 0
        run.group_count = 0
        run.finished_at = timezone.now()
        run.save(update_fields=[
            'status', 'kept_count', 'duplicate_count', 'group_count',
            'finished_at', 'updated_at',
        ])
