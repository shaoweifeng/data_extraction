"""
Prompt 业务服务层

职责：
- 读取项目的自定义 Prompt（custom_prompt / use_custom_prompt）
- 读取系统默认 Prompt
- 保存/重置自定义 Prompt，含校验逻辑
- 写入 ActivityLog

调用方（project_views.py）只需调用这三个函数，不再直接操作 metadata 或文件路径。
"""

from pathlib import Path
from typing import Dict

from django.conf import settings

from core.models import ActivityLog, Project


# 默认 Prompt 文件路径（相对 BASE_DIR）
_DEFAULT_PROMPT_REL = "structural_screening/02_screening_ai/prompts/prompt1.txt"

# Prompt 必须包含的占位符
_REQUIRED_PLACEHOLDER = '{screening_criteria}'


# ============================================================================
# 读取
# ============================================================================

def get_prompt(project: Project) -> Dict:
    """
    获取项目 Prompt 配置。

    Returns:
        {custom_prompt, use_custom_prompt, default_prompt}
    """
    meta = project.metadata or {}
    custom_prompt = meta.get('custom_prompt', '')
    use_custom = meta.get('use_custom_prompt', False)

    prompt_path = Path(settings.BASE_DIR) / _DEFAULT_PROMPT_REL
    default_prompt = prompt_path.read_text(encoding='utf-8') if prompt_path.exists() else ''

    return {
        'custom_prompt': custom_prompt,
        'use_custom_prompt': use_custom,
        'default_prompt': default_prompt,
    }


# ============================================================================
# 保存
# ============================================================================

def save_prompt(project: Project, custom_prompt: str, use_custom: bool, user) -> Dict:
    """
    保存自定义 Prompt。

    Args:
        project: 目标项目
        custom_prompt: 自定义 Prompt 内容（已 strip）
        use_custom: 是否启用自定义 Prompt
        user: 操作用户（用于 ActivityLog）

    Returns:
        {'message': ..., 'use_custom_prompt': ...}

    Raises:
        ValueError: Prompt 校验失败（缺少占位符）
    """
    if use_custom and _REQUIRED_PLACEHOLDER not in custom_prompt:
        raise ValueError(f'Prompt 必须包含 {_REQUIRED_PLACEHOLDER} 占位符')

    project.metadata = project.metadata or {}
    project.metadata['custom_prompt'] = custom_prompt
    project.metadata['use_custom_prompt'] = use_custom
    project.save(update_fields=['metadata'])

    ActivityLog.objects.create(
        project=project,
        operation_type='prompt_set',
        operation_detail={
            'use_custom': use_custom,
            'prompt_length': len(custom_prompt),
            'prompt_preview': custom_prompt[:100] if custom_prompt else '',
        },
        created_by=user,
    )

    return {'message': '已保存', 'use_custom_prompt': use_custom}


# ============================================================================
# 重置
# ============================================================================

def reset_prompt(project: Project, user) -> Dict:
    """
    重置 Prompt 为默认值。

    Args:
        project: 目标项目
        user: 操作用户（用于 ActivityLog）

    Returns:
        {'message': ...}
    """
    project.metadata = project.metadata or {}
    project.metadata['custom_prompt'] = ''
    project.metadata['use_custom_prompt'] = False
    project.save(update_fields=['metadata'])

    ActivityLog.objects.create(
        project=project,
        operation_type='prompt_reset',
        operation_detail={},
        created_by=user,
    )

    return {'message': '已重置为默认 Prompt'}
