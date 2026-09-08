"""任务工作区和停止信号管理。"""

import json
import shutil
from datetime import datetime
from pathlib import Path

from django.conf import settings


class WorkspaceManager:
    def __init__(self, project_id: int, step_key: str, task_id: int):
        self.project_id = project_id
        self.step_key = step_key
        self.task_id = task_id

    def prepare(self) -> Path:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        workspace = (
            Path(settings.BASE_DIR)
            / 'workspaces'
            / f'project_{self.project_id}'
            / f'{self.step_key}_task_{self.task_id}_{timestamp}'
        )
        workspace.mkdir(parents=True, exist_ok=True)
        return workspace

    @property
    def stop_file(self) -> Path:
        return (
            Path(settings.BASE_DIR)
            / 'workspaces'
            / f'project_{self.project_id}'
            / f'{self.step_key}.STOP'
        )

    def has_stop_signal(self) -> bool:
        return self.stop_file.exists()

    def create_stop_signal(self, reason: str = '用户请求') -> Path:
        self.stop_file.parent.mkdir(parents=True, exist_ok=True)
        with self.stop_file.open('w', encoding='utf-8') as file_obj:
            json.dump(
                {
                    'timestamp': datetime.now().isoformat(),
                    'reason': reason,
                    'task_id': self.task_id,
                    'step_key': self.step_key,
                },
                file_obj,
                indent=2,
                ensure_ascii=False,
            )
        return self.stop_file

    def clear_stop_signal(self) -> None:
        if self.stop_file.exists():
            self.stop_file.unlink()

    @staticmethod
    def copy_input_files(input_files, target_dir: Path) -> None:
        target_dir.mkdir(parents=True, exist_ok=True)
        for data_file in input_files:
            shutil.copy(data_file.file.path, target_dir / data_file.filename)
