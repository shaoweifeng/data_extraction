"""Benchmark the full-text evidence pipeline against local PDF fixtures."""

from __future__ import annotations

import json
import statistics
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.ai.pricing import calculate_shadow_pricing
from core.quality.domain.methods import get_method_config
from core.quality.services.evidence_evaluation import build_evidence_prompt, call_model_for_evidence
from core.quality.services.evidence_retrieval import build_method_evidence_packages
from core.quality.services.fulltext import extract_page_text
from core.quality.services.fulltext_chunks import build_chunks, estimate_tokens


def _percentile(values, percentile):
    if not values:
        return 0
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile / 100
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 2)


def _summarize(records):
    fields = (
        'page_count', 'extracted_chars', 'chunk_count', 'evidence_chars',
        'estimated_prompt_tokens', 'actual_total_tokens', 'shadow_credits',
        'estimated_cost_cny',
    )
    summary = {'sample_count': len(records), 'successful_count': 0, 'failed_count': 0}
    good = [item for item in records if not item.get('error')]
    summary['successful_count'] = len(good)
    summary['failed_count'] = len(records) - len(good)
    for field in fields:
        values = [float(item[field]) for item in good if item.get(field) is not None]
        summary[field] = {
            'p50': _percentile(values, 50),
            'p75': _percentile(values, 75),
            'p90': _percentile(values, 90),
            'total': round(sum(values), 6),
        }
    return summary


class Command(BaseCommand):
    help = 'Benchmark QA extraction/retrieval locally; --live additionally calls configured models.'

    def add_arguments(self, parser):
        parser.add_argument('--input-dir', required=True)
        parser.add_argument('--limit', type=int, default=30)
        parser.add_argument('--method', default='QUADAS2')
        parser.add_argument('--variant', default='')
        parser.add_argument(
            '--models', nargs='+', default=['deepseek-v4-flash', 'qwen3-7-flash'],
        )
        parser.add_argument('--live', action='store_true')
        parser.add_argument('--output', required=True)

    def handle(self, *args, **options):
        input_dir = Path(options['input_dir']).resolve()
        output = Path(options['output']).resolve()
        limit = options['limit']
        if not input_dir.is_dir():
            raise CommandError('输入目录不存在。')
        if limit < 1 or limit > 100:
            raise CommandError('--limit 必须在 1 到 100 之间。')
        method = get_method_config(options['method'].upper(), options['variant'] or None)
        files = sorted(
            path for path in input_dir.iterdir()
            if path.is_file() and path.suffix.casefold() == '.pdf'
        )[:limit]
        if not files:
            raise CommandError('输入目录中没有 PDF。')

        records = []
        aggregate_model_usage = {}
        for position, path in enumerate(files, 1):
            record = {'file': path.name, 'error': ''}
            try:
                import fitz
                with fitz.open(path) as document:
                    if document.needs_pass:
                        raise ValueError('pdf_encrypted')
                    if len(document) > settings.QA_FULLTEXT_MAX_PAGES:
                        raise ValueError('too_many_pages')
                    extraction = extract_page_text(
                        document, max_chars=settings.QA_PDF_TEXT_MAX_CHARS,
                    )
                    record['page_count'] = len(document)
                chunks = build_chunks(
                    extraction['pages'],
                    target_tokens=settings.QA_CHUNK_TARGET_TOKENS,
                    overlap_tokens=settings.QA_CHUNK_OVERLAP_TOKENS,
                )
                reference = {'title': path.stem, 'first_author': '', 'year': '', 'abstract': ''}
                packages = build_method_evidence_packages(
                    chunks, method, reference,
                    max_chars_per_domain=settings.QA_EVIDENCE_MAX_CHARS_PER_DOMAIN,
                    max_chunks_per_signal=settings.QA_EVIDENCE_MAX_CHUNKS_PER_SIGNAL,
                )
                prompts = [build_evidence_prompt(package, method['name']) for package in packages]
                record.update({
                    'extracted_chars': len(extraction['text']),
                    'extraction_truncated': extraction['truncated'],
                    'chunk_count': len(chunks),
                    'domain_count': len(packages),
                    'evidence_chars': sum(package['char_count'] for package in packages),
                    'estimated_prompt_tokens': sum(estimate_tokens(prompt) for prompt in prompts),
                    'actual_total_tokens': None,
                    'shadow_credits': None,
                    'estimated_cost_cny': None,
                    'model_errors': {},
                })
                if options['live']:
                    model_usage = {}
                    for package, prompt in zip(packages, prompts):
                        for model_id in options['models']:
                            _, usage, errors = call_model_for_evidence(model_id, prompt, package)
                            if errors:
                                record['model_errors'].setdefault(model_id, []).extend(errors)
                            if not usage:
                                continue
                            target = model_usage.setdefault(model_id, {
                                'prompt_tokens': 0, 'completion_tokens': 0,
                                'total_tokens': 0, 'cached_prompt_tokens': 0, 'calls': 0,
                            })
                            prompt_tokens = int(usage.get('prompt', usage.get('prompt_tokens', 0)) or 0)
                            completion_tokens = int(
                                usage.get('completion', usage.get('completion_tokens', 0)) or 0
                            )
                            target['prompt_tokens'] += prompt_tokens
                            target['completion_tokens'] += completion_tokens
                            target['total_tokens'] += int(
                                usage.get('total', usage.get('total_tokens', 0))
                                or prompt_tokens + completion_tokens
                            )
                            target['cached_prompt_tokens'] += int(
                                usage.get('cached_prompt_tokens', 0) or 0
                            )
                            target['calls'] += 1
                    pricing = calculate_shadow_pricing(model_usage)
                    record['model_usage'] = model_usage
                    record['actual_total_tokens'] = sum(
                        item['total_tokens'] for item in model_usage.values()
                    )
                    record['shadow_credits'] = pricing['shadow_credits']
                    record['estimated_cost_cny'] = (
                        float(pricing['estimated_cost_cny'])
                        if pricing['estimated_cost_cny'] is not None else None
                    )
                    for model_id, usage in model_usage.items():
                        target = aggregate_model_usage.setdefault(model_id, {
                            'prompt_tokens': 0, 'completion_tokens': 0,
                            'total_tokens': 0, 'cached_prompt_tokens': 0, 'calls': 0,
                        })
                        for key in target:
                            target[key] += usage[key]
            except Exception as exc:
                record['error'] = f'{type(exc).__name__}: {exc}'[:500]
            records.append(record)
            self.stdout.write(f'[{position}/{len(files)}] {path.name}: {record["error"] or "ok"}')

        aggregate_pricing = calculate_shadow_pricing(aggregate_model_usage)
        report = {
            'schema_version': 'qa-evidence-benchmark-v1',
            'mode': 'live' if options['live'] else 'local',
            'input_dir': str(input_dir),
            'method': method['key'],
            'method_variant': method.get('variant_key', ''),
            'models': options['models'] if options['live'] else [],
            'settings': {
                'max_pages': settings.QA_FULLTEXT_MAX_PAGES,
                'max_chars': settings.QA_PDF_TEXT_MAX_CHARS,
                'chunk_target_tokens': settings.QA_CHUNK_TARGET_TOKENS,
                'chunk_overlap_tokens': settings.QA_CHUNK_OVERLAP_TOKENS,
                'evidence_chars_per_domain': settings.QA_EVIDENCE_MAX_CHARS_PER_DOMAIN,
                'evidence_chunks_per_signal': settings.QA_EVIDENCE_MAX_CHUNKS_PER_SIGNAL,
            },
            'summary': _summarize(records),
            'aggregate_model_usage': aggregate_model_usage,
            'aggregate_pricing': {
                'pricing_version': aggregate_pricing['pricing_version'],
                'shadow_credits': aggregate_pricing['shadow_credits'],
                'estimated_cost_cny': (
                    str(aggregate_pricing['estimated_cost_cny'])
                    if aggregate_pricing['estimated_cost_cny'] is not None else None
                ),
                'unknown_models': aggregate_pricing['unknown_models'],
            },
            'records': records,
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        self.stdout.write(self.style.SUCCESS(
            f'报告已写入 {output}；成功 {report["summary"]["successful_count"]}，'
            f'失败 {report["summary"]["failed_count"]}'
        ))
