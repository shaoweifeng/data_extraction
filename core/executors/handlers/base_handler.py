"""
步骤 Handler 基类

每个步骤 handler 继承本类，只需实现 execute() 方法，
其余工作区管理、日志、停止信号、checkpoint 均由 BaseExecutor 提供。

设计原则：
- Handler 不持有状态，只是对 executor 能力的薄包装
- Handler.execute() 与原 executor._execute_xxx() 行为完全等价
- 新增步骤时：新增一个 handler 文件 + @register 装饰 + 注册到 handlers/__init__.py
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
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

    # ── 常用快捷方法（直接委托 executor）────────────────────────────────

    def check_stop_signal(self) -> bool:
        """检查是否收到停止信号。"""
        return self.executor.check_stop_signal()

    def save_checkpoint(self, data: dict, label: str = "") -> None:
        """保存断点数据。"""
        self.executor.save_checkpoint(data, label)

    def load_checkpoint(self):
        """加载断点数据。"""
        return self.executor.load_checkpoint()

    def save_output_file(self, file_path, **kwargs):
        """保存产物文件到 DataFile。"""
        return self.executor.save_output_file(file_path, **kwargs)

    def get_step_output_files(self, step_key: str):
        """获取上一步骤的输出文件。"""
        return self.executor.get_step_output_files(step_key)
