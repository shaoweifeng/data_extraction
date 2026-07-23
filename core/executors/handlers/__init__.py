# handlers 包初始化：导入所有 handler，触发 @register 自注册
from .parse_handler import ParseHandler
from .dedup_handler import DedupHandler
from .export_handler import ExportHandler
from .ai_screen_handler import AIScreenHandler

__all__ = ["ParseHandler", "DedupHandler", "ExportHandler", "AIScreenHandler"]
