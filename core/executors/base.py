"""
任务执行器基础框架 - 数据提取平台

核心设计：
1. 日志文件化 - TaskLogger 只写文件，DB 只存路径和元信息
2. 进度独立 - 进度数据存在独立 JSON 文件，不依赖日志解析
3. 断点续传 - 每个步骤定期保存 checkpoint
4. 停止信号 - 通过 STOP 文件检测用户中断
"""

import os
import json
import time
import logging
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List

from django.utils import timezone
from django.conf import settings
from django.core.files import File
from django.db import transaction

logger = logging.getLogger(__name__)


# ============================================================================
# 文件日志器 - DB 只存元信息
# ============================================================================

class TaskLogger:
    """
    任务专用日志器 - 文件落盘，DB 只存元信息
    
    特性：
    - 日志完全写入文件，不写 DB
    - 进度信息独立 JSON 文件
    - 自动统计行数和文件大小
    - 支持定期 checkpoint
    - 【新增】进度和日志实时同步到DB，供前端轮询
    """
    
    def __init__(self, task_id: int, workspace: str):
        self.task_id = task_id
        self.workspace = Path(workspace)
        
        # 创建日志目录
        self.log_dir = self.workspace / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # 日志文件路径
        self.log_file = self.log_dir / f"task_{task_id}.log"
        self.progress_file = self.log_dir / f"progress_{task_id}.json"
        # checkpoint路径放在 task 的 logs 目录下，logs 目录由上面 mkdir 已创建
        self.checkpoint_file = self.log_dir / "checkpoint.json"
        
        # 文件句柄和统计信息
        self.file_handler = None
        self.line_count = 0
        self.file_size = 0
        
        # 进度数据（内存中维护）
        self.progress_data = {
            "current": 0,
            "total": 0,
            "percentage": 0.0,
            "unit": "",
            "start_time": datetime.now().isoformat(),
            "last_update": None,
            "checkpoints": []
        }
        
        # 【新增】日志缓冲区和同步控制
        self.log_buffer = []
        self.max_buffer_size = 100      # 最多保留100行
        self.last_db_sync = datetime.now()
        self.db_sync_interval = 2      # 每2秒同步一次DB
        
        # 【新增】进度同步控制（以16篇为最小单位对齐批次）
        self._last_progress_sync = 0
        self._progress_sync_interval = 16  # 每16篇文献同步一次（与 batch_size 对齐）
        
        # 初始化
        self._init_logger()
        self._save_progress()
    
    def _init_logger(self):
        """初始化文件日志器"""
        # 创建文件handler
        self.file_handler = logging.FileHandler(
            self.log_file,
            encoding='utf-8',
            mode='a'
        )
        self.file_handler.setLevel(logging.DEBUG)
        
        # 设置格式
        formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        self.file_handler.setFormatter(formatter)
        
        # 添加到logger
        logging.root.addHandler(self.file_handler)
        
        self.info(f"[初始化] 任务 {self.task_id} 日志系统启动")
    
    def info(self, msg: str):
        """写入 INFO 日志"""
        logger.info(msg)
        self._add_to_buffer(f"[INFO] {msg}")
        self._update_stats()
    
    def error(self, msg: str):
        """写入 ERROR 日志"""
        logger.error(msg)
        self._add_to_buffer(f"[ERROR] {msg}")
        self._update_stats()
    
    def warning(self, msg: str):
        """写入 WARNING 日志"""
        logger.warning(msg)
        self._add_to_buffer(f"[WARN] {msg}")
        self._update_stats()
    
    def debug(self, msg: str):
        """写入 DEBUG 日志"""
        logger.debug(msg)
        self._add_to_buffer(f"[DEBUG] {msg}")
        self._update_stats()
    
    def _update_stats(self):
        """更新日志统计信息"""
        try:
            if self.log_file.exists():
                stat = self.log_file.stat()
                self.file_size = stat.st_size
        except Exception as e:
            logger.error(f"更新日志统计失败: {e}")
    
    def update_progress(self, current: int, total: int, unit: str = ""):
        """更新进度信息"""
        self.progress_data["current"] = current
        self.progress_data["total"] = total
        self.progress_data["percentage"] = round(current / total * 100, 2) if total > 0 else 0.0
        self.progress_data["unit"] = unit
        self.progress_data["last_update"] = datetime.now().isoformat()
        
        # 写入文件
        self._save_progress()
        
        # 同时写入日志（用于追溯）
        self.info(f"[进度] {current}/{total} {unit} ({self.progress_data['percentage']}%)")
        
        # 【新增】批量同步到DB（每N篇或每5秒）
        should_sync = (
            current - self._last_progress_sync >= self._progress_sync_interval or
            (datetime.now() - self.last_db_sync).total_seconds() >= 5
        )
        if should_sync:
            self._sync_progress_to_db(current, total)
            self._last_progress_sync = current
    
    def add_checkpoint(self, name: str, data: Dict = None):
        """添加检查点（用于断点续传）"""
        checkpoint = {
            "name": name,
            "time": datetime.now().isoformat(),
            "progress": {
                "current": self.progress_data["current"],
                "total": self.progress_data["total"]
            },
            "data": data or {}
        }
        
        self.progress_data["checkpoints"].append(checkpoint)
        self._save_progress()
        self._save_checkpoint(checkpoint)
        
        self.info(f"[断点] 保存检查点: {name}")
    
    def _save_progress(self):
        """保存进度到 JSON 文件"""
        try:
            with open(self.progress_file, 'w', encoding='utf-8') as f:
                json.dump(self.progress_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"保存进度失败: {e}")
    
    def _save_checkpoint(self, checkpoint: Dict):
        """保存单个检查点到文件（覆盖式保存，只保留最新）"""
        try:
            with open(self.checkpoint_file, 'w', encoding='utf-8') as f:
                json.dump(checkpoint, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"保存检查点失败: {e}")
    
    def load_checkpoint(self) -> Optional[Dict]:
        """加载最近的检查点"""
        if self.checkpoint_file.exists():
            try:
                with open(self.checkpoint_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                self.warning(f"加载检查点失败: {e}")
        return None
    
    def clear_checkpoint(self):
        """清除检查点文件"""
        if self.checkpoint_file.exists():
            try:
                self.checkpoint_file.unlink()
                self.info("[断点] 清除检查点")
            except Exception as e:
                self.error(f"清除检查点失败: {e}")
    
    def count_lines(self) -> int:
        """统计日志行数（按需调用）"""
        try:
            if self.log_file.exists():
                with open(self.log_file, 'r', encoding='utf-8', errors='ignore') as f:
                    return sum(1 for _ in f)
        except Exception as e:
            logger.error(f"统计日志行数失败: {e}")
        return 0
    
    def get_metadata(self) -> Dict:
        """获取日志元信息（用于 DB 存储）"""
        self._update_stats()
        self.line_count = self.count_lines()
        
        try:
            log_rel = str(self.log_file.relative_to(settings.MEDIA_ROOT))
            progress_rel = str(self.progress_file.relative_to(settings.MEDIA_ROOT))
        except ValueError:
            log_rel = str(self.log_file)
            progress_rel = str(self.progress_file)
        
        return {
            "log_file": log_rel,
            "progress_file": progress_rel,
            "line_count": self.line_count,
            "file_size": self.file_size,
            "last_update": self.progress_data.get("last_update")
        }
    
    def _add_to_buffer(self, line: str):
        """添加日志到缓冲区，并定期同步到DB"""
        timestamp = datetime.now().strftime('%H:%M:%S')
        formatted_line = f"[{timestamp}] {line}"
        self.log_buffer.append(formatted_line)
        
        # 控制缓冲区大小
        if len(self.log_buffer) > self.max_buffer_size:
            self.log_buffer.pop(0)
        
        # 定期同步到DB
        now = datetime.now()
        if (now - self.last_db_sync).total_seconds() >= self.db_sync_interval:
            self._sync_logs_to_db()
            self.last_db_sync = now
    
    def _sync_progress_to_db(self, current: int, total: int):
        """将进度同步到数据库"""
        try:
            from django.db import close_old_connections
            close_old_connections()
            from core.models import Task
            Task.objects.filter(id=self.task_id).update(
                progress=round(current / total, 4) if total > 0 else 0
            )
        except Exception as e:
            logger.warning(f"同步进度到DB失败: {e}")
    
    def _sync_logs_to_db(self):
        """将缓冲区日志同步到Task.logs字段"""
        try:
            from django.db import close_old_connections
            close_old_connections()
            from core.models import Task
            log_content = '\n'.join(self.log_buffer)
            Task.objects.filter(id=self.task_id).update(
                logs=log_content
            )
        except Exception as e:
            logger.warning(f"同步日志到DB失败: {e}")
    
    def close(self):
        """关闭日志器"""
        self.info(f"[结束] 任务 {self.task_id} 日志系统关闭")
        
        # 【新增】最终同步日志到DB
        self._sync_logs_to_db()
        
        if self.file_handler:
            logging.root.removeHandler(self.file_handler)
            self.file_handler.close()
            self.file_handler = None


# ============================================================================
# 执行器抽象基类
# ============================================================================

class BaseExecutor(ABC):
    """
    任务执行器基类
    
    职责：
    1. 管理工作区生命周期
    2. 初始化任务状态
    3. 提供停止信号检测
    4. 提供断点续传接口
    5. 统一的结果收集和文件保存
    """
    
    def __init__(self, task_id: int, step_key: str, project_id: int):
        self.task_id = task_id
        self.step_key = step_key
        self.project_id = project_id
        
        # 加载配置
        from core.step_config import get_step_config
        self.config = get_step_config(step_key)
        
        # 准备工作区（子类可能需要自定义）
        self.workspace = self._prepare_workspace()
        
        # 初始化日志器
        self.logger = TaskLogger(task_id, str(self.workspace))
        
        # 任务对象（延迟加载）
        self.task_obj = None
        self.step_obj = None
        self.project_obj = None
        self.stage_obj = None
    
    def _prepare_workspace(self) -> Path:
        """准备工作区"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        workspace = Path(settings.BASE_DIR) / "workspaces" / f"project_{self.project_id}" / f"{self.step_key}_{timestamp}"
        workspace.mkdir(parents=True, exist_ok=True)
        return workspace
    
    def initialize(self):
        """初始化任务"""
        from core.models import Task, Project, ProjectStage, StageStep
        from core.step_config import get_stage_definition
        
        self.project_obj = Project.objects.get(id=self.project_id)
        self.task_obj = Task.objects.get(id=self.task_id)
        
        # 获取阶段
        stage_key = self.config.get("stage_key")
        self.stage_obj = ProjectStage.objects.get(
            project=self.project_obj,
            stage_key=stage_key
        )
        
        # 获取或创建步骤对象
        stage_def = get_stage_definition(stage_key)
        step_def = None
        for s in stage_def.get("steps", []):
            if s["step_key"] == self.step_key:
                step_def = s
                break
        
        self.step_obj, _ = StageStep.objects.get_or_create(
            stage=self.stage_obj,
            step_key=self.step_key,
            defaults={
                "name": self.config.get("name", step_def.get("name", self.step_key)),
                "order": step_def.get("order", 100) if step_def else 100,
                "can_skip": self.config.get("can_skip", True)
            }
        )
        
        # 更新任务状态（同时写入 log_file 路径，供前端运行期间查询日志）
        self.task_obj.status = 'running'
        self.task_obj.started_at = timezone.now()
        self.task_obj.stage = self.stage_obj
        self.task_obj.step = self.step_obj
        self.task_obj.log_file = str(self.logger.log_file)
        self.task_obj.save()
        
        # 更新步骤状态
        self.step_obj.status = 'in_progress'
        self.step_obj.started_at = timezone.now()
        self.step_obj.save()
        
        # 清理停止信号
        self._clear_stop_signal()
        
        self.logger.info(f"[启动] {self.config.get('name', self.step_key)} - 项目: {self.project_obj.name}")
    
    @abstractmethod
    def execute(self) -> bool:
        """执行任务 - 子类必须实现"""
        pass
    
    def finalize(self, success: bool, error_msg: str = None):
        """收尾工作"""
        try:
            if self.step_obj:
                self.task_obj.refresh_from_db()  # 先刷新 task 状态，再决定 step 状态
                if self.task_obj.status in ('stopping', 'stopped'):
                    self.step_obj.status = 'stopped'
                else:
                    self.step_obj.status = 'completed' if success else 'failed'
                self.step_obj.completed_at = timezone.now()
                
                # 保留已有的metadata（如去重统计信息），只更新基础信息
                existing_metadata = self.step_obj.metadata or {}
                base_metadata = self._collect_step_metadata()
                existing_metadata.update(base_metadata)
                self.step_obj.metadata = existing_metadata
                
                self.step_obj.save()
            
            if self.task_obj:
                # 如果任务已被用户暂停（stopping/stopped），不覆盖为 failed
                self.task_obj.refresh_from_db()
                if self.task_obj.status in ('stopping', 'stopped'):
                    # 只更新日志路径，不改状态
                    log_meta = self.logger.get_metadata()
                    self.task_obj.logs = json.dumps(log_meta, ensure_ascii=False)
                    self.task_obj.log_file = str(self.logger.log_file)  # 始终使用绝对路径
                    self.task_obj.status = 'stopped'
                    self.task_obj.completed_at = timezone.now()
                    # 将 checkpoint 绝对路径写入 config，方便 resume_task() 直接读取
                    cp_path = self.logger.checkpoint_file
                    if cp_path.exists():
                        task_config = dict(self.task_obj.config or {})
                        task_config["checkpoint_path"] = str(cp_path)
                        self.task_obj.config = task_config
                    self.task_obj.save()
                else:
                    self.task_obj.status = 'completed' if success else 'failed'
                    self.task_obj.completed_at = timezone.now()
                    self.task_obj.progress = 1.0 if success else self.task_obj.progress
                    
                    log_meta = self.logger.get_metadata()
                    self.task_obj.logs = json.dumps(log_meta, ensure_ascii=False)
                    self.task_obj.log_file = str(self.logger.log_file)  # 始终使用绝对路径
                    
                    if error_msg:
                        self.task_obj.error_message = error_msg
                        self.logger.error(f"[失败] {error_msg}")
                    else:
                        self.logger.info(f"[完成] {self.config.get('name', self.step_key)}")
                    
                    self.task_obj.save()
        
        finally:
            self.logger.close()
            self._clear_stop_signal()
    
    def _collect_step_metadata(self) -> Dict:
        """收集步骤元数据"""
        return {
            "workspace": str(self.workspace),
            "duration": str(timezone.now() - self.task_obj.started_at) if self.task_obj and self.task_obj.started_at else None,
            "config": self.config
        }
    
    # ========================================================================
    # 停止信号检测
    # ========================================================================
    
    def check_stop_signal(self) -> bool:
        """检查停止信号"""
        stop_file = self._get_stop_file_path()
        if stop_file.exists():
            self.logger.warning("[停止] 检测到停止信号")
            return True
        return False
    
    def create_stop_signal(self, reason: str = "用户请求"):
        """创建停止信号文件"""
        stop_file = self._get_stop_file_path()
        with open(stop_file, 'w') as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "reason": reason,
                "task_id": self.task_id,
                "step_key": self.step_key
            }, f, indent=2)
        
        self.logger.info(f"[信号] 创建停止信号: {reason}")
    
    def _clear_stop_signal(self):
        """清除停止信号文件"""
        stop_file = self._get_stop_file_path()
        if stop_file.exists():
            try:
                stop_file.unlink()
            except Exception as e:
                logger.error(f"清除停止信号失败: {e}")
    
    def _get_stop_file_path(self) -> Path:
        """获取停止信号文件路径"""
        return Path(settings.BASE_DIR) / "workspaces" / f"project_{self.project_id}" / f"{self.step_key}.STOP"
    
    # ========================================================================
    # 断点续传
    # ========================================================================
    
    def save_checkpoint(self, data: Dict):
        """保存断点信息到 checkpoint.json，同时更新 progress.json 的追溯列表。

        注意：只写入 data 本身（非 wrapped 格式），让 load_checkpoint 可以直接
        读取 processed_sources 等字段，无需嵌套查找。
        progress.json 中的 checkpoints 追溯列表通过直接 append 维护，
        不再调用 add_checkpoint（后者会再次覆盖 checkpoint.json 为 wrapped 格式）。
        """
        # 写入 checkpoint.json（使用原始 data，供 load_checkpoint 直接读取）
        self.logger._save_checkpoint(data)
        # 仅将摘要信息追加到 progress.json checkpoints 列表（不覆盖 checkpoint.json）
        summary = {
            "name": "manual_checkpoint",
            "time": datetime.now().isoformat(),
            "progress": {
                "current": self.logger.progress_data.get("current", 0),
                "total": self.logger.progress_data.get("total", 0)
            }
        }
        self.logger.progress_data["checkpoints"].append(summary)
        self.logger._save_progress()
        self.logger.info(f"[断点] 保存检查点: processed={len(data.get('processed_sources', []))}")
    
    def load_checkpoint(self) -> Optional[Dict]:
        """加载断点信息"""
        return self.logger.load_checkpoint()
    
    def clear_checkpoint(self):
        """清除断点"""
        self.logger.clear_checkpoint()
    
    # ========================================================================
    # 文件操作辅助
    # ========================================================================
    
    def save_output_file(self, file_path: Path, filename: str, description: str, 
                         category: str = 'output') -> 'DataFile':
        """保存输出文件到 DataFile"""
        from core.models import DataFile
        from django.core.files.base import ContentFile
        
        # 读取文件内容
        with open(file_path, 'rb') as f:
            content = f.read()
        
        # 使用ContentFile，避免保留原始路径信息
        django_file = ContentFile(content, name=filename)
        
        data_file = DataFile.objects.create(
            project=self.project_obj,
            stage=self.stage_obj,
            step=self.step_obj,
            filename=filename,
            file=django_file,
            data_category=category,
            source='tool_generated',
            description=description,
            created_by=self.task_obj.created_by
        )
        
        self.logger.info(f"[保存] {filename} ({category})")
        return data_file
    
    def copy_input_files(self, input_files: List['DataFile'], target_dir: Path):
        """复制输入文件到工作区"""
        target_dir.mkdir(parents=True, exist_ok=True)
        
        for df in input_files:
            dest_path = target_dir / df.filename
            shutil.copy(df.file.path, dest_path)
            self.logger.info(f"[复制] {df.filename}")
    
    def get_previous_step(self, step_key: str) -> Optional['StageStep']:
        """获取前序步骤对象"""
        from core.models import StageStep
        
        try:
            return StageStep.objects.get(
                stage=self.stage_obj,
                step_key=step_key
            )
        except StageStep.DoesNotExist:
            return None
    
    def get_step_output_files(self, step_key: str, category: str = None) -> List['DataFile']:
        """获取某个步骤的输出文件"""
        from core.models import DataFile
        
        step = self.get_previous_step(step_key)
        if not step:
            return []
        
        queryset = DataFile.objects.filter(
            project=self.project_obj,
            step=step
        )
        
        if category:
            queryset = queryset.filter(data_category=category)
        
        return list(queryset)


# ============================================================================
# 工具函数
# ============================================================================

def safe_title(title: str, max_len: int = 50) -> str:
    """生成安全的目录名（截断 + hash）"""
    import re
    from hashlib import md5
    
    safe = re.sub(r'[^\w\-]', '_', title[:max_len])
    hash_suffix = md5(title.encode()).hexdigest()[:8]
    return f"{safe}_{hash_suffix}"


def format_duration(seconds: float) -> str:
    """格式化时长"""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        return f"{seconds/60:.1f}min"
    else:
        return f"{seconds/3600:.1f}h"
