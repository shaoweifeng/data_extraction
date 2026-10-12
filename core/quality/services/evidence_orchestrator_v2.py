"""Production orchestration for the reference-by-ID QA evidence protocol."""

from __future__ import annotations

import json
import uuid
from collections import Counter, defaultdict

from django.db import transaction
from django.utils import timezone

from core.models import (
    QADomainResult,
    QAEvaluationRun,
    QAModelSignalResult,
    QAReviewContext,
    QASignalItem,
)
from core.quality.domain.methods import get_method_config
from core.quality.services.domain_results import recalculate_domain_results
from core.quality.services.evidence_protocol_v2 import (
    PROTOCOL_VERSION,
    PROMPT_VERSION,
    build_needs_review_fallback,
    build_v2_prompt,
    call_model_v2,
)
from core.quality.services.evidence_retrieval import (
    RETRIEVAL_VERSION,
    build_reference_evidence_packages,
)
from core.quality.services.fulltext_chunks import CHUNKING_VERSION
from core.services.ai_models_config import get_model_config


MAX_MODEL_ATTEMPTS = 2
TRUSTED_STATUSES = {'validated', 'no_evidence'}
TERMINAL_STATUSES = TRUSTED_STATUSES | {'needs_review'}
RETRYABLE_ERROR_CODES = {
    'provider_failed', 'empty_response', 'json_parse_failed', 'missing_valid_result',
}


def _error_json(errors: list[dict]) -> str:
    value = json.dumps(errors, ensure_ascii=False, separators=(',', ':'))
    if len(value) <= 500:
        return value
    compact = [{
        'code': item.get('code', 'unknown_error'),
        'signal_key': item.get('signal_key', ''),
        'returned_refs': item.get('returned_refs', []),
    } for item in errors]
    return json.dumps(compact, ensure_ascii=False, separators=(',', ':'))[:500]


def _stored_errors(row: QAModelSignalResult) -> list[dict]:
    if not row.error_message:
        return []
    try:
        parsed = json.loads(row.error_message)
        return parsed if isinstance(parsed, list) else []
    except (TypeError, ValueError, json.JSONDecodeError):
        return [{'code': row.error_code or 'unknown_error'}]


def _review_context(reference) -> dict | None:
    row = QAReviewContext.objects.filter(
        project_id=reference.project_id,
        quality_method=reference.quality_method,
        method_variant=reference.quality_method_variant or '',
    ).first()
    if not row:
        return None
    context = {
        'target_population': row.target_population,
        'index_test': row.index_test,
        'target_condition': row.target_condition,
        'reference_standard': row.reference_standard,
        'intended_use': row.intended_use,
        'review_objective': row.review_objective,
    }
    return context if any(context.values()) else None


def _merge_usage(target: dict, usage: dict | None, model_id: str) -> None:
    if not usage:
        return
    prompt = int(usage.get('prompt', usage.get('prompt_tokens', 0)) or 0)
    completion = int(usage.get('completion', usage.get('completion_tokens', 0)) or 0)
    total = int(usage.get('total', usage.get('total_tokens', 0)) or prompt + completion)
    cached = int(usage.get('cached_prompt_tokens', 0) or 0)
    target['prompt'] = int(target.get('prompt', 0)) + prompt
    target['completion'] = int(target.get('completion', 0)) + completion
    target['total'] = int(target.get('total', 0)) + total
    model_usage = target.setdefault('model_usage', {}).setdefault(model_id, {
        'prompt_tokens': 0,
        'completion_tokens': 0,
        'total_tokens': 0,
        'cached_prompt_tokens': 0,
        'calls': 0,
    })
    model_usage['prompt_tokens'] += prompt
    model_usage['completion_tokens'] += completion
    model_usage['total_tokens'] += total
    model_usage['cached_prompt_tokens'] += cached
    model_usage['calls'] += 1


def _page_label(evidence: list[dict]) -> str:
    pages = sorted({item.get('page_number') for item in evidence if item.get('page_number')})
    return '、'.join(f'第{page}页' for page in pages)


def _public_model_result(row: QAModelSignalResult, model_name: str) -> dict:
    evidence = row.resolved_evidence if isinstance(row.resolved_evidence, list) else []
    first = evidence[0] if evidence else {}
    return {
        'model_id': row.model_id,
        'model_name': model_name,
        'judgment': row.judgment if row.status in TRUSTED_STATUSES else '',
        'reason': row.reason,
        'evidence': '\n'.join(
            str(item.get('text') or '') for item in evidence if item.get('text')
        )[:2400],
        'evidence_page': _page_label(evidence),
        'evidence_chunk_id': first.get('chunk_id', ''),
        'evidence_span_ids': [
            item.get('span_id') for item in evidence if item.get('span_id')
        ],
        'evidence_page_start': first.get('page_number'),
        'evidence_page_end': first.get('page_number'),
        'evidence_section': first.get('section', ''),
        'evidence_sha256': first.get('sha256', ''),
        'evidence_refs': row.evidence_refs,
        'prompt_version': row.prompt_version,
        'retrieval_version': row.retrieval_version,
        'method_config_version': row.method_config_version,
        'evidence_snapshot_sha256': row.evidence_snapshot_sha256,
        'validation_status': row.status,
        'validation_errors': _stored_errors(row),
        'error_code': row.error_code,
    }


class EvidenceV2Orchestrator:
    """Persist V2 calls independently and project trusted results into the review UI."""

    def __init__(
        self,
        *,
        project_id: int,
        model_ids: list[str],
        user_id: int | None = None,
        task=None,
        resume_ref_ids: set[int] | None = None,
        resume_all_incomplete: bool = False,
        stop_checker=None,
    ):
        self.project_id = project_id
        self.model_ids = list(dict.fromkeys(model_ids))
        self.user_id = user_id
        self.task = task
        self.resume_ref_ids = set(resume_ref_ids or [])
        self.resume_all_incomplete = resume_all_incomplete
        self.stop_checker = stop_checker
        self.run = None
        self.was_stopped = False

    def _ensure_run(self) -> QAEvaluationRun:
        if self.run:
            return self.run
        idempotency_key = (
            f'qa-evidence-v2-task:{self.task.id}' if self.task else
            f'qa-evidence-v2-direct:{uuid.uuid4()}'
        )
        defaults = {
            'project_id': self.project_id,
            'task': self.task,
            'created_by_id': self.user_id,
            'status': 'running',
            'model_ids': self.model_ids,
            'protocol_version': PROTOCOL_VERSION,
            'retrieval_version': RETRIEVAL_VERSION,
            'chunking_version': CHUNKING_VERSION,
            'started_at': timezone.now(),
        }
        self.run, _ = QAEvaluationRun.objects.get_or_create(
            idempotency_key=idempotency_key,
            defaults=defaults,
        )
        if self.run.status != 'running':
            self.run.status = 'running'
            self.run.completed_at = None
            self.run.save(update_fields=['status', 'completed_at', 'updated_at'])
        return self.run

    def _can_reuse_call(self, rows: dict[str, QAModelSignalResult], signals, snapshot) -> bool:
        for signal in signals:
            row = rows.get(signal['signal_key'])
            if not row or row.evidence_snapshot_sha256 != snapshot['snapshot_sha256']:
                return False
            if row.status in TERMINAL_STATUSES:
                continue
            if row.attempt_count < MAX_MODEL_ATTEMPTS:
                return False
        return True

    def _persist_model_call(
        self,
        *,
        reference,
        package: dict,
        snapshot: dict,
        model_id: str,
        results: list[dict],
        errors: list[dict],
        usage: dict | None,
        response_sha256: str,
    ) -> None:
        result_map = {item['signal_key']: item for item in results}
        errors_by_signal = defaultdict(list)
        general_errors = []
        for error in errors:
            if error.get('signal_key'):
                errors_by_signal[error['signal_key']].append(error)
            else:
                general_errors.append(error)

        for signal in package['signal_items']:
            key = signal['signal_key']
            signal_errors = errors_by_signal.get(key) or []
            result = result_map.get(key)
            if result and not signal_errors:
                status = result['validation_status']
                stored_errors = []
            else:
                stored_errors = signal_errors or general_errors or [{
                    'code': 'missing_valid_result', 'signal_key': key,
                }]
                result = build_needs_review_fallback(signal, stored_errors)
                codes = {item.get('code') for item in stored_errors}
                if 'provider_failed' in codes:
                    status = 'provider_failed'
                elif codes & RETRYABLE_ERROR_CODES:
                    status = 'invalid_response'
                else:
                    status = 'needs_review'

            existing = QAModelSignalResult.objects.filter(
                evaluation_run=self.run,
                qa_reference=reference,
                signal_key=key,
                model_id=model_id,
            ).first()
            attempts = (existing.attempt_count if existing else 0) + 1
            QAModelSignalResult.objects.update_or_create(
                evaluation_run=self.run,
                qa_reference=reference,
                signal_key=key,
                model_id=model_id,
                defaults={
                    'status': status,
                    'judgment': result.get('judgment', '') if status in TRUSTED_STATUSES else '',
                    'reason': result.get('reason', ''),
                    'evidence_refs': result.get('evidence_refs', []),
                    'resolved_evidence': (
                        result.get('resolved_evidence', []) if status in TRUSTED_STATUSES else []
                    ),
                    'evidence_snapshot_sha256': snapshot['snapshot_sha256'],
                    'prompt_version': PROMPT_VERSION,
                    'retrieval_version': RETRIEVAL_VERSION,
                    'chunking_version': CHUNKING_VERSION,
                    'method_config_version': package.get('method_config_version', ''),
                    'response_sha256': response_sha256,
                    'error_code': (stored_errors[0].get('code', '') if stored_errors else ''),
                    'error_message': _error_json(stored_errors) if stored_errors else '',
                    'token_usage': usage or {},
                    'attempt_count': min(attempts, MAX_MODEL_ATTEMPTS),
                    'started_at': existing.started_at if existing else timezone.now(),
                    'completed_at': timezone.now(),
                },
            )

    def _project_domain(self, reference, package: dict, *, preserve_confirmation: bool) -> bool:
        model_names = {
            model_id: (get_model_config(model_id) or {}).get('name', model_id)
            for model_id in self.model_ids
        }
        rows = QAModelSignalResult.objects.filter(
            evaluation_run=self.run,
            qa_reference=reference,
            signal_key__in=[item['signal_key'] for item in package['signal_items']],
            model_id__in=self.model_ids,
        )
        by_signal_model = {(row.signal_key, row.model_id): row for row in rows}
        domain_reviewable = True
        for signal in package['signal_items']:
            model_results = []
            for model_id in self.model_ids:
                row = by_signal_model.get((signal['signal_key'], model_id))
                if row:
                    model_results.append(_public_model_result(
                        row, model_names.get(model_id, model_id),
                    ))
            trusted = [
                item for item in model_results
                if item.get('validation_status') in TRUSTED_STATUSES and item.get('judgment')
            ]
            if not trusted and not any(
                item.get('validation_status') == 'needs_review' for item in model_results
            ):
                domain_reviewable = False

            from core.quality.executors.qa_eval import _determine_consistency
            consistency, recommendation = _determine_consistency(model_results)
            first_valid = next(
                (item for item in trusted if item['judgment'] == recommendation),
                trusted[0] if trusted else (model_results[0] if model_results else {}),
            )
            model1 = model_results[0] if model_results else {}
            model2 = model_results[1] if len(model_results) > 1 else {}
            defaults = {
                'quality_method': reference.quality_method,
                'domain': signal['domain'],
                'result_type': signal['result_type'],
                'signal_question': signal['signal_question'],
                'signal_description': signal['signal_description'],
                'options': signal['options'],
                'ai_judgment': recommendation,
                'ai_reason': first_valid.get('reason', ''),
                'ai_evidence': first_valid.get('evidence', ''),
                'ai_evidence_page': first_valid.get('evidence_page', ''),
                'model_results': model_results,
                'model1_id': model1.get('model_id', ''),
                'model1_judgment': model1.get('judgment', ''),
                'model1_reason': model1.get('reason', ''),
                'model2_id': model2.get('model_id', ''),
                'model2_judgment': model2.get('judgment', ''),
                'model2_reason': model2.get('reason', ''),
                'consistency': consistency,
                'system_recommendation': recommendation,
                'pre_selected': recommendation,
            }
            if not preserve_confirmation:
                defaults.update({
                    'human_judgment': '',
                    'is_modified': False,
                    'original_ai_judgment': '',
                    'is_confirmed': False,
                    'confirmed_by': None,
                    'confirmed_at': None,
                })
            QASignalItem.objects.update_or_create(
                qa_ref=reference,
                signal_key=signal['signal_key'],
                defaults=defaults,
            )
        return domain_reviewable

    def evaluate_reference(self, reference) -> dict | None:
        self._ensure_run()
        method = get_method_config(
            reference.quality_method, reference.quality_method_variant or None,
        )
        context = _review_context(reference)
        packages = build_reference_evidence_packages(reference)
        # A duplicate delivery of the same task must not erase a human confirmation
        # that may have happened after the first delivery completed.
        same_run_has_rows = QAModelSignalResult.objects.filter(
            evaluation_run=self.run,
            qa_reference=reference,
        ).exists()
        preserve = (
            self.resume_all_incomplete
            or reference.id in self.resume_ref_ids
            or same_run_has_rows
        )
        if not preserve:
            QASignalItem.objects.filter(qa_ref=reference).delete()
            QADomainResult.objects.filter(qa_ref=reference).delete()

        stats = {'prompt': 0, 'completion': 0, 'total': 0}
        all_domains_reviewable = True
        method_versions = set(filter(None, [self.run.method_config_version]))
        method_versions.add(method.get('config_version', ''))

        for package in packages:
            if self.stop_checker and self.stop_checker():
                self.was_stopped = True
                reference.__class__.objects.filter(pk=reference.id).update(ai_eval_status='pending')
                self.run.status = 'stopped'
                self.run.completed_at = timezone.now()
                self.run.save(update_fields=['status', 'completed_at', 'updated_at'])
                return stats if stats['total'] else None

            prompt, snapshot = build_v2_prompt(
                package, method['name'], review_context=context,
            )
            signal_keys = [item['signal_key'] for item in package['signal_items']]
            for model_id in self.model_ids:
                existing = {
                    row.signal_key: row for row in QAModelSignalResult.objects.filter(
                        evaluation_run=self.run,
                        qa_reference=reference,
                        signal_key__in=signal_keys,
                        model_id=model_id,
                    )
                }
                if self._can_reuse_call(existing, package['signal_items'], snapshot):
                    continue
                results, usage, errors, response_sha256 = call_model_v2(
                    model_id, prompt, package, snapshot,
                )
                _merge_usage(stats, usage, model_id)
                self._persist_model_call(
                    reference=reference,
                    package=package,
                    snapshot=snapshot,
                    model_id=model_id,
                    results=results,
                    errors=errors,
                    usage=usage,
                    response_sha256=response_sha256,
                )
            if not self._project_domain(
                reference, package, preserve_confirmation=preserve,
            ):
                all_domains_reviewable = False

        self.run.method_config_version = ','.join(sorted(method_versions))[:32]
        current_usage = dict(self.run.token_usage or {})
        for key in ('prompt', 'completion', 'total'):
            current_usage[key] = int(current_usage.get(key, 0)) + int(stats.get(key, 0))
        for model_id, values in stats.get('model_usage', {}).items():
            target = current_usage.setdefault('model_usage', {}).setdefault(model_id, {
                key: 0 for key in (
                    'prompt_tokens', 'completion_tokens', 'total_tokens',
                    'cached_prompt_tokens', 'calls',
                )
            })
            for key, value in values.items():
                target[key] = int(target.get(key, 0)) + int(value or 0)
        self.run.token_usage = current_usage
        self.run.save(update_fields=[
            'method_config_version', 'token_usage', 'updated_at',
        ])

        final_status = 'completed' if all_domains_reviewable else 'failed'
        reference.__class__.objects.filter(pk=reference.id).update(ai_eval_status=final_status)
        reference.refresh_from_db()
        recalculate_domain_results(reference)
        return stats if stats['total'] else None

    def finalize(self, *, stopped: bool = False) -> None:
        if not self.run:
            return
        rows = self.run.signal_results.all()
        counts = Counter(rows.values_list('status', flat=True))
        self.run.requested_count = rows.count()
        self.run.validated_count = counts['validated']
        self.run.skipped_count = counts['no_evidence']
        self.run.failed_count = sum(
            count for status, count in counts.items() if status not in TRUSTED_STATUSES
        )
        self.run.error_summary = dict(Counter(
            code for code in rows.exclude(error_code='').values_list('error_code', flat=True)
        ))
        if stopped or self.was_stopped:
            self.run.status = 'stopped'
        elif counts['provider_failed'] or counts['invalid_response']:
            self.run.status = 'partial'
        elif rows.exists():
            self.run.status = 'completed'
        else:
            self.run.status = 'failed'
        self.run.completed_at = timezone.now()
        self.run.save(update_fields=[
            'status', 'requested_count', 'validated_count', 'skipped_count',
            'failed_count', 'error_summary', 'completed_at', 'updated_at',
        ])
