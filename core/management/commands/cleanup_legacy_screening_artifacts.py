from django.core.management.base import BaseCommand, CommandError

from core.models import DataFile


LEGACY_ARTIFACT_TYPES = (
    'screening_parsed_references_xml',
    'screening_parsed_reference_xml',
    'screening_dedup_reference_xml',
    'screening_result_json',
)


class Command(BaseCommand):
    help = '删除数据库化初筛不再使用的单篇 XML/JSON DataFile 及其物理文件。'

    def add_arguments(self, parser):
        parser.add_argument('--project-id', type=int)
        parser.add_argument(
            '--execute', action='store_true',
            help='实际删除；默认只预览数量与体积。',
        )

    def handle(self, *args, **options):
        queryset = DataFile.objects.filter(
            metadata__artifact_type__in=LEGACY_ARTIFACT_TYPES,
        ).order_by('pk')
        project_id = options.get('project_id')
        if project_id is not None:
            if project_id <= 0:
                raise CommandError('project-id 必须是正整数。')
            queryset = queryset.filter(project_id=project_id)

        total = queryset.count()
        total_bytes = sum(queryset.values_list('file_size', flat=True).iterator())
        scope = f'项目 #{project_id}' if project_id else '全部项目'
        if not options['execute']:
            self.stdout.write(
                f'[预览] {scope}：将删除 {total} 条旧初筛文件记录，约 {total_bytes} 字节。'
            )
            self.stdout.write('确认备份无误后追加 --execute 执行。')
            return

        deleted = 0
        for data_file in queryset.iterator(chunk_size=500):
            if data_file.file:
                data_file.file.delete(save=False)
            data_file.delete()
            deleted += 1
        self.stdout.write(self.style.SUCCESS(
            f'{scope}：已删除 {deleted} 条旧初筛文件记录及对应物理文件。'
        ))
