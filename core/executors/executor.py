"""
步骤执行器 - 数据提取平台

通过 Handler 注册表将步骤分发到对应的 StepHandler 执行。
同时支持同步（普通调用）和异步（Celery Worker）两种运行方式，
两者均走同一套执行链路：StepExecutor.execute() → registry → Handler.execute()

断点兼容性校验确保跨项目/跨步骤的 checkpoint 文件不会被误读。
"""

from typing import Dict

from .base import BaseExecutor


class StepExecutor(BaseExecutor):
    """统一步骤执行器（同步/异步共用）"""

    def _is_compatible_checkpoint(self, checkpoint: Dict) -> bool:
        """校验 checkpoint 是否属于当前项目/步骤，避免串读其他任务的断点。"""
        meta = checkpoint.get("_checkpoint_meta") or {}
        if not meta:
            return True

        if meta.get("project_id") != self.project_id:
            self.logger.warning(
                f"[断点] 忽略其他项目的 checkpoint: "
                f"project_id={meta.get('project_id')} current={self.project_id}"
            )
            return False

        if meta.get("step_key") != self.step_key:
            self.logger.warning(
                f"[断点] 忽略其他步骤的 checkpoint: "
                f"step_key={meta.get('step_key')} current={self.step_key}"
            )
            return False

        return True

    def execute(self) -> bool:
        """
        通过注册表查找并执行对应的 StepHandler。

        Returns:
            True if 成功, False if 失败
        """
        from core.executors import handlers as _handlers  # noqa: F401 触发 @register 自注册
        from core.executors.registry import get_handler

        handler_cls = get_handler(self.step_key)
        if handler_cls is None:
            self.logger.error(f"未找到步骤 '{self.step_key}' 的 Handler，请检查注册表")
            return False

        handler = handler_cls(self)
        return handler.execute()

