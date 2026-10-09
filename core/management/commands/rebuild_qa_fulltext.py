import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from core.models import QAFulltextAsset
from core.quality.services.fulltext import process_fulltext_asset
from core.quality.services.fulltext import EXTRACTION_VERSION
from core.quality.services.fulltext_chunks import CHUNKING_VERSION


class Command(BaseCommand):
    help = 'Re-extract and deterministically chunk QA full-text assets in a bounded scope.'

    def add_arguments(self, parser):
        scope = parser.add_mutually_exclusive_group(required=True)
        scope.add_argument('--asset-id', type=int)
        scope.add_argument('--project-id', type=int)
        scope.add_argument('--retry-report')
        parser.add_argument('--limit', type=int, default=100)
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--resume', action='store_true')
        parser.add_argument('--report')

    def handle(self, *args, **options):
        limit = options['limit']
        if limit <= 0 or limit > 1000:
            raise CommandError('--limit 必须在 1 到 1000 之间。')

        queryset = QAFulltextAsset.objects.exclude(raw_file='').order_by('id')
        if options['asset_id'] is not None:
            queryset = queryset.filter(pk=options['asset_id'])
        elif options['project_id'] is not None:
            queryset = queryset.filter(project_id=options['project_id'])
        else:
            retry_path = Path(options['retry_report']).resolve()
            try:
                previous = json.loads(retry_path.read_text(encoding='utf-8'))
                retry_ids = [int(item['asset_id']) for item in previous.get('failed', [])]
            except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
                raise CommandError('无法读取 --retry-report 中的失败资产。') from exc
            queryset = queryset.filter(pk__in=retry_ids)
        if options['resume']:
            queryset = queryset.exclude(
                status='ready', extraction_status='completed',
                extraction_version=EXTRACTION_VERSION, chunking_version=CHUNKING_VERSION,
            )
        asset_ids = list(queryset.values_list('id', flat=True)[:limit])
        if not asset_ids:
            self.stdout.write('指定范围内没有需要重建的质量评价全文资产。')
            return

        if options['dry_run']:
            self.stdout.write(f'将重建 {len(asset_ids)} 个资产: {asset_ids}')
            return

        succeeded = []
        failed = []
        for asset_id in asset_ids:
            try:
                process_fulltext_asset(asset_id, force=True)
                asset = QAFulltextAsset.objects.only(
                    'status', 'error_code', 'chunk_count',
                ).get(pk=asset_id)
                if asset.status == 'ready':
                    succeeded.append(asset_id)
                    self.stdout.write(
                        self.style.SUCCESS(f'asset={asset_id} ready chunks={asset.chunk_count}')
                    )
                else:
                    failed.append({'asset_id': asset_id, 'error': asset.error_code or asset.status})
            except Exception as exc:
                failed.append({'asset_id': asset_id, 'error': type(exc).__name__})
                self.stderr.write(f'asset={asset_id} failed={type(exc).__name__}')

        self.stdout.write(f'完成: success={len(succeeded)} failed={len(failed)}')
        if failed:
            self.stdout.write(f'失败清单: {failed}')
        if options['report']:
            report_path = Path(options['report']).resolve()
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps({
                'schema_version': 'qa-fulltext-rebuild-v1',
                'extraction_version': EXTRACTION_VERSION,
                'chunking_version': CHUNKING_VERSION,
                'succeeded_asset_ids': succeeded,
                'failed': failed,
            }, ensure_ascii=False, indent=2), encoding='utf-8')
            self.stdout.write(f'报告已写入 {report_path}')
