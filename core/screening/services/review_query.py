"""Database-backed queries for the screening review UI."""

from django.db.models import (
    BooleanField,
    Case,
    Count,
    Exists,
    IntegerField,
    OuterRef,
    Q,
    Subquery,
    Value,
    When,
)

from core.models import ManualReview
from core.screening.models import ScreeningRun
from core.screening.services.screening_run_service import (
    latest_completed_screening_run,
    screening_run_is_current,
)


AI_CONFLICT = Q(consensus='conflict')
AI_INCLUDED = Q(decision='included')
AI_EXCLUDED = Q(decision='excluded')
AI_DECISIVE = Q(decision__in=('included', 'excluded'))


def review_result_queryset(project_id, run_id=None):
    """Return current run results annotated with their human decision."""
    if run_id is not None:
        run = ScreeningRun.objects.select_related('corpus', 'dedup_run').filter(
            pk=run_id,
            project_id=project_id,
            status=ScreeningRun.Status.COMPLETED,
        ).first()
    else:
        run = latest_completed_screening_run(project_id)
    if run is None:
        return None

    reviews = ManualReview.objects.filter(
        project_id=project_id,
        screening_run=run,
        reference_id=OuterRef('reference_id'),
    )
    queryset = run.results.select_related('reference').annotate(
        has_human_review=Exists(reviews),
        human_decision=Subquery(reviews.values('decision')[:1]),
        human_is_override=Subquery(
            reviews.values('is_override')[:1],
            output_field=BooleanField(),
        ),
        ai_excluded_priority=Case(
            When(decision='excluded', then=Value(0)),
            default=Value(1),
            output_field=IntegerField(),
        ),
    )
    queryset._screening_database = True
    queryset._screening_run = run
    queryset._screening_is_current = screening_run_is_current(run)
    return queryset


def final_decision_filter(decision):
    """Build the database predicate for one review tab."""
    unreviewed = Q(has_human_review=False)
    conflict = AI_CONFLICT
    included = AI_INCLUDED
    excluded = AI_EXCLUDED
    decisive = AI_DECISIVE
    if decision == 'unreviewed':
        return unreviewed
    if decision == 'included':
        return Q(human_decision='included') | (unreviewed & included & ~conflict)
    if decision == 'excluded':
        return Q(human_decision='excluded') | (unreviewed & excluded & ~conflict)
    if decision == 'conflict':
        return Q(human_decision='conflict') | (unreviewed & conflict)
    if decision == 'pending':
        return Q(human_decision='pending') | (unreviewed & ~decisive & ~conflict)
    return Q()


def aggregate_review_stats(queryset):
    """Calculate review counters in SQL without loading result payloads."""
    conflict = AI_CONFLICT
    included = AI_INCLUDED
    excluded = AI_EXCLUDED
    unreviewed = Q(has_human_review=False)
    decisive_reviewed = Q(human_decision__in=('included', 'excluded'))
    aggregates = queryset.aggregate(
        total=Count('pk'),
        reviewed=Count('pk', filter=Q(has_human_review=True)),
        included=Count('pk', filter=Q(human_decision='included')),
        excluded=Count('pk', filter=Q(human_decision='excluded')),
        pending=Count('pk', filter=Q(human_decision='pending')),
        overridden=Count('pk', filter=Q(human_is_override=True)),
        ai_included=Count('pk', filter=included & ~conflict),
        ai_excluded=Count('pk', filter=excluded & ~conflict),
        ai_conflict=Count('pk', filter=conflict),
        tab_included=Count('pk', filter=final_decision_filter('included')),
        tab_excluded=Count('pk', filter=final_decision_filter('excluded')),
        tab_pending=Count('pk', filter=final_decision_filter('pending')),
        tab_conflict=Count('pk', filter=final_decision_filter('conflict')),
        ai_correct_in_reviewed=Count(
            'pk', filter=decisive_reviewed & Q(human_is_override=False),
        ),
        ai_wrong_in_reviewed=Count(
            'pk', filter=decisive_reviewed & Q(human_is_override=True),
        ),
        decisive_reviewed=Count('pk', filter=decisive_reviewed),
        unreviewed=Count('pk', filter=unreviewed),
    )
    denominator = aggregates['total'] - aggregates['pending']
    numerator = aggregates['ai_correct_in_reviewed'] + aggregates['unreviewed']
    aggregates['ai_accuracy'] = (
        round(numerator / denominator * 100, 1) if denominator > 0 else None
    )
    aggregates['conflict'] = aggregates['tab_conflict']
    aggregates['final_included'] = aggregates['tab_included']
    aggregates['final_excluded'] = aggregates['tab_excluded']
    aggregates['final_conflict_pending'] = (
        aggregates['tab_conflict'] + aggregates['tab_pending']
    )
    return aggregates
