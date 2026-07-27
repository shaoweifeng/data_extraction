"""
日志服务层
职责：
- 统一日志读取：优先读 task_*.log 文件，回退 Task.logs 字段
- 统一日志路径推导规则
"""
from pathlib import Path
from typing import List, Optional
from django.conf import settings


def read_task_logs(task_id: int, last_n: int = 200) -> dict:
    """
    读取任务日志（末尾 N 行）。
    优先级：
    1. task.log_file 指向的日志文件
    2. 回退 task.logs 字段内容
    """
    from core.models import Task
    task = Task.objects.get(id=task_id)
    log_file = _resolve_log_file(task)
    if log_file and log_file.exists():
        try:
            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            tail = lines[-last_n:] if len(lines) > last_n else lines
            return {
                'log_content': ''.join(tail),
                'total_lines': len(lines),
                'returned_lines': len(tail),
            }
        except Exception as e:
            return {'log_content': f'读取日志失败: {e}', 'total_lines': 0, 'returned_lines': 0}
    return {
        'log_content': task.logs or '任务正在初始化，日志即将生成...',
        'total_lines': 0,
        'returned_lines': 0,
    }


def tail_task_logs(task_id: int, last_n: int = 50) -> List[str]:
    """读取任务日志末尾 N 行，返回行列表。"""
    from core.models import Task
    task = Task.objects.get(id=task_id)
    log_file = _resolve_log_file(task)
    if not log_file or not log_file.exists():
        return []
    try:
        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
            lines = []
            for line in f:
                lines.append(line.rstrip('\n\r'))
                if len(lines) > last_n:
                    lines.pop(0)
        return lines
    except Exception as e:
        return [f"Error reading log: {str(e)}"]


def _resolve_log_file(task) -> Optional[Path]:
    """解析 Task 的日志文件绝对路径。"""
    log_file = task.log_file
    if not log_file:
        return None
    path = Path(log_file)
    if path.is_absolute():
        return path
    return Path(settings.MEDIA_ROOT) / log_file
