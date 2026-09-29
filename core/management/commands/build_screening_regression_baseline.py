"""Generate the checked-in screening/QA regression baseline."""

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from core.screening.regression_baseline import build_regression_baseline


class Command(BaseCommand):
    help = '根据 meta_project/Screen_input 和 QA_input 生成可重复的回归基线'

    def add_arguments(self, parser):
        parser.add_argument(
            '--sample-root',
            type=Path,
            default=Path(settings.BASE_DIR) / 'meta_project',
        )
        parser.add_argument(
            '--output',
            type=Path,
            default=(
                Path(settings.BASE_DIR)
                / 'core/tests/fixtures/regression/meta_project_baseline.json'
            ),
        )

    def handle(self, *args, **options):
        baseline = build_regression_baseline(options['sample_root'])
        output = options['output']
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(baseline, ensure_ascii=False, indent=2, sort_keys=True) + '\n',
            encoding='utf-8',
        )
        self.stdout.write(self.style.SUCCESS(f'回归基线已写入 {output}'))
