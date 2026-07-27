"""
同步执行器 - 数据提取平台

通过 Handler 注册表将步骤分发到对应的 StepHandler 执行。
步骤逻辑已迁移至 core/executors/handlers/ 目录下的独立 Handler 类：
  - parse_handler.py    文献解析（RIS/BIB/NBIB/XML → 统一XML）
  - dedup_handler.py    自动去重（基于标题/DOI）
  - export_handler.py   结果归纳（聚合JSON → Excel/RIS）
  - ai_screen_handler.py AI 初筛
"""

from .base import BaseExecutor


class SyncExecutor(BaseExecutor):
    """同步执行器 - 根据注册表分发到对应 Handler"""

    def execute(self) -> bool:
        """
        通过注册表查找并执行对应的 StepHandler。

        Returns:
            True if 成功

        Raises:
            ValueError: 步骤未注册
            RuntimeError: 步骤执行返回失败
            Exception: 执行过程中的其他异常
        """
        # 首次调用时触发所有 handler 的 @register 自注册
        from core.executors import handlers as _handlers  # noqa: F401
        from core.executors.registry import get_handler

        handler_cls = get_handler(self.step_key)
        if handler_cls is None:
            raise ValueError(f"未找到步骤 '{self.step_key}' 的 Handler，请检查注册表")

        try:
            handler = handler_cls(self)
            result = handler.execute()

            if not result:
                raise RuntimeError(f"{self.step_key} 步骤执行失败，请查看日志获取详情")

            return True

        except Exception as e:
            self.logger.error(f"[失败] {type(e).__name__}: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            raise
