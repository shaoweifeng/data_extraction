"""Version-bound write use cases for manual screening review."""

from datetime import datetime, timezone

from django.db import transaction

from core.models import ActivityLog, ManualReview
from core.screening.models import ScreeningResult, ScreeningRun
from core.screening.services.screening_run_service import screening_run_is_current


class ReviewRunError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def _run_result(project_id, run_id, reference_id, *, lock=False, require_current=True):
    run = ScreeningRun.objects.select_related('corpus', 'dedup_run').filter(
        pk=run_id,
        project_id=project_id,
        status=ScreeningRun.Status.COMPLETED,
    ).first()
    if run is None:
        raise ReviewRunError('review_result_not_found', '未找到该文献的初筛结果。')
    if require_current and not screening_run_is_current(run):
        raise ReviewRunError('screening_run_stale', '该结果属于历史文献版本，只能查看，不能修改。')
    queryset = ScreeningResult.objects.filter(
        screening_run=run,
        reference_id=reference_id,
    ).select_related('reference')
    if lock:
        queryset = queryset.select_for_update()
    result = queryset.first()
    if result is None:
        raise ReviewRunError('review_result_not_found', '未找到该文献的初筛结果。')
    return run, result


def _review_defaults(step, result, decision, reason, user):
    original_decision = result.decision if result.decision in ('included', 'excluded') else ''
    return {
        'project_id': result.screening_run.project_id,
        'step': step,
        'ai_decision': original_decision,
        'ai_reason': result.reason,
        'multi_model_results': result.model_results,
        'consensus': result.consensus or original_decision or 'pending',
        'decision': decision,
        'reason': reason,
        'is_override': bool(original_decision) and original_decision != decision,
        'reviewer': user,
    }


def _log_decision(project_id, run_id, reference_id, before, after, user):
    ActivityLog.objects.create(
        project_id=project_id,
        operation_type='review_decision',
        operation_detail={
            'screening_run_id': run_id,
            'reference_id': reference_id,
            'before': before,
            'after': after,
        },
        created_by=user,
    )


@transaction.atomic
def update_review_by_reference(
    project_id,
    step,
    run_id,
    reference_id,
    decision,
    reason,
    user,
):
    run, result = _run_result(project_id, run_id, reference_id, lock=True)
    review = ManualReview.objects.select_for_update().filter(
        screening_run=run,
        reference_id=reference_id,
    ).first()
    before = None if review is None else {
        'decision': review.decision,
        'reason': review.reason,
        'is_override': review.is_override,
    }
    defaults = _review_defaults(step, result, decision, reason, user)
    if review is None:
        review = ManualReview.objects.create(
            screening_run=run,
            reference=result.reference,
            **defaults,
        )
        created = True
    else:
        for field, value in defaults.items():
            setattr(review, field, value)
        # defaults contains the ``project_id`` assignment attribute; a regular
        # save avoids translating that attname incorrectly in update_fields.
        review.save()
        created = False
    after = {
        'decision': review.decision,
        'reason': review.reason,
        'is_override': review.is_override,
    }
    _log_decision(project_id, run.id, reference_id, before, after, user)
    return review, created


@transaction.atomic
def submit_reviews(project_id, step, run_id, review_items, user):
    created_count = 0
    updated_count = 0
    for item in review_items:
        reference_id = item['reference_id']
        if not run_id:
            raise ReviewRunError('screening_run_required', '人工审阅必须指定初筛运行。')
        _, created = update_review_by_reference(
            project_id,
            step,
            run_id,
            reference_id,
            item['decision'],
            item.get('reason', ''),
            user,
        )
        created_count += int(created)
        updated_count += int(not created)
    return created_count, updated_count


@transaction.atomic
def append_note(project_id, step, run_id, reference_id, content, user):
    run, result = _run_result(project_id, run_id, reference_id, lock=True)
    review = ManualReview.objects.select_for_update().filter(
        screening_run=run,
        reference_id=reference_id,
    ).first()
    created = review is None
    if review is None:
        review = ManualReview.objects.create(
            screening_run=run,
            reference=result.reference,
            notes=[],
            **_review_defaults(step, result, 'pending', '', user),
        )
    note = {
        'content': content,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'user': user.username,
    }
    notes = list(review.notes or [])
    notes.append(note)
    review.notes = notes
    review.reviewer = user
    review.save(update_fields=['notes', 'reviewer', 'reviewed_at'])
    ActivityLog.objects.create(
        project_id=project_id,
        operation_type='review_note',
        operation_detail={
            'screening_run_id': run.id,
            'reference_id': reference_id,
            'note_length': len(content),
            'note_count': len(notes),
        },
        created_by=user,
    )
    return review, note, created


def review_notes(project_id, run_id, reference_id):
    run, _ = _run_result(
        project_id,
        run_id,
        reference_id,
        require_current=False,
    )
    review = ManualReview.objects.filter(
        screening_run=run,
        reference_id=reference_id,
    ).only('notes').first()
    return list(reversed(list(review.notes or []))) if review else []
