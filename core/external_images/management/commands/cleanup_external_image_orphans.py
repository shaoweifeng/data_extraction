import os
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.external_images.models import ExternalImageUpload


class Command(BaseCommand):
    help = '查找或清理没有数据库记录的过期外部上传图片'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='实际删除；默认只预览')
        parser.add_argument('--older-than-hours', type=int, default=24, help='只处理早于该小时数的文件')

    def handle(self, *args, **options):
        root = Path(settings.EXTERNAL_IMAGE_UPLOAD_ROOT)
        if not root.exists():
            self.stdout.write('外部图片目录不存在，无需清理。')
            return

        cutoff = timezone.now() - timedelta(hours=max(1, options['older_than_hours']))
        referenced = set(ExternalImageUpload.objects.values_list('file', flat=True))
        orphans = []
        for directory, _, filenames in os.walk(root):
            for filename in filenames:
                path = Path(directory) / filename
                relative_name = path.relative_to(root).as_posix()
                modified_at = datetime.fromtimestamp(
                    path.stat().st_mtime,
                    tz=timezone.get_current_timezone(),
                )
                if relative_name not in referenced and modified_at < cutoff:
                    orphans.append(path)

        if options['apply']:
            for path in orphans:
                path.unlink(missing_ok=True)
            action = '已删除'
        else:
            action = '发现'
        self.stdout.write(self.style.SUCCESS(f'{action} {len(orphans)} 个孤立外部图片。'))
