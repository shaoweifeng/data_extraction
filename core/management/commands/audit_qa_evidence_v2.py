"""Read-only preflight audit for the QA evidence V2 schema migration."""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, F

from core.models import QADomainResult, QAFulltextAsset, QAReference, QASignalItem


class Command(BaseCommand):
    help = 'Audit existing QA rows before applying the evidence V2 uniqueness migration.'

    def add_arguments(self, parser):
        parser.add_argument('--output', help='Optional JSON report path.')
        parser.add_argument('--sample-limit', type=int, default=50)
        parser.add_argument('--fail-on-conflicts', action='store_true')

    def handle(self, *args, **options):
        sample_limit = options['sample_limit']
        if sample_limit < 1 or sample_limit > 1000:
            raise CommandError('--sample-limit 必须在 1 到 1000 之间。')

        duplicate_groups = QASignalItem.objects.values(
            'qa_ref_id', 'signal_key',
        ).annotate(
            row_count=Count('id'),
        ).filter(row_count__gt=1).order_by('qa_ref_id', 'signal_key')

        duplicate_samples = []
        for row in duplicate_groups[:sample_limit]:
            confirmed_count = QASignalItem.objects.filter(
                qa_ref_id=row['qa_ref_id'],
                signal_key=row['signal_key'],
                is_confirmed=True,
            ).count()
            duplicate_samples.append({
                'qa_ref_id': row['qa_ref_id'],
                'signal_key': row['signal_key'],
                'row_count': row['row_count'],
                'confirmed_count': confirmed_count,
                'row_ids': list(QASignalItem.objects.filter(
                    qa_ref_id=row['qa_ref_id'], signal_key=row['signal_key'],
                ).order_by('id').values_list('id', flat=True)[:100]),
            })

        duplicate_domain_groups = QADomainResult.objects.values(
            'qa_ref_id', 'domain',
        ).annotate(row_count=Count('id')).filter(row_count__gt=1)
        mismatched_assets = QAFulltextAsset.objects.exclude(
            project_id=F('qa_reference__project_id')
        )
        report = {
            'safe_to_add_signal_unique_constraint': not duplicate_samples,
            'conflict_counts': {
                'duplicate_signal_groups': duplicate_groups.count(),
                'duplicate_domain_groups': duplicate_domain_groups.count(),
                'asset_project_mismatches': mismatched_assets.count(),
            },
            'duplicate_signal_samples': duplicate_samples,
            'duplicate_domain_samples': list(
                duplicate_domain_groups.order_by('qa_ref_id', 'domain')[:sample_limit]
            ),
            'asset_project_mismatch_samples': list(
                mismatched_assets.order_by('id').values(
                    'id', 'project_id', 'qa_reference_id',
                    'qa_reference__project_id',
                )[:sample_limit]
            ),
            'inventory': {
                'references': QAReference.objects.count(),
                'signal_items': QASignalItem.objects.count(),
                'confirmed_signal_items': QASignalItem.objects.filter(is_confirmed=True).count(),
                'domain_results': QADomainResult.objects.count(),
                'fulltext_assets': QAFulltextAsset.objects.count(),
                'reference_statuses': list(
                    QAReference.objects.values('ai_eval_status')
                    .annotate(count=Count('id')).order_by('ai_eval_status')
                ),
                'chunking_versions': list(
                    QAFulltextAsset.objects.values('chunking_version')
                    .annotate(count=Count('id')).order_by('chunking_version')
                ),
            },
        }

        rendered = json.dumps(report, ensure_ascii=False, indent=2, default=str)
        if options.get('output'):
            output = Path(options['output']).expanduser().resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(rendered + '\n', encoding='utf-8')
            self.stdout.write(str(output))
        else:
            self.stdout.write(rendered)

        conflicts = report['conflict_counts']
        if options['fail_on_conflicts'] and any(conflicts.values()):
            raise CommandError('发现质量评价数据冲突；请在执行 0036 迁移前处理。')
