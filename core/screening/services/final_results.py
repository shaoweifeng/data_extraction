"""Run-bound iteration over the final screening decision for each reference."""

from dataclasses import dataclass
from typing import Iterator

from core.models import ManualReview
from core.screening.models import ScreeningResult, ScreeningRun
from core.screening.selectors import screening_result_payload
from core.screening.services.decision_service import ScreeningDecisionService


@dataclass(frozen=True)
class ResolvedScreeningRecord:
    result: ScreeningResult
    manual_review: ManualReview | None
    final_decision: str

    @property
    def reference(self):
        return self.result.reference

    def as_payload(self) -> dict:
        return screening_result_payload(self.result)


def iter_resolved_screening_records(
    screening_run: ScreeningRun,
    *,
    batch_size: int = 500,
) -> Iterator[ResolvedScreeningRecord]:
    """Yield one run's results with run-scoped manual decisions in bounded batches."""
    last_pk = 0
    while True:
        batch = list(
            screening_run.results.filter(pk__gt=last_pk)
            .select_related('reference')
            .order_by('pk')[:batch_size]
        )
        if not batch:
            return
        last_pk = batch[-1].pk
        reviews = {
            review.reference_id: review
            for review in ManualReview.objects.filter(
                project_id=screening_run.project_id,
                screening_run=screening_run,
                reference_id__in=[row.reference_id for row in batch],
            ).only('reference_id', 'decision', 'reason', 'is_override')
        }
        for row in batch:
            review = reviews.get(row.reference_id)
            yield ResolvedScreeningRecord(
                result=row,
                manual_review=review,
                final_decision=ScreeningDecisionService.resolve(
                    screening_result_payload(row), review,
                ),
            )
