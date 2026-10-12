"""Bounded live canary for the V2 QA evidence protocol."""

import json
import uuid
from collections import defaultdict
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.models import (
    QAEvaluationRun,
    QAFulltextAsset,
    QAModelSignalResult,
    QAReviewContext,
)
from core.quality.domain.methods import get_method_config
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


class Command(BaseCommand):
    help = (
        'Run a maximum-three-document live V2 evidence canary. Results are written '
        'only to V2 audit tables; existing QA decisions and user credits are untouched.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--asset-id', type=int, action='append', required=True)
        parser.add_argument(
            '--models', nargs='+', default=['deepseek-v4-flash', 'qwen3-7-flash'],
        )
        parser.add_argument('--output', required=True)
        parser.add_argument('--max-invalid-rate', type=float, default=0.05)
        parser.add_argument('--confirm-live-calls', action='store_true')

    def handle(self, *args, **options):
        asset_ids = list(dict.fromkeys(options['asset_id']))
        model_ids = list(dict.fromkeys(options['models']))
        if not options['confirm_live_calls']:
            raise CommandError('真实模型验证必须显式传入 --confirm-live-calls。')
        if not 1 <= len(asset_ids) <= 3:
            raise CommandError('一次真实验证仅允许 1～3 个全文资产。')
        if not 1 <= len(model_ids) <= 2:
            raise CommandError('一次真实验证仅允许 1～2 个模型。')
        if not 0 <= options['max_invalid_rate'] <= 1:
            raise CommandError('--max-invalid-rate 必须在 0～1 之间。')

        assets = list(QAFulltextAsset.objects.filter(pk__in=asset_ids).select_related(
            'project', 'qa_reference',
        ).order_by('id'))
        if len(assets) != len(asset_ids):
            raise CommandError('部分全文资产不存在。')
        if len({asset.project_id for asset in assets}) != 1:
            raise CommandError('一次验证的全文资产必须属于同一个项目。')
        for asset in assets:
            if asset.status != 'ready' or asset.extraction_status != 'completed':
                raise CommandError(f'asset={asset.id} 尚未完成全文处理。')
            if asset.chunking_version != CHUNKING_VERSION:
                raise CommandError(
                    f'asset={asset.id} 的索引版本是 {asset.chunking_version or "空"}，'
                    f'必须先重建为 {CHUNKING_VERSION}。'
                )

        project = assets[0].project
        run = QAEvaluationRun.objects.create(
            project=project,
            status='running',
            model_ids=model_ids,
            protocol_version=PROTOCOL_VERSION,
            retrieval_version=RETRIEVAL_VERSION,
            chunking_version=CHUNKING_VERSION,
            idempotency_key=f'qa-v2-live-canary:{uuid.uuid4()}',
            started_at=timezone.now(),
        )
        report = {
            'run_id': run.id,
            'run_uuid': str(run.run_uuid),
            'asset_ids': asset_ids,
            'models': model_ids,
            'protocol_version': PROTOCOL_VERSION,
            'prompt_version': PROMPT_VERSION,
            'retrieval_version': RETRIEVAL_VERSION,
            'chunking_version': CHUNKING_VERSION,
            'records': [],
        }
        usage_total = defaultdict(int)
        usage_by_model = {}
        requested = validated = skipped = failed = 0
        method_versions = set()
        error_counts = defaultdict(int)
        try:
            for asset in assets:
                reference = asset.qa_reference
                method = get_method_config(
                    reference.quality_method,
                    reference.quality_method_variant or None,
                )
                method_versions.add(method.get('config_version', ''))
                context_row = QAReviewContext.objects.filter(
                    project_id=project.id,
                    quality_method=reference.quality_method,
                    method_variant=reference.quality_method_variant or '',
                ).first()
                review_context = None
                if context_row and any([
                    context_row.target_population, context_row.index_test,
                    context_row.target_condition, context_row.reference_standard,
                    context_row.intended_use, context_row.review_objective,
                ]):
                    review_context = {
                        'target_population': context_row.target_population,
                        'index_test': context_row.index_test,
                        'target_condition': context_row.target_condition,
                        'reference_standard': context_row.reference_standard,
                        'intended_use': context_row.intended_use,
                        'review_objective': context_row.review_objective,
                    }
                packages = build_reference_evidence_packages(reference)
                record = {
                    'asset_id': asset.id,
                    'reference_id': reference.id,
                    'title': reference.title,
                    'has_review_context': bool(review_context),
                    'domains': [],
                }
                for package in packages:
                    prompt, snapshot = build_v2_prompt(
                        package, method['name'], review_context=review_context,
                    )
                    if len(prompt) > 90_000:
                        raise CommandError(
                            f'asset={asset.id} domain={package["domain"]} Prompt超过安全预算。'
                        )
                    domain_record = {
                        'domain': package['domain'],
                        'prompt_chars': len(prompt),
                        'catalog_size': len(snapshot['catalog']),
                        'models': {},
                    }
                    expected_keys = [item['signal_key'] for item in package['signal_items']]
                    for model_id in model_ids:
                        results, usage, errors, response_sha256 = call_model_v2(
                            model_id, prompt, package, snapshot,
                        )
                        result_map = {item['signal_key']: item for item in results}
                        errors_by_signal = defaultdict(list)
                        general_errors = []
                        for error in errors:
                            code = error.get('code', 'unknown_error')
                            error_counts[code] += 1
                            if error.get('signal_key'):
                                errors_by_signal[error['signal_key']].append(error)
                            else:
                                general_errors.append(error)
                        for key in ('prompt', 'completion', 'total', 'cached_prompt_tokens'):
                            value = int((usage or {}).get(key, 0) or 0)
                            usage_total[key] += value
                            target = usage_by_model.setdefault(model_id, defaultdict(int))
                            target[key] += value
                        usage_by_model[model_id]['calls'] += 1

                        rows = []
                        model_validated = model_skipped = model_failed = 0
                        for signal in package['signal_items']:
                            requested += 1
                            result = result_map.get(signal['signal_key'])
                            signal_errors = errors_by_signal.get(signal['signal_key']) or []
                            if result and not signal_errors:
                                status = result['validation_status']
                                if status == 'validated':
                                    validated += 1
                                    model_validated += 1
                                else:
                                    skipped += 1
                                    model_skipped += 1
                                error_code = ''
                                error_message = ''
                            else:
                                signal_errors = signal_errors or general_errors
                                if not signal_errors:
                                    signal_errors = [{
                                        'code': 'missing_valid_result',
                                        'signal_key': signal['signal_key'],
                                    }]
                                result = build_needs_review_fallback(signal, signal_errors)
                                status = result['validation_status']
                                failed += 1
                                model_failed += 1
                                error_code = signal_errors[0].get(
                                    'code', 'missing_valid_result',
                                )[:64]
                                error_message = json.dumps(
                                    signal_errors, ensure_ascii=False, separators=(',', ':'),
                                )[:500]
                            rows.append(QAModelSignalResult(
                                evaluation_run=run,
                                qa_reference=reference,
                                signal_key=signal['signal_key'],
                                model_id=model_id,
                                status=status,
                                judgment=result.get('judgment', ''),
                                reason=result.get('reason', ''),
                                evidence_refs=result.get('evidence_refs', []),
                                resolved_evidence=result.get('resolved_evidence', []),
                                evidence_snapshot_sha256=snapshot['snapshot_sha256'],
                                prompt_version=PROMPT_VERSION,
                                retrieval_version=RETRIEVAL_VERSION,
                                chunking_version=CHUNKING_VERSION,
                                method_config_version=method.get('config_version', ''),
                                response_sha256=response_sha256,
                                error_code=error_code,
                                error_message=error_message,
                                token_usage=usage or {},
                                attempt_count=1,
                                started_at=run.started_at,
                                completed_at=timezone.now(),
                            ))
                        QAModelSignalResult.objects.bulk_create(rows)
                        domain_record['models'][model_id] = {
                            'validated': model_validated,
                            'no_evidence': model_skipped,
                            'failed': model_failed,
                            'errors': errors,
                            'usage': usage or {},
                            'response_sha256': response_sha256,
                        }
                    record['domains'].append(domain_record)
                report['records'].append(record)
        except Exception as exc:
            run.status = 'failed'
            run.error_summary = {'command_error': type(exc).__name__}
            run.completed_at = timezone.now()
            run.save(update_fields=['status', 'error_summary', 'completed_at', 'updated_at'])
            raise

        invalid_rate = failed / requested if requested else 1.0
        run.status = 'completed' if failed == 0 else 'partial'
        run.requested_count = requested
        run.validated_count = validated
        run.skipped_count = skipped
        run.failed_count = failed
        run.method_config_version = ','.join(sorted(method_versions))[:32]
        run.token_usage = {
            **dict(usage_total),
            'model_usage': {key: dict(value) for key, value in usage_by_model.items()},
        }
        run.error_summary = dict(error_counts)
        run.completed_at = timezone.now()
        run.save()
        report['summary'] = {
            'requested': requested,
            'validated': validated,
            'no_evidence': skipped,
            'failed': failed,
            'invalid_rate': invalid_rate,
            'error_counts': dict(error_counts),
            'token_usage': run.token_usage,
        }
        output = Path(options['output']).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        self.stdout.write(json.dumps(report['summary'], ensure_ascii=False, indent=2))
        self.stdout.write(str(output))
        if invalid_rate > options['max_invalid_rate']:
            raise CommandError(
                f'V2无效结果率 {invalid_rate:.2%} 超过阈值 '
                f'{options["max_invalid_rate"]:.2%}，不得扩大灰度。'
            )
