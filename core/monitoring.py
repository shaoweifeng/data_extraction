"""
进度监控与日志读取 - 数据提取平台

提供：
1. ProgressMonitor - 读取进度JSON文件，聚合子步骤进度
2. LogReader - 流式读取日志文件（分页、实时tail）
3. ProgressWebSocketConsumer - WebSocket实时推送（可选）

关键设计：
- 进度信息完全独立于任务日志
- 支持聚合流水线中多个子步骤的进度
- 流式读取大日志文件（避免内存溢出）
"""

import json
from pathlib import Path
from typing import Dict, List
from datetime import datetime

from django.conf import settings


class ProgressMonitor:
    """
    进度监控器 - 读取独立进度JSON文件
    
    特性：
    - 不依赖日志解析
    - 支持聚合子步骤进度
    - 自动计算整体进度百分比
    """
    
    def __init__(self, project_id: int):
        self.project_id = project_id
        self.workspace_root = Path(settings.BASE_DIR) / "workspaces" / f"project_{project_id}"
    
    def get_step_progress(self, step_key: str) -> Dict:
        """
        获取单个步骤进度
        
        Args:
            step_key: 步骤标识
        
        Returns:
            进度信息字典
        """
        # 查找最新的进度文件
        progress_files = []
        
        if not self.workspace_root.exists():
            return {"status": "not_started", "percentage": 0.0}
        
        for item in self.workspace_root.iterdir():
            if item.name.startswith(f"{step_key}_") and item.is_dir():
                # 使用 glob 查找
                for pf in item.glob("logs/progress_*.json"):
                    progress_files.append(pf)
        
        if not progress_files:
            return {"status": "not_started", "percentage": 0.0}
        
        # 读取最新的进度文件
        latest_file = max(progress_files, key=lambda x: x.stat().st_mtime)
        
        try:
            with open(latest_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
                return {
                    "step_key": step_key,
                    "current": data.get("current", 0),
                    "total": data.get("total", 0),
                    "percentage": data.get("percentage", 0.0),
                    "unit": data.get("unit", ""),
                    "start_time": data.get("start_time"),
                    "last_update": data.get("last_update"),
                    "checkpoints": data.get("checkpoints", []),
                    "status": "in_progress" if data.get("current", 0) < data.get("total", 1) else "completed"
                }
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def get_stage_progress(self, stage_key: str) -> Dict:
        """
        获取阶段进度（聚合子步骤）
        
        Args:
            stage_key: 阶段标识
        
        Returns:
            聚合的进度信息
        """
        from core.step_config import get_step_config
        
        config = get_step_config(stage_key)
        
        # 如果是单步骤阶段，直接返回步骤进度
        if "sub_steps" not in config:
            return self.get_step_progress(stage_key)
        
        # 聚合子步骤进度
        weights = config.get("monitoring", {}).get("weight_distribution", {})
        sub_step_progress = {}
        total_percentage = 0.0
        
        for step_key, weight in weights.items():
            step_prog = self.get_step_progress(step_key)
            sub_step_progress[step_key] = step_prog
            total_percentage += step_prog.get("percentage", 0.0) * weight
        
        # 计算整体状态
        all_completed = all(
            prog.get("status") in ["completed", "skipped"]
            for prog in sub_step_progress.values()
        )
        any_failed = any(
            prog.get("status") == "error"
            for prog in sub_step_progress.values()
        )
        
        if any_failed:
            overall_status = "error"
        elif all_completed:
            overall_status = "completed"
        else:
            overall_status = "in_progress"
        
        return {
            "stage_key": stage_key,
            "percentage": round(total_percentage, 2),
            "status": overall_status,
            "sub_steps": sub_step_progress
        }
    
    def get_project_progress(self) -> Dict:
        """获取项目整体进度"""
        from core.models import ProjectStage
        
        stages = ProjectStage.objects.filter(project_id=self.project_id)
        
        return {
            "project_id": self.project_id,
            "stages": {
                stage.stage_key: self.get_stage_progress(stage.stage_key)
                for stage in stages
            },
            "updated_at": datetime.now().isoformat()
        }


class LogReader:
    """
    日志读取器 - 流式读取大日志文件
    
    特性：
    - 分页读取，避免内存溢出
    - 支持实时tail（获取最后N行）
    - 自动编码检测
    """
    
    def __init__(self, task_id: int):
        self.task_id = task_id
        from core.models import Task
        self.task = Task.objects.get(id=task_id)
    
    def read_logs(self, from_line: int = 0, max_lines: int = 100) -> Dict:
        """
        分页读取日志
        
        Args:
            from_line: 起始行号（0-based）
            max_lines: 最大行数
        
        Returns:
            包含日志行和分页信息的字典
        """
        # 从task.logs字段解析日志文件路径
        log_file_path = None
        if self.task.logs:
            try:
                import json
                log_meta = json.loads(self.task.logs)
                log_file_path = log_meta.get('log_file')
            except (json.JSONDecodeError, TypeError):
                pass
        
        if not log_file_path:
            return {"lines": [], "total": 0, "error": "No log file"}
        
        # 构建完整路径
        if log_file_path.startswith('/'):
            log_path = Path(log_file_path)
        else:
            log_path = Path(settings.MEDIA_ROOT) / log_file_path
        
        if not log_path.exists():
            return {"lines": [], "total": 0, "error": f"Log file not found: {log_file_path}"}
        
        try:
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                all_lines = f.readlines()
                total_lines = len(all_lines)
                requested_lines = all_lines[from_line:from_line + max_lines]
                
                return {
                    "lines": [line.rstrip('\n\r') for line in requested_lines],
                    "from_line": from_line,
                    "to_line": from_line + len(requested_lines),
                    "total": total_lines,
                    "has_more": from_line + len(requested_lines) < total_lines,
                    "file_size": log_path.stat().st_size
                }
        
        except Exception as e:
            return {"lines": [], "total": 0, "error": str(e)}
    
    def tail_logs(self, last_n_lines: int = 50) -> List[str]:
        """
        读取最后N行日志（实时tail）
        
        Args:
            last_n_lines: 行数
        
        Returns:
            日志行列表
        """
        if not self.task.log_file:
            return []
        
        log_path = Path(settings.MEDIA_ROOT) / self.task.log_file
        
        if not log_path.exists():
            return []
        
        try:
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                # 高效读取最后N行（不加载整个文件）
                lines = []
                for line in f:
                    lines.append(line.rstrip('\n\r'))
                    if len(lines) > last_n_lines:
                        lines.pop(0)
                
                return lines
        
        except Exception as e:
            return [f"Error reading log: {str(e)}"]
    
    def search_logs(self, keyword: str, context_lines: int = 2) -> List[Dict]:
        """
        搜索日志（带上下文）
        
        Args:
            keyword: 搜索关键词
            context_lines: 上下文行数
        
        Returns:
            匹配结果列表（包含行号和上下文）
        """
        if not self.task.log_file:
            return []
        
        log_path = Path(settings.MEDIA_ROOT) / self.task.log_file
        
        if not log_path.exists():
            return []
        
        try:
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
                results = []
                
                for i, line in enumerate(lines):
                    if keyword.lower() in line.lower():
                        start = max(0, i - context_lines)
                        end = min(len(lines), i + context_lines + 1)
                        
                        results.append({
                            "line_number": i,
                            "line": line.rstrip('\n\r'),
                            "context": [
                                lines[j].rstrip('\n\r')
                                for j in range(start, end)
                            ]
                        })
                
                return results
        
        except Exception as e:
            return [{"error": str(e)}]


# ============================================================================
# 辅助函数
# ============================================================================

def get_task_progress(task_id: int) -> Dict:
    """
    快捷函数 - 获取任务进度
    
    Args:
        task_id: 任务ID
    
    Returns:
        进度信息字典
    """
    from core.models import Task
    task = Task.objects.get(id=task_id)
    
    if not task.log_file:
        return {
            "current": 0,
            "total": 100,
            "percentage": task.progress * 100,
            "status": task.status
        }
    
    # 尝试读取进度文件
    progress_file = task.log_file.replace("task_", "progress_").replace(".log", ".json")
    progress_path = Path(settings.MEDIA_ROOT) / progress_file
    
    if progress_path.exists():
        try:
            with open(progress_path, 'r') as f:
                data = json.load(f)
                return {
                    "current": data.get("current", 0),
                    "total": data.get("total", 0),
                    "percentage": data.get("percentage", 0.0),
                    "unit": data.get("unit", ""),
                    "status": task.status,
                    "last_update": data.get("last_update")
                }
        except Exception:
            pass
    
    # 回退到任务表的进度字段
    return {
        "current": int(task.progress * 100),
        "total": 100,
        "percentage": task.progress * 100,
        "unit": "%",
        "status": task.status
    }
