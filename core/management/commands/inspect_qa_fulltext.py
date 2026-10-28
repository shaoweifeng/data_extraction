import json
import re
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from core.models import QAFulltextAsset
from core.quality.services.evidence_retrieval import (
    EvidenceRetrievalError,
    load_verified_chunks,
)


def _preview(text, *, limit=180):
    compact = re.sub(r'\s+', ' ', text or '').strip()
    return compact[:limit] + ('…' if len(compact) > limit else '')


def _match_context(text, phrase, *, radius=100):
    index = (text or '').lower().find(phrase.lower())
    if index < 0:
        return None
    start = max(0, index - radius)
    end = min(len(text), index + len(phrase) + radius)
    return _preview(text[start:end], limit=radius * 2 + len(phrase))


class Command(BaseCommand):
    help = 'Generate a bounded, read-only QA full-text extraction/chunk inspection report.'

    def add_arguments(self, parser):
        parser.add_argument('--asset-id', type=int, required=True)
        parser.add_argument('--asset-kind', choices=['qa', 'shared'], default='qa')
        parser.add_argument('--output', required=True)
        parser.add_argument('--find', action='append', default=[])

    def handle(self, *args, **options):
        try:
            from core.fulltext.models import FulltextAsset
            model = FulltextAsset if options['asset_kind'] == 'shared' else QAFulltextAsset
            related = ('project',) if options['asset_kind'] == 'shared' else ('project', 'qa_reference')
            asset = model.objects.select_related(*related).get(
                pk=options['asset_id']
            )
        except model.DoesNotExist as exc:
            raise CommandError('质量评价全文资产不存在。') from exc

        output_dir = Path(options['output']).expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        try:
            chunks = load_verified_chunks(asset)
        except EvidenceRetrievalError as exc:
            raise CommandError(str(exc)) from exc
        chunk_rows = [{
            'chunk_id': chunk.get('chunk_id'),
            'page_start': chunk.get('page_start'),
            'page_end': chunk.get('page_end'),
            'section': chunk.get('section'),
            'estimated_tokens': chunk.get('estimated_tokens'),
            'char_count': chunk.get('char_count'),
            'sha256': chunk.get('sha256'),
            'span_count': len(chunk.get('evidence_spans') or []),
            'preview': _preview(chunk.get('text', '')),
        } for chunk in chunks]
        unique_spans = {
            span.get('span_id'): span
            for chunk in chunks
            for span in (chunk.get('evidence_spans') or [])
            if span.get('span_id')
        }

        matches = []
        for phrase in options['find']:
            phrase_matches = []
            for chunk in chunks:
                context = _match_context(chunk.get('text', ''), phrase)
                if context:
                    phrase_matches.append({
                        'chunk_id': chunk.get('chunk_id'),
                        'page_start': chunk.get('page_start'),
                        'page_end': chunk.get('page_end'),
                        'context': context,
                    })
            matches.append({'phrase': phrase, 'matches': phrase_matches})

        report = {
            'asset_id': asset.id,
            'project_id': asset.project_id,
            'reference_id': getattr(asset, 'qa_reference_id', None),
            'asset_kind': options['asset_kind'],
            'original_filename': asset.original_filename,
            'status': asset.status,
            'extraction_status': asset.extraction_status,
            'page_count': asset.page_count,
            'extracted_page_count': asset.extracted_page_count,
            'extracted_text_chars': asset.extracted_text_chars,
            'extraction_truncated': asset.extraction_truncated,
            'truncated_at_page': asset.truncated_at_page,
            'extraction_version': asset.extraction_version,
            'extracted_text_sha256': asset.extracted_text_sha256,
            'chunk_count': asset.chunk_count,
            'chunking_version': asset.chunking_version,
            'chunk_index_sha256': asset.chunk_index_sha256,
            'unique_evidence_span_count': len(unique_spans),
            'chunks': chunk_rows,
            'searches': matches,
        }

        stem = f'{options["asset_kind"]}-fulltext-asset-{asset.id}'
        json_path = output_dir / f'{stem}.json'
        markdown_path = output_dir / f'{stem}.md'
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

        lines = [
            f'# QA 全文资产 {asset.id} 验收报告',
            '',
            f'- 项目 ID：{asset.project_id}',
            f'- 文献 ID：{getattr(asset, "qa_reference_id", None)}',
            f'- 原文件名：{asset.original_filename}',
            f'- 状态：{asset.status} / {asset.extraction_status}',
            f'- PDF 页数 / 实际检查页数：{asset.page_count} / {asset.extracted_page_count}',
            f'- 提取字符数：{asset.extracted_text_chars}',
            f'- 是否截断 / 截断页：{asset.extraction_truncated} / {asset.truncated_at_page}',
            f'- 提取版本 / SHA256：{asset.extraction_version} / {asset.extracted_text_sha256}',
            f'- 分块数 / 版本 / SHA256：{asset.chunk_count} / {asset.chunking_version} / {asset.chunk_index_sha256}',
            f'- 唯一证据片段数：{len(unique_spans)}',
            '',
            '## 分块预览',
            '',
            '| 块 ID | 页码 | 章节 | 估算 Token | 字符数 | 片段数 | 预览 |',
            '|---|---:|---|---:|---:|---:|---|',
        ]
        for chunk in chunk_rows:
            preview = (chunk['preview'] or '').replace('|', '\\|')
            lines.append(
                f"| {chunk['chunk_id']} | {chunk['page_start']}-{chunk['page_end']} | "
                f"{chunk['section']} | {chunk['estimated_tokens']} | {chunk['char_count']} | "
                f"{chunk['span_count']} | {preview} |"
            )
        if matches:
            lines.extend(['', '## 短语检索', ''])
            for item in matches:
                lines.append(f"### `{item['phrase']}`")
                lines.append('')
                if not item['matches']:
                    lines.append('- 未命中')
                for match in item['matches']:
                    lines.append(
                        f"- {match['chunk_id']}（第 {match['page_start']}-{match['page_end']} 页）："
                        f"{match['context']}"
                    )
                lines.append('')
        markdown_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        self.stdout.write(self.style.SUCCESS(str(markdown_path)))
        self.stdout.write(str(json_path))
