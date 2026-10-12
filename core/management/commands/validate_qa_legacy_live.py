"""Bounded, audit-only live validation for the legacy QA prompt."""

import hashlib
import json
from collections import defaultdict
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.models import QAFulltextAsset
from core.quality.domain.methods import get_method_config
from core.quality.executors.qa_eval import _build_qa_prompt, _call_model_for_ref


class Command(BaseCommand):
    help = (
        'Run an audit-only legacy QA validation for at most five ready assets. '
        'The command performs live model calls but never changes QA results or credits.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--asset-id', type=int, action='append', required=True)
        parser.add_argument(
            '--models', nargs='+', default=['deepseek-v4-flash', 'qwen3-7-flash'],
        )
        parser.add_argument('--output', required=True)
        parser.add_argument('--confirm-live-calls', action='store_true')

    def handle(self, *args, **options):
        asset_ids = list(dict.fromkeys(options['asset_id']))
        model_ids = list(dict.fromkeys(options['models']))
        if not options['confirm_live_calls']:
            raise CommandError('真实模型验证必须显式传入 --confirm-live-calls。')
        if not 1 <= len(asset_ids) <= 5:
            raise CommandError('一次旧链路验证仅允许 1～5 个全文资产。')
        if not 1 <= len(model_ids) <= 2:
            raise CommandError('一次旧链路验证仅允许 1～2 个模型。')

        asset_map = {
            asset.id: asset
            for asset in QAFulltextAsset.objects.filter(pk__in=asset_ids).select_related(
                'project', 'qa_reference',
            )
        }
        if len(asset_map) != len(asset_ids):
            raise CommandError('部分全文资产不存在。')
        assets = [asset_map[asset_id] for asset_id in asset_ids]
        if len({asset.project_id for asset in assets}) != 1:
            raise CommandError('一次验证的全文资产必须属于同一个项目。')

        report = {
            'schema_version': 'qa-legacy-live-v1',
            'generated_at': timezone.now().isoformat(),
            'asset_ids': asset_ids,
            'models': model_ids,
            'content_limit_chars': settings.QA_AI_MAX_CONTENT_CHARS,
            'records': [],
        }
        usage_total = defaultdict(int)
        usage_by_model = {}
        expected = returned = valid = missing = invalid_judgment = 0

        for asset in assets:
            if asset.status != 'ready' or asset.extraction_status != 'completed':
                raise CommandError(f'asset={asset.id} 尚未完成全文处理。')
            reference = asset.qa_reference
            method = get_method_config(
                reference.quality_method,
                reference.quality_method_variant or None,
            )
            signal_items = method.get('signal_items', [])
            if not signal_items:
                raise CommandError(f'asset={asset.id} 的评价方法不支持 AI 信号问题。')

            try:
                asset.extracted_text_file.open('rb')
                raw = asset.extracted_text_file.read(
                    settings.QA_AI_MAX_CONTENT_CHARS * 4 + 1,
                )
                content = raw.decode('utf-8', errors='replace')[
                    :settings.QA_AI_MAX_CONTENT_CHARS
                ]
            finally:
                try:
                    asset.extracted_text_file.close()
                except Exception:
                    pass
            if len(content.strip()) <= 100:
                raise CommandError(f'asset={asset.id} 没有足够的提取文本。')

            prompt = _build_qa_prompt({
                'title': reference.title,
                'first_author': reference.first_author,
                'year': reference.year,
                'has_fulltext': True,
                'content': content,
            }, signal_items, method['name'])
            record = {
                'asset_id': asset.id,
                'reference_id': reference.id,
                'title': reference.title,
                'content_chars': len(content),
                'content_sha256': hashlib.sha256(content.encode('utf-8')).hexdigest(),
                'prompt_chars': len(prompt),
                'models': {},
            }
            expected_keys = {item['signal_key']: item for item in signal_items}

            for model_id in model_ids:
                results, usage = _call_model_for_ref(model_id, prompt, signal_items)
                result_map = {item['signal_key']: item for item in results}
                normalized = []
                model_valid = model_missing = model_invalid = 0
                for signal_key, signal in expected_keys.items():
                    expected += 1
                    item = result_map.get(signal_key)
                    if item is None:
                        missing += 1
                        model_missing += 1
                        normalized.append({
                            'signal_key': signal_key,
                            'status': 'missing',
                            'judgment': '',
                            'reason': '',
                            'evidence': '',
                            'evidence_page': '',
                        })
                        continue
                    returned += 1
                    status = 'valid'
                    if item.get('judgment') not in signal['options']:
                        status = 'invalid_judgment'
                        invalid_judgment += 1
                        model_invalid += 1
                    else:
                        valid += 1
                        model_valid += 1
                    normalized.append({'status': status, **item})

                usage = usage or {}
                for key in ('prompt', 'completion', 'total', 'cached_prompt_tokens'):
                    value = int(usage.get(key, 0) or 0)
                    usage_total[key] += value
                    usage_by_model.setdefault(model_id, defaultdict(int))[key] += value
                usage_by_model[model_id]['calls'] += 1
                record['models'][model_id] = {
                    'valid': model_valid,
                    'missing': model_missing,
                    'invalid_judgment': model_invalid,
                    'usage': usage,
                    'results': normalized,
                }
            report['records'].append(record)

        report['summary'] = {
            'expected': expected,
            'returned': returned,
            'valid': valid,
            'missing': missing,
            'invalid_judgment': invalid_judgment,
            'valid_rate': valid / expected if expected else 0,
            'token_usage': {
                **dict(usage_total),
                'model_usage': {
                    key: dict(value) for key, value in usage_by_model.items()
                },
            },
        }
        output = Path(options['output']).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        self.stdout.write(json.dumps(report['summary'], ensure_ascii=False, indent=2))
        self.stdout.write(str(output))
