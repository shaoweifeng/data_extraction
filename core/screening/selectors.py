"""Read models for database-backed screening results."""


def screening_result_payload(result) -> dict:
    """Serialize one database result without exposing storage implementation keys."""
    reference = result.reference
    decision = result.decision
    decisive = decision in ('included', 'excluded')
    reason_id = next(
        (item.get('reason_id', '') for item in result.model_results if item.get('reason_id')),
        '',
    )
    return {
        'reference_id': reference.id,
        'title': reference.title,
        'authors': '; '.join(reference.authors or []),
        'year': reference.publication_year,
        'journal': reference.journal,
        'volume': reference.volume,
        'issue': reference.issue,
        'page': reference.pages,
        'date': reference.publication_date,
        'reference_type': reference.publication_type,
        'pmcid': reference.pmcid,
        'address': reference.address,
        'doi': reference.doi,
        'url': reference.url,
        'abstract': reference.abstract,
        'decision': decision,
        'include_or_not': 'yes' if decision == 'included' else ('no' if decision == 'excluded' else ''),
        'exclusion_reason': result.reason,
        'number_exclusion_reason': reason_id,
        'extracted_fields': result.extracted_fields,
        'multi_model_results': result.model_results,
        'token_usage': result.token_usage,
        'consensus': result.consensus or (decision if decisive else 'pending'),
        'error': result.error_message,
    }


def load_ai_results(project_id) -> list[dict]:
    """Return the current completed run from database storage only."""
    from core.screening.services.screening_run_service import current_completed_screening_run

    run = current_completed_screening_run(project_id)
    if run is None:
        return []
    return [
        screening_result_payload(result)
        for result in run.results.select_related('reference').order_by('id').iterator(chunk_size=500)
    ]
