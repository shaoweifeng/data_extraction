import json
import re
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from core.models import QAReference
from core.quality.services.evidence_retrieval import (
    EvidenceRetrievalError,
    build_reference_evidence_packages,
)


def _preview(text, limit=320):
    compact = re.sub(r'\s+', ' ', text or '').strip()
    return compact[:limit] + ('…' if len(compact) > limit else '')


class Command(BaseCommand):
    help = '生成不调用模型、且不复制全文的质量评价证据检索验收报告。'

    def add_arguments(self, parser):
        parser.add_argument('--reference-id', type=int, required=True)
        parser.add_argument('--output', required=True)
        parser.add_argument('--signal-key', action='append', default=[])

    def handle(self, *args, **options):
        try:
            reference = QAReference.objects.select_related('fulltext_asset').get(
                pk=options['reference_id']
            )
        except QAReference.DoesNotExist as exc:
            raise CommandError('质量评价文献不存在。') from exc
        try:
            packages = build_reference_evidence_packages(reference)
        except EvidenceRetrievalError as exc:
            raise CommandError(str(exc)) from exc

        requested = set(options['signal_key'])
        available = {
            signal['signal_key']
            for package in packages
            for signal in package['signal_items']
        }
        unknown = requested - available
        if unknown:
            raise CommandError(f'未知信号问题: {", ".join(sorted(unknown))}')

        report_packages = []
        for package in packages:
            signals = [
                signal for signal in package['signal_items']
                if not requested or signal['signal_key'] in requested
            ]
            if not signals:
                continue
            signal_keys = {signal['signal_key'] for signal in signals}
            chunks = []
            for chunk in package['selected_chunks']:
                selected_for = sorted(signal_keys.intersection(chunk['selected_for']))
                if not selected_for:
                    continue
                chunks.append({
                    key: value for key, value in chunk.items() if key != 'text'
                } | {
                    'selected_for': selected_for,
                    'preview': _preview(chunk['text']),
                })
            report_packages.append({
                'domain': package['domain'],
                'domain_name': package['domain_name'],
                'snapshot_sha256': package['snapshot_sha256'],
                'retrieval_version': package['retrieval_version'],
                'char_count': package['char_count'],
                'char_budget': package['char_budget'],
                'signal_items': [{
                    'signal_key': signal['signal_key'],
                    'signal_question': signal['signal_question'],
                    'queries': signal['retrieval']['queries'],
                    'preferred_sections': signal['retrieval']['preferred_sections'],
                    'selected_chunk_ids': package['signal_coverage'][signal['signal_key']],
                } for signal in signals],
                'selected_chunks': chunks,
            })

        report = {
            'reference': {
                'id': reference.id,
                'project_id': reference.project_id,
                'title': reference.title,
                'quality_method': reference.quality_method,
                'quality_method_variant': reference.quality_method_variant,
            },
            'packages': report_packages,
        }
        output_dir = Path(options['output']).expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        stem = f'qa-evidence-reference-{reference.id}'
        json_path = output_dir / f'{stem}.json'
        markdown_path = output_dir / f'{stem}.md'
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

        lines = [
            f'# QA 文献 {reference.id} 证据检索报告', '',
            f'- 项目 ID：{reference.project_id}',
            f'- 标题：{reference.title}',
            f'- 方法：{reference.quality_method} / {reference.quality_method_variant or "默认"}',
            '- 说明：本报告仅含限长预览，不调用模型，也不会产生积分消耗。',
        ]
        for package in report_packages:
            lines.extend([
                '', f"## {package['domain_name']}（{package['domain']}）", '',
                f"- 检索版本：{package['retrieval_version']}",
                f"- 证据字符预算：{package['char_count']} / {package['char_budget']}",
                f"- 快照 SHA256：`{package['snapshot_sha256']}`", '',
                '### 问题覆盖', '',
            ])
            for signal in package['signal_items']:
                ids = '、'.join(signal['selected_chunk_ids']) or '未命中'
                lines.append(f"- `{signal['signal_key']}` {signal['signal_question']}：{ids}")
            lines.extend([
                '', '### 入选证据块', '',
                '| 块 ID | 页码 | 章节 | 得分 | 对应问题 | 命中词 | 预览 |',
                '|---|---:|---|---:|---|---|---|',
            ])
            for chunk in package['selected_chunks']:
                preview = chunk['preview'].replace('|', '\\|')
                queries = '、'.join(chunk['matched_queries']).replace('|', '\\|') or '-'
                lines.append(
                    f"| {chunk['chunk_id']} | {chunk['page_start']}-{chunk['page_end']} | "
                    f"{chunk['section']} | {chunk['score']} | "
                    f"{', '.join(chunk['selected_for'])} | {queries} | {preview} |"
                )
        markdown_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        self.stdout.write(self.style.SUCCESS(str(markdown_path)))
        self.stdout.write(str(json_path))
