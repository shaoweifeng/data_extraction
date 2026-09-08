"""任务 checkpoint 的文件存储。"""

import json
from pathlib import Path
from typing import Dict, Optional

class CheckpointStore:
    def __init__(self, path):
        self.path = Path(path)

    def save(self, checkpoint: Dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open('w', encoding='utf-8') as file_obj:
            json.dump(checkpoint, file_obj, indent=2, ensure_ascii=False)

    def load(self) -> Optional[Dict]:
        if not self.path.exists():
            return None
        with self.path.open('r', encoding='utf-8') as file_obj:
            return json.load(file_obj)

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()
