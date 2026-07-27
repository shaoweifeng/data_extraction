"""
AI 模型配置 - 已迁移至 core/services/ai_models_config.py
此文件仅保留向后兼容转发，请勿在此直接修改。
"""
from core.services.ai_models_config import (  # noqa: F401
    AI_MODELS,
    get_model_config,
    get_models_for_frontend,
)
