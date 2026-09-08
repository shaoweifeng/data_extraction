"""任务文件日志和进度上报。"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from django.conf import settings

from .checkpoint_store import CheckpointStore


logger = logging.getLogger(__name__)


class TaskReporter:
    """写任务专属日志、进度文件，并节流同步到 Task。"""

    def __init__(self, task_id: int, workspace: str):
        self.task_id = task_id
        self.workspace = Path(workspace)
        self.log_dir = self.workspace / 'logs'
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.log_dir / f'task_{task_id}.log'
        self.progress_file = self.log_dir / f'progress_{task_id}.json'
        self.checkpoint_store = CheckpointStore(self.log_dir / 'checkpoint.json')
        self.checkpoint_file = self.checkpoint_store.path
        self.file_handler = None
        self.line_count = 0
        self.file_size = 0
        self.progress_data = {
            'current': 0,
            'total': 0,
            'percentage': 0.0,
            'unit': '',
            'start_time': datetime.now().isoformat(),
            'last_update': None,
            'checkpoints': [],
        }
        self.log_buffer = []
        self.max_buffer_size = 100
        self.last_db_sync = datetime.now()
        self.db_sync_interval = 2
        self._last_progress_sync = 0
        self._progress_sync_interval = 16
        self._init_logger()
        self._save_progress()

    def _init_logger(self):
        self.file_handler = logging.FileHandler(self.log_file, encoding='utf-8', mode='a')
        self.file_handler.setLevel(logging.DEBUG)
        self.file_handler.setFormatter(logging.Formatter(
            '%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
        ))
        self._task_file_logger = logging.getLogger(f'core.executors.task.{self.task_id}')
        self._task_file_logger.setLevel(logging.DEBUG)
        self._task_file_logger.propagate = False
        self._task_file_logger.addHandler(self.file_handler)
        self.info(f'[初始化] 任务 {self.task_id} 日志系统启动')

    def _write(self, level: str, message: str, buffer_level: str) -> None:
        getattr(logger, level)(message)
        getattr(self._task_file_logger, level)(message)
        self._add_to_buffer(f'[{buffer_level}] {message}')
        self._update_stats()

    def info(self, msg: str):
        self._write('info', msg, 'INFO')

    def error(self, msg: str):
        self._write('error', msg, 'ERROR')

    def warning(self, msg: str):
        self._write('warning', msg, 'WARN')

    def debug(self, msg: str):
        self._write('debug', msg, 'DEBUG')

    def _update_stats(self):
        try:
            if self.log_file.exists():
                self.file_size = self.log_file.stat().st_size
        except OSError as exc:
            logger.error(f'更新日志统计失败: {exc}')

    def update_progress(self, current: int, total: int, unit: str = ''):
        self.progress_data.update({
            'current': current,
            'total': total,
            'percentage': round(current / total * 100, 2) if total > 0 else 0.0,
            'unit': unit,
            'last_update': datetime.now().isoformat(),
        })
        self._save_progress()
        self.info(f"[进度] {current}/{total} {unit} ({self.progress_data['percentage']}%)")
        should_sync = (
            current - self._last_progress_sync >= self._progress_sync_interval
            or (datetime.now() - self.last_db_sync).total_seconds() >= 5
        )
        if should_sync:
            self._sync_progress_to_db(current, total)
            self._last_progress_sync = current

    def add_checkpoint(self, name: str, data: Dict = None):
        checkpoint = {
            'name': name,
            'time': datetime.now().isoformat(),
            'progress': {
                'current': self.progress_data['current'],
                'total': self.progress_data['total'],
            },
            'data': data or {},
        }
        self.progress_data['checkpoints'].append(checkpoint)
        self._save_progress()
        self._save_checkpoint(checkpoint)
        self.info(f'[断点] 保存检查点: {name}')

    def _save_progress(self):
        try:
            with self.progress_file.open('w', encoding='utf-8') as file_obj:
                json.dump(self.progress_data, file_obj, indent=2, ensure_ascii=False)
        except OSError as exc:
            logger.error(f'保存进度失败: {exc}')

    def _save_checkpoint(self, checkpoint: Dict):
        try:
            self.checkpoint_store.save(checkpoint)
        except OSError as exc:
            logger.error(f'保存断点失败: {exc}')

    def load_checkpoint(self) -> Optional[Dict]:
        try:
            return self.checkpoint_store.load()
        except (OSError, json.JSONDecodeError) as exc:
            self.warning(f'加载检查点失败: {exc}')
            return None

    def clear_checkpoint(self):
        try:
            existed = self.checkpoint_file.exists()
            self.checkpoint_store.clear()
            if existed:
                self.info('[断点] 清除检查点')
        except OSError as exc:
            self.error(f'清除检查点失败: {exc}')

    def count_lines(self) -> int:
        try:
            if self.log_file.exists():
                with self.log_file.open('r', encoding='utf-8', errors='ignore') as file_obj:
                    return sum(1 for _ in file_obj)
        except OSError as exc:
            logger.error(f'统计日志行数失败: {exc}')
        return 0

    def get_metadata(self) -> Dict:
        self._update_stats()
        self.line_count = self.count_lines()
        try:
            log_path = str(self.log_file.relative_to(settings.MEDIA_ROOT))
            progress_path = str(self.progress_file.relative_to(settings.MEDIA_ROOT))
        except ValueError:
            log_path = str(self.log_file)
            progress_path = str(self.progress_file)
        return {
            'log_file': log_path,
            'progress_file': progress_path,
            'line_count': self.line_count,
            'file_size': self.file_size,
            'last_update': self.progress_data.get('last_update'),
        }

    def _add_to_buffer(self, line: str):
        self.log_buffer.append(f"[{datetime.now().strftime('%H:%M:%S')}] {line}")
        if len(self.log_buffer) > self.max_buffer_size:
            self.log_buffer.pop(0)
        now = datetime.now()
        if (now - self.last_db_sync).total_seconds() >= self.db_sync_interval:
            self._sync_logs_to_db()
            self.last_db_sync = now

    def _sync_progress_to_db(self, current: int, total: int):
        try:
            from django.db import close_old_connections
            from core.models import Task

            close_old_connections()
            Task.objects.filter(id=self.task_id).update(
                progress=round(current / total, 4) if total > 0 else 0,
            )
        except Exception as exc:
            logger.warning(f'同步进度到DB失败: {exc}')

    def _sync_logs_to_db(self):
        try:
            from django.db import close_old_connections
            from core.models import Task

            close_old_connections()
            Task.objects.filter(id=self.task_id).update(logs='\n'.join(self.log_buffer))
        except Exception as exc:
            logger.warning(f'同步日志到DB失败: {exc}')

    def close(self):
        self.info(f'[结束] 任务 {self.task_id} 日志系统关闭')
        self._sync_logs_to_db()
        if self.file_handler:
            self._task_file_logger.removeHandler(self.file_handler)
            self.file_handler.close()
            self.file_handler = None
