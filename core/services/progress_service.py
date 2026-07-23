"""
进度与日志服务层

职责：
- 统一进度读取：优先读 progress_*.json，回退 Task.progress 字段
- 统一日志读取：优先读 task_*.log 文件，回退 Task.logs 字段
- 统一日志路径推导规则，避免散落在 monitoring / scheduler / views 各处

调用方只需关心接口，不关心进度/日志存在哪里。
"""

import json
from pathlib import Path
from typing import Dict, List, Optional

from django.conf import settings


# ============================================================================
# 进度读取
# ============================================================================

def get_task_progress(task_id: int) -> Dict:
    """
    获取任务进度。

    优先级：
    1. 读取 progress_*.json 文件（执行器实时写入）
    2. 回退到 Task.progress 字段

    Returns:
        {current, total, percentage, unit, status, last_update}
    """
    from core.models import Task

    task = Task.objects.get(id=task_id)
    return _read_progress_for_task(task)


def _read_progress_for_task(task) -> Dict:
    """从 Task 对象读取进度（内部复用）。"""
    log_file = task.log_file

    if log_file:
        progress_path = _derive_progress_path(log_file)
        if progress_path and progress_path.exists():
            try:
                with open(progress_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return {
                    "current": data.get("current", 0),
                    "total": data.get("total", 0),
                    "percentage": data.get("percentage", 0.0),
                    "unit": data.get("unit", ""),
                    "status": task.status,
                    "last_update": data.get("last_update"),
                }
            except Exception:
                pass

    # 回退：使用 Task.progress 字段（0.0 ~ 1.0）
    return {
        "current": int(task.progress * 100),
        "total": 100,
        "percentage": task.progress * 100,
        "unit": "%",
        "status": task.status,
        "last_update": None,
    }


def _derive_progress_path(log_file: str) -> Optional[Path]:
    """
    根据日志文件路径推导进度文件路径。

    规则：task_<suffix>.log → progress_<suffix>.json
    支持绝对路径和相对路径（相对于 MEDIA_ROOT）。
    """
    if not log_file:
        return None

    log_path = Path(log_file)
    if not log_path.is_absolute():
        log_path = Path(settings.MEDIA_ROOT) / log_file

    # task_xxx.log → progress_xxx.json（同目录）
    name = log_path.name
    if name.startswith("task_") and name.endswith(".log"):
        progress_name = "progress_" + name[len("task_"):-len(".log")] + ".json"
        return log_path.parent / progress_name

    return None


# ============================================================================
# 日志读取
# ============================================================================

def read_task_logs(task_id: int, last_n: int = 200) -> Dict:
    """
    读取任务日志（末尾 N 行）。

    优先级：
    1. task.log_file 指向的日志文件
    2. 回退 task.logs 字段内容

    Returns:
        {log_content, total_lines, returned_lines}
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
    """
    读取任务日志末尾 N 行，返回行列表。

    Returns:
        List[str]，每行不含换行符
    """
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
    """
    解析 Task 的日志文件绝对路径。

    task.log_file 可能是：
    - 绝对路径（新版本）
    - 相对路径（相对 MEDIA_ROOT，旧版本）
    - None

    Returns:
        Path 对象或 None
    """
    log_file = task.log_file
    if not log_file:
        return None

    path = Path(log_file)
    if path.is_absolute():
        return path

    return Path(settings.MEDIA_ROOT) / log_file
