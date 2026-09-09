"""
任务执行器基础框架 - 数据提取平台

核心设计：
1. 日志文件化 - TaskReporter 只写文件，DB 只存路径和元信息
2. 进度独立 - 进度数据存在独立 JSON 文件，不依赖日志解析
3. 断点续传 - 每个步骤定期保存 checkpoint
4. 停止信号 - 通过 STOP 文件检测用户中断
"""

import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, List

from django.utils import timezone

from core.workflow.domain.statuses import StageStepStatus, TaskStatus
from core.workflow.runtime import CheckpointStore, TaskReporter, WorkspaceManager
from core.workflow.services.lifecycle import (
    InvalidStateTransition,
    transition_step,
    transition_task,
)

logger = logging.getLogger(__name__)


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

        self.workspace_manager = WorkspaceManager(project_id, step_key, task_id)
        self.workspace = self._prepare_workspace()

        # 初始化日志器
        self.logger = TaskReporter(task_id, str(self.workspace))
        self.checkpoint_store = CheckpointStore(self.logger.checkpoint_file)

        # 任务对象（延迟加载）
        self.task_obj = None
        self.step_obj = None
        self.project_obj = None
        self.stage_obj = None

    def _prepare_workspace(self) -> Path:
        """准备工作区"""
        return self.workspace_manager.prepare()

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
        transition_task(
            self.task_obj,
            TaskStatus.RUNNING,
            updates={
                'started_at': self.task_obj.started_at or timezone.now(),
                'stage': self.stage_obj,
                'step': self.step_obj,
                'log_file': str(self.logger.log_file),
            },
            expected_from={TaskStatus.PENDING, TaskStatus.QUEUING, TaskStatus.RUNNING},
        )

        # 已完成/已跳过的步骤可以被用户再次执行，但状态机明确要求
        # 它们先回到 pending，不允许直接跳到 in_progress。
        # 此重置放在 worker 真正认领任务后执行，避免仅成功派发但未开始
        # 执行时就提前改变步骤状态。
        self.step_obj.refresh_from_db()
        if self.step_obj.status in (
            StageStepStatus.COMPLETED,
            StageStepStatus.SKIPPED,
        ):
            transition_step(
                self.step_obj,
                StageStepStatus.PENDING,
                updates={'started_at': None, 'completed_at': None},
                expected_from={
                    StageStepStatus.COMPLETED,
                    StageStepStatus.SKIPPED,
                },
            )

        # 更新步骤状态。每次新任务都记录自己的开始时间。
        transition_step(
            self.step_obj,
            StageStepStatus.IN_PROGRESS,
            updates={'started_at': timezone.now(), 'completed_at': None},
            expected_from={
                StageStepStatus.PENDING,
                StageStepStatus.STOPPED,
                StageStepStatus.FAILED,
                StageStepStatus.IN_PROGRESS,
            },
        )

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
                if self.task_obj.status in (TaskStatus.STOPPING, TaskStatus.STOPPED):
                    step_target = StageStepStatus.STOPPED
                else:
                    step_target = StageStepStatus.COMPLETED if success else StageStepStatus.FAILED

                # 保留已有的metadata（如去重统计信息），只更新基础信息
                existing_metadata = self.step_obj.metadata or {}
                base_metadata = self._collect_step_metadata()
                existing_metadata.update(base_metadata)
                step_updates = {'metadata': existing_metadata}
                if step_target in (
                    StageStepStatus.STOPPED,
                    StageStepStatus.COMPLETED,
                    StageStepStatus.FAILED,
                ):
                    step_updates['completed_at'] = timezone.now()
                try:
                    transition_step(self.step_obj, step_target, updates=step_updates)
                except InvalidStateTransition as exc:
                    # 即使执行器在步骤初始化期间就失败，Task 也必须能够
                    # 落到 failed，否则前端会永久轮询 running。对失败任务
                    # 保留已有步骤状态，并继续收尾 Task；成功任务仍严格报错。
                    if success:
                        raise
                    logger.warning(
                        "步骤失败状态写入被状态机拒绝，继续标记任务失败: "
                        "task_id=%s, step=%s, error=%s",
                        self.task_id,
                        self.step_key,
                        exc,
                    )

            if self.task_obj:
                # 如果任务已被用户暂停（stopping/stopped），不覆盖为 failed
                self.task_obj.refresh_from_db()
                if self.task_obj.status in (TaskStatus.STOPPING, TaskStatus.STOPPED):
                    # 只更新日志路径，不改状态
                    log_meta = self.logger.get_metadata()
                    task_updates = {
                        'logs': json.dumps(log_meta, ensure_ascii=False),
                        'log_file': str(self.logger.log_file),
                        'completed_at': timezone.now(),
                    }
                    # 将 checkpoint 绝对路径写入 config，方便 resume_task() 直接读取
                    cp_path = self.logger.checkpoint_file
                    if cp_path.exists():
                        task_config = dict(self.task_obj.config or {})
                        task_config["checkpoint_path"] = str(cp_path)
                        task_updates['config'] = task_config
                    transition_task(self.task_obj, TaskStatus.STOPPED, updates=task_updates)
                else:
                    task_target = TaskStatus.COMPLETED if success else TaskStatus.FAILED
                    log_meta = self.logger.get_metadata()
                    task_updates = {
                        'completed_at': timezone.now(),
                        'progress': 1.0 if success else self.task_obj.progress,
                        'logs': json.dumps(log_meta, ensure_ascii=False),
                        'log_file': str(self.logger.log_file),
                    }
                    if error_msg:
                        task_updates['error_message'] = error_msg
                        self.logger.error(f"[失败] {error_msg}")
                    else:
                        self.logger.info(f"[完成] {self.config.get('name', self.step_key)}")
                    transition_task(self.task_obj, task_target, updates=task_updates)

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
        if self.workspace_manager.has_stop_signal():
            self.logger.warning("[停止] 检测到停止信号")
            return True
        return False

    def create_stop_signal(self, reason: str = "用户请求"):
        """创建停止信号文件"""
        self.workspace_manager.create_stop_signal(reason)
        self.logger.info(f"[信号] 创建停止信号: {reason}")

    def _clear_stop_signal(self):
        """清除停止信号文件"""
        try:
            self.workspace_manager.clear_stop_signal()
        except OSError as e:
            logger.error(f"清除停止信号失败: {e}")

    def _get_stop_file_path(self) -> Path:
        """获取停止信号文件路径"""
        return self.workspace_manager.stop_file

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
        checkpoint_data = dict(data or {})
        checkpoint_data["_checkpoint_meta"] = {
            "project_id": self.project_id,
            "task_id": self.task_id,
            "step_key": self.step_key,
            "saved_at": datetime.now().isoformat(),
        }

        # 写入 checkpoint.json（使用原始 data，供 load_checkpoint 直接读取）
        self.checkpoint_store.save(checkpoint_data)
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
        try:
            return self.checkpoint_store.load()
        except (OSError, json.JSONDecodeError) as exc:
            self.logger.warning(f"加载断点失败: {exc}")
            return None

    def clear_checkpoint(self):
        """清除断点"""
        self.checkpoint_store.clear()

    # ========================================================================
    # 文件操作辅助
    # ========================================================================

    def save_output_file(self, file_path: Path, filename: str, description: str,
                         category: str = 'output', artifact_type: str = None,
                         metadata: Dict = None) -> 'DataFile':
        """保存输出文件到 DataFile"""
        from core.models import DataFile
        from django.core.files import File

        artifact_metadata = dict(metadata or {})
        if artifact_type:
            artifact_metadata['artifact_type'] = artifact_type

        # 直接把磁盘文件交给 Django storage 分块保存。ContentFile(f.read()) 会让
        # 大型导出文件在保存阶段再次完整驻留内存。
        with open(file_path, 'rb') as source_file:
            data_file = DataFile.objects.create(
                project=self.project_obj,
                stage=self.stage_obj,
                step=self.step_obj,
                filename=filename,
                file=File(source_file, name=filename),
                data_category=category,
                source='tool_generated',
                description=description,
                metadata=artifact_metadata,
                created_by=self.task_obj.created_by
            )

        self.logger.info(f"[保存] {filename} ({category})")
        return data_file

    def copy_input_files(self, input_files: List['DataFile'], target_dir: Path):
        """复制输入文件到工作区"""
        self.workspace_manager.copy_input_files(input_files, target_dir)
        for data_file in input_files:
            self.logger.info(f"[复制] {data_file.filename}")

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

def safe_title(title: object, max_len: int = 50) -> str:
    """生成安全的目录名（截断 + hash）"""
    import re
    from hashlib import md5

    normalized_title = str(title).strip() if title is not None else ''
    normalized_title = normalized_title or 'unknown'
    safe = re.sub(r'[^\w\-]', '_', normalized_title[:max_len])
    hash_suffix = md5(normalized_title.encode()).hexdigest()[:8]
    return f"{safe}_{hash_suffix}"


def format_duration(seconds: float) -> str:
    """格式化时长"""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        return f"{seconds/60:.1f}min"
    else:
        return f"{seconds/3600:.1f}h"
