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

from core.models import ManualReview, StageStep
from core.screening.selectors import ai_result_files


AI_CONFLICT = (
    Q(metadata__consensus='conflict')
    | (Q(metadata__consensus__isnull=True) & Q(metadata__decision='conflict'))
)
AI_INCLUDED = Q(metadata__decision='included')
AI_EXCLUDED = Q(metadata__decision='excluded')
AI_DECISIVE = Q(metadata__decision__in=('included', 'excluded'))


def review_result_queryset(project_id):
    """Return indexed AI results annotated with the matching human decision."""
    ai_step = StageStep.objects.filter(
        stage__project_id=project_id,
        step_key='ai_screen',
    ).order_by('-id').first()
    if not ai_step:
        return None

    reviews = ManualReview.objects.filter(
        project_id=project_id,
        source_xml=OuterRef('metadata__source_xml'),
    )
    return ai_result_files(project_id, ai_step).annotate(
        has_human_review=Exists(reviews),
        human_decision=Subquery(reviews.values('decision')[:1]),
        human_is_override=Subquery(
            reviews.values('is_override')[:1],
            output_field=BooleanField(),
        ),
        ai_excluded_priority=Case(
            When(metadata__decision='excluded', then=Value(0)),
            default=Value(1),
            output_field=IntegerField(),
        ),
    )


def final_decision_filter(decision):
    """Build the database predicate for one review tab."""
    unreviewed = Q(has_human_review=False)

    if decision == 'unreviewed':
        return unreviewed
    if decision == 'included':
        return Q(human_decision='included') | (unreviewed & AI_INCLUDED & ~AI_CONFLICT)
    if decision == 'excluded':
        return Q(human_decision='excluded') | (unreviewed & AI_EXCLUDED & ~AI_CONFLICT)
    if decision == 'conflict':
        return Q(human_decision='conflict') | (unreviewed & AI_CONFLICT)
    if decision == 'pending':
        return Q(human_decision='pending') | (unreviewed & ~AI_DECISIVE & ~AI_CONFLICT)
    return Q()


def aggregate_review_stats(queryset):
    """Calculate all review counters in SQL without loading result JSON files."""
    unreviewed = Q(has_human_review=False)
    decisive_reviewed = Q(human_decision__in=('included', 'excluded'))
    aggregates = queryset.aggregate(
        total=Count('pk'),
        reviewed=Count('pk', filter=Q(has_human_review=True)),
        included=Count('pk', filter=Q(human_decision='included')),
        excluded=Count('pk', filter=Q(human_decision='excluded')),
        pending=Count('pk', filter=Q(human_decision='pending')),
        overridden=Count('pk', filter=Q(human_is_override=True)),
        ai_included=Count('pk', filter=AI_INCLUDED),
        ai_excluded=Count('pk', filter=AI_EXCLUDED & ~AI_CONFLICT),
        ai_conflict=Count('pk', filter=AI_CONFLICT),
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
