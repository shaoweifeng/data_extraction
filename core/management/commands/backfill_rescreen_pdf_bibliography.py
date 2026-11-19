"""Preview or apply conservative local PDF bibliography enrichment."""
from django.core.management.base import BaseCommand, CommandError
from core.fulltext.bibliography import bibliography_from_asset
from core.fulltext.models import FulltextAsset
from core.rescreening.services.pdf_bibliography import enrich_pdf_references


class Command(BaseCommand):
    help = '补全 PDF 直接导入的复筛空白题录字段；默认仅预览，--apply 才写入并生成输入版本。'

    def add_arguments(self, parser):
        parser.add_argument('--project-id', type=int, required=True)
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        assets = FulltextAsset.objects.filter(project_id=options['project_id'], status='ready',
            rescreen_bindings__reference__import_batch__source_type='pdf',
            rescreen_bindings__reference__removed_revision__isnull=True).distinct().order_by('pk')
        count = 0
        for asset in assets.iterator(chunk_size=100):
            try:
                changes = enrich_pdf_references(asset, bibliography_from_asset(asset), apply=options['apply'])
            except Exception as exc:
                raise CommandError(f'asset={asset.pk}: {exc}') from exc
            for row in changes:
                count += 1
                self.stdout.write(f"reference={row['reference_id']} fields={','.join(row['fields'])}")
        self.stdout.write(f"{'已补全' if options['apply'] else '预览可补全'} {count} 篇；未识别字段保持空白。")
