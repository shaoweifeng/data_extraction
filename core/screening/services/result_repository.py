"""Filesystem and DataFile persistence for AI screening results."""

import json
from pathlib import Path
from typing import Dict, List

from core.executors.base import safe_title
from core.models import DataFile
from core.artifacts.types import ArtifactType


def _result_metadata(entry: Dict, result: Dict) -> Dict:
    """Build the lightweight database index used by review list queries."""
    decision = result.get('decision', 'excluded')
    return {
        'artifact_type': ArtifactType.SCREENING_RESULT_JSON,
        'decision': decision,
        'consensus': result.get('consensus', decision),
        'source_xml': entry.get('source_xml', '') or result.get('source_xml', ''),
        'title': entry.get('title', '') or result.get('title', ''),
        'authors': entry.get('authors', '') or result.get('authors', ''),
        'year': entry.get('year', '') or result.get('year', ''),
        'journal': entry.get('journal', '') or result.get('journal', ''),
        'doi': entry.get('doi', '') or result.get('doi', ''),
        'url': entry.get('url', '') or result.get('url', ''),
        'ai_reason': result.get('exclusion_reason', ''),
    }


class ScreeningResultRepository:
    def __init__(self, handler):
        self._handler = handler

    def __getattr__(self, name):
        return getattr(self._handler, name)

    def _save_result(self, entry: Dict, result: Dict, results_dir: Path):
        safe_dir = safe_title(entry.get("title", "unknown"), 50)
        result_dir = results_dir / safe_dir
        result_dir.mkdir(exist_ok=True)
        result_file = result_dir / f"screening_result_{entry['source_xml'].replace('.xml', '.json')}"
        # 将多模型字段一并写入 JSON
        save_data = dict(result)
        save_data.setdefault('multi_model_results', [])
        save_data.setdefault('consensus', result.get('decision', 'excluded'))
        with open(result_file, 'w', encoding='utf-8') as f:
            json.dump(save_data, f, ensure_ascii=False, indent=2)

    def _save_batch_results_to_db(self, batch: List[Dict], results: List[Dict]):
        from django.db import close_old_connections
        from django.core.files.base import ContentFile
        close_old_connections()

        for entry, result in zip(batch, results):
            filename = f"screening_result_{entry['source_xml'].replace('.xml', '.json')}"
            if DataFile.objects.filter(project=self.project_obj, step=self.step_obj, filename=filename).exists():
                continue
            safe_dir = safe_title(entry.get("title", "unknown"), 50)
            result_file_path = self.workspace / "screening_ai" / "results" / safe_dir / filename
            if result_file_path.exists():
                with open(result_file_path, 'rb') as f:
                    content = f.read()
                DataFile.objects.create(
                    project=self.project_obj, stage=self.stage_obj, step=self.step_obj,
                    filename=filename, file=ContentFile(content, name=filename),
                    data_category='output', source='tool_generated',
                    description='AI筛选结果',
                    metadata=_result_metadata(entry, result),
                    created_by=self.task_obj.created_by,
                )

    def _save_all_results(self, results_dir: Path):
        from django.core.files.base import ContentFile
        for result_dir in results_dir.iterdir():
            if not result_dir.is_dir():
                continue
            for result_file in result_dir.glob("screening_result_*.json"):
                filename = result_file.name
                if DataFile.objects.filter(project=self.project_obj, step=self.step_obj, filename=filename).exists():
                    continue
                with open(result_file, 'rb') as f:
                    content = f.read()
                try:
                    result = json.loads(content.decode('utf-8'))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    result = {}
                DataFile.objects.create(
                    project=self.project_obj, stage=self.stage_obj, step=self.step_obj,
                    filename=filename, file=ContentFile(content, name=filename),
                    data_category='output', source='tool_generated',
                    description='AI筛选结果',
                    metadata=_result_metadata(result, result),
                    created_by=self.task_obj.created_by,
                )
