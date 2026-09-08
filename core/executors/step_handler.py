"""
步骤 Handler 公共基类

每个步骤 handler 继承本类，只需实现 execute() 方法，
其余工作区管理、日志、停止信号、checkpoint 均由 BaseExecutor 提供。

设计原则：
- Handler 不持有状态，只是对 executor 能力的薄包装
- Handler.execute() 与原 executor._execute_xxx() 行为完全等价
- 新增步骤时：新增一个 handler 文件 + @register 装饰 + 注册到 handlers/__init__.py
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional, Dict, List

if TYPE_CHECKING:
    from pathlib import Path
    from core.executors.base import BaseExecutor


class BaseStepHandler(ABC):
    """
    步骤 Handler 基类

    Attributes:
        step_key: 步骤标识（由 @register 装饰器设置）
        execution_mode: "sync" 或 "async"
    """

    step_key: str = ""
    execution_mode: str = "sync"

    def __init__(self, executor: "BaseExecutor"):
        """
        Args:
            executor: 已经 initialize() 过的 BaseExecutor 实例
                      通过它访问 workspace、logger、project_obj 等
        """
        self.executor = executor
        # 快捷引用，避免写 self.executor.xxx
        self.logger = executor.logger
        self.workspace = executor.workspace
        self.project_obj = executor.project_obj
        self.task_obj = executor.task_obj
        self.step_obj = executor.step_obj
        self.stage_obj = executor.stage_obj
        self.project_id = executor.project_id
        self.config = executor.config

    @abstractmethod
    def execute(self) -> bool:
        """
        执行步骤业务逻辑。

        Returns:
            True 表示执行成功，False 表示执行失败（但不是异常）
        """

    # ── 委托方法（签名与 BaseExecutor 完全一致）──────────────────────────

    def check_stop_signal(self) -> bool:
        """检查是否收到停止信号。"""
        return self.executor.check_stop_signal()

    def save_checkpoint(self, data: Dict) -> None:
        """保存断点数据。签名与 BaseExecutor.save_checkpoint(data) 一致。"""
        self.executor.save_checkpoint(data)

    def load_checkpoint(self) -> Optional[Dict]:
        """加载断点数据。"""
        return self.executor.load_checkpoint()

    def clear_checkpoint(self) -> None:
        """清除断点。"""
        self.executor.clear_checkpoint()

    def save_output_file(self, file_path: "Path", filename: str,
                         description: str, category: str = 'output',
                         artifact_type: str = None, metadata: Dict = None):
        """
        保存产物文件到 DataFile。
        签名与 BaseExecutor.save_output_file(file_path, filename, description, category) 一致。
        """
        return self.executor.save_output_file(
            file_path, filename, description, category, artifact_type, metadata,
        )

    def get_step_output_files(self, step_key: str, category: str = None) -> List:
        """
        获取某步骤的输出文件列表。
        签名与 BaseExecutor.get_step_output_files(step_key, category) 一致。
        """
        return self.executor.get_step_output_files(step_key, category)

    def copy_input_files(self, input_files, target_dir: "Path") -> None:
        """
        批量复制输入文件到工作区。
        签名与 BaseExecutor.copy_input_files(input_files, target_dir) 一致。
        """
        self.executor.copy_input_files(input_files, target_dir)
