"""
步骤配置中心 - 数据提取平台

定义所有步骤的执行配置，包括：
- 执行模式（sync/async/manual/pipeline）
- 超时时间
- 重试策略
- 输入输出定义
- 监控配置
- 依赖关系
"""

# ============================================================================
# 步骤配置表
# ============================================================================

STEP_CONFIGURATIONS = {
    # ========================================================================
    # 阶段1: 文献检索（手动）
    # ========================================================================
    "SEARCH": {
        "name": "文献检索",
        "stage_key": "SEARCH",
        "execution_mode": "manual",
        "description": "用户自行检索文献并上传结果文件",
        "auto_trigger": False,
        "dependencies": [],
        "timeout": None,
        "retry_policy": None,
        "monitoring": {
            "progress_type": "boolean",
            "checkpoints": []
        },
        "ui_actions": ["upload_files"],
        "metadata_template": {
            "search_database": "",
            "search_date": "",
            "total_results": 0
        }
    },
    
    # ========================================================================
    # 阶段2: 文献初筛（流水线）
    # ========================================================================
    "SCREEN_1": {
        "name": "文献初筛",
        "stage_key": "SCREEN_1",
        "execution_mode": "pipeline",
        "description": "文献自动解析、去重、AI筛选、结果归纳",
        "auto_trigger": True,
        "dependencies": ["SEARCH"],
        "sub_steps": ["parse", "dedup", "criteria", "field_extraction", "ai_screen", "export"],
        "monitoring": {
            "progress_type": "aggregate",
            "weight_distribution": {
                "parse": 0.1,
                "dedup": 0.1,
                "criteria": 0.1,
                "field_extraction": 0.1,
                "ai_screen": 0.5,
                "export": 0.1
            }
        },
        "metadata_template": {}
    },
    
    # ------------------------------------------------------------------------
    # 子步骤: 文献解析（同步）
    # ------------------------------------------------------------------------
    "parse": {
        "name": "导入文献索引",
        "stage_key": "SCREEN_1",
        "execution_mode": "async",
        "description": "解析RIS/BIB/NBIB/XML格式文献",
        "timeout": 300,
        "retry_policy": {
            "max_retries": 2,
            "retry_delay": 5,
            "retry_on": ["file_error", "parse_error"]
        },
        "inputs": ["*.ris", "*.bib", "*.nbib", "*.xml"],
        "outputs": ["references.xml", "split_xmls/*.xml"],
        "monitoring": {
            "progress_type": "file_count",
            "progress_unit": "files",
            "update_interval": 1
        },
        "logging": {
            "level": "INFO",
            "rotation": "10MB",
            "retention": "7 days"
        },
        "metadata_template": {
            "total_files": 0,
            "total_entries": 0,
            "unique_entries": 0,
            "split_files": 0
        }
    },
    
    # ------------------------------------------------------------------------
    # 子步骤: 自动去重（同步）
    # ------------------------------------------------------------------------
    "dedup": {
        "name": "自动去重",
        "stage_key": "SCREEN_1",
        "execution_mode": "async",
        "description": "基于标题/DOI自动去重",
        "timeout": 180,
        "can_skip": True,
        "skip_if_no_duplicates": True,
        "retry_policy": {
            "max_retries": 1,
            "retry_delay": 3
        },
        "inputs": ["split_xmls/*.xml"],
        "outputs": ["dedup_xmls/*.xml", "dedup_report.json"],
        "monitoring": {
            "progress_type": "counter",
            "progress_unit": "refs",
            "update_interval": 100
        },
        "logging": {
            "level": "INFO",
            "rotation": "10MB"
        },
        "metadata_template": {
            "total_files": 0,
            "kept_files": 0,
            "duplicates": 0,
            "duplicate_rate": "0%"
        }
    },
    
    # ------------------------------------------------------------------------
    # 子步骤: 纳排标准（手动）
    # ------------------------------------------------------------------------
    "criteria": {
        "name": "纳排标准",
        "stage_key": "SCREEN_1",
        "execution_mode": "manual",
        "description": "用户设置初筛纳排标准",
        "timeout": None,
        "auto_trigger": False,
        "inputs": [],
        "outputs": ["screening_criteria.json"],
        "ui_actions": ["add_criteria", "edit_criteria", "delete_criteria", "confirm_criteria"],
        "monitoring": {
            "progress_type": "boolean",
            "requires_user_action": True
        },
        "metadata_template": {
            "criteria_count": 0,
            "confirmed": False,
            "confirmed_at": None
        }
    },
    
    # ------------------------------------------------------------------------
    # 子步骤: 提取字段（手动，定义字段后在 AI 初筛时一并提取）
    # ------------------------------------------------------------------------
    "field_extraction": {
        "name": "提取字段",
        "stage_key": "SCREEN_1",
        "execution_mode": "manual",
        "description": "用户定义需要 AI 从纳入文献中提取的自定义字段",
        "timeout": None,
        "auto_trigger": False,
        "inputs": [],
        "outputs": ["extraction_fields.json"],
        "ui_actions": ["add_field", "edit_field", "delete_field"],
        "monitoring": {
            "progress_type": "boolean",
            "requires_user_action": True
        },
        "metadata_template": {
            "fields": [],
            "confirmed": False,
            "confirmed_at": None
        }
    },
    
    # ------------------------------------------------------------------------
    # 子步骤: AI初筛（异步）
    # ------------------------------------------------------------------------
    "ai_screen": {
        "name": "AI初筛",
        "stage_key": "SCREEN_1",
        "execution_mode": "async",
        "description": "调用AI接口进行文献筛选",
        "timeout": 7200,
        "batch_size": 16,
        # concurrency 不在此预置，由 get_user_concurrency(user) 动态计算（普通用户2，管理员16）
        "resume_capability": True,
        "checkpoint_interval": 16,
        "inputs": ["dedup_xmls/*.xml", "screening_criteria.json"],
        "outputs": ["results/*/*.json"],
        "retry_policy": {
            "max_retries": 3,
            "retry_delay": 10,
            "retry_on": ["timeout", "rate_limit", "api_error", "network_error"]
        },
        "monitoring": {
            "progress_type": "percentage",
            "progress_unit": "refs",
            "real_time_update": True,
            "update_interval": 5,
            "websocket_channel": "project_{project_id}.screening"
        },
        "logging": {
            "level": "DEBUG",
            "rotation": "50MB",
            "retention": "30 days"
        },
        "metadata_template": {
            "total_refs": 0,
            "processed_refs": 0,
            "included_refs": 0,
            "excluded_refs": 0,
            "error_refs": 0,
            "start_time": None,
            "end_time": None,
            "duration": None
        }
    },
    
    # ------------------------------------------------------------------------
    # 子步骤: 结果归纳（同步）
    # ------------------------------------------------------------------------
    "export": {
        "name": "结果归纳",
        "stage_key": "SCREEN_1",
        "execution_mode": "sync",
        "description": "聚合筛选结果生成Excel/RIS",
        "timeout": 120,
        "inputs": ["results/*/*.json"],
        "outputs": ["screening_results.xlsx", "screening_results.ris"],
        "retry_policy": {
            "max_retries": 1,
            "retry_delay": 5
        },
        "monitoring": {
            "progress_type": "boolean"
        },
        "logging": {
            "level": "INFO"
        },
        "metadata_template": {
            "total_results": 0,
            "included_count": 0,
            "excluded_count": 0,
            "file_size_excel": 0,
            "file_size_ris": 0
        }
    },
    
    # ========================================================================
    # 阶段3: 文献复筛（手动）
    # ========================================================================
    "SCREEN_2": {
        "name": "文献复筛",
        "stage_key": "SCREEN_2",
        "execution_mode": "manual",
        "description": "人工阅读全文进行二次筛选",
        "dependencies": ["SCREEN_1"],
        "timeout": None,
        "ui_actions": ["download_fulltext", "mark_screened", "add_notes"],
        "monitoring": {
            "progress_type": "manual_count",
            "progress_unit": "refs"
        },
        "metadata_template": {
            "total_refs": 0,
            "screened_refs": 0,
            "included_refs": 0,
            "excluded_refs": 0
        }
    },
    
    # ========================================================================
    # 阶段4: 文献质量评价（手动）
    # ========================================================================
    "QUALITY": {
        "name": "文献质量评价",
        "stage_key": "QUALITY",
        "execution_mode": "manual",
        "description": "评价纳入文献的方法学质量",
        "dependencies": ["SCREEN_2"],
        "timeout": None,
        "ui_actions": ["evaluate_quality", "add_quality_notes"],
        "monitoring": {
            "progress_type": "manual_count",
            "progress_unit": "refs"
        },
        "metadata_template": {
            "total_refs": 0,
            "evaluated_refs": 0,
            "high_quality": 0,
            "medium_quality": 0,
            "low_quality": 0
        }
    },
    
    # ========================================================================
    # 阶段5: 数据提取（手动）
    # ========================================================================
    "EXTRACT": {
        "name": "数据提取",
        "stage_key": "EXTRACT",
        "execution_mode": "manual",
        "description": "从纳入文献中提取研究数据",
        "dependencies": ["QUALITY"],
        "timeout": None,
        "ui_actions": ["extract_data", "validate_data", "export_data"],
        "monitoring": {
            "progress_type": "manual_count",
            "progress_unit": "refs"
        },
        "metadata_template": {
            "total_refs": 0,
            "extracted_refs": 0,
            "variables_count": 0
        }
    },
    
    # ========================================================================
    # 阶段6: Meta分析（异步）
    # ========================================================================
    "META": {
        "name": "Meta分析",
        "stage_key": "META",
        "execution_mode": "async",
        "description": "执行Meta分析统计计算",
        "dependencies": ["EXTRACT"],
        "timeout": 3600,
        "inputs": ["extraction_data.xlsx"],
        "outputs": ["meta_results.xlsx", "forest_plot.png", "funnel_plot.png"],
        "retry_policy": {
            "max_retries": 2,
            "retry_delay": 30
        },
        "monitoring": {
            "progress_type": "percentage",
            "progress_unit": "analysis",
            "update_interval": 10
        },
        "logging": {
            "level": "INFO",
            "rotation": "20MB"
        },
        "metadata_template": {
            "studies_count": 0,
            "effect_size": None,
            "confidence_interval": None,
            "heterogeneity_i2": None
        }
    }
}


# ============================================================================
# 阶段定义表
# ============================================================================

STAGE_DEFINITIONS = [
    {
        "stage_key": "SEARCH",
        "name": "文献检索",
        "order": 10,
        "steps": []
    },
    {
        "stage_key": "SCREEN_1",
        "name": "文献初筛",
        "order": 20,
        "steps": [
            {"step_key": "parse", "name": "导入文献索引", "order": 10, "can_skip": False},
            {"step_key": "dedup", "name": "自动去重", "order": 20, "can_skip": True},
            {"step_key": "criteria", "name": "纳排标准", "order": 30, "can_skip": False},
            {"step_key": "field_extraction", "name": "提取字段", "order": 35, "can_skip": True},
            {"step_key": "ai_screen", "name": "AI初筛", "order": 40, "can_skip": False},
            {"step_key": "export", "name": "结果归纳", "order": 50, "can_skip": False}
        ]
    },
    {
        "stage_key": "SCREEN_2",
        "name": "文献复筛",
        "order": 30,
        "steps": []
    },
    {
        "stage_key": "QUALITY",
        "name": "文献质量评价",
        "order": 40,
        "steps": []
    },
    {
        "stage_key": "EXTRACT",
        "name": "数据提取",
        "order": 50,
        "steps": []
    },
    {
        "stage_key": "META",
        "name": "Meta分析",
        "order": 60,
        "steps": []
    }
]


# ============================================================================
# 辅助函数
# ============================================================================

def get_step_config(step_key: str) -> dict:
    """
    获取步骤配置
    
    Args:
        step_key: 步骤标识（parse/dedup/criteria等）
    
    Returns:
        步骤配置字典
    
    Raises:
        KeyError: 步骤不存在
    """
    if step_key not in STEP_CONFIGURATIONS:
        raise KeyError(f"未知的步骤: {step_key}")
    return STEP_CONFIGURATIONS[step_key]


def get_stage_definition(stage_key: str) -> dict:
    """
    获取阶段定义
    
    Args:
        stage_key: 阶段标识（SEARCH/SCREEN_1等）
    
    Returns:
        阶段定义字典
    
    Raises:
        KeyError: 阶段不存在
    """
    for stage_def in STAGE_DEFINITIONS:
        if stage_def["stage_key"] == stage_key:
            return stage_def
    raise KeyError(f"未知的阶段: {stage_key}")


def get_execution_mode(step_key: str) -> str:
    """
    获取步骤的执行模式
    
    Args:
        step_key: 步骤标识
    
    Returns:
        执行模式（sync/async/manual/pipeline）
    """
    config = get_step_config(step_key)
    return config.get("execution_mode", "sync")


def is_async_step(step_key: str) -> bool:
    """
    判断是否为异步步骤
    
    Args:
        step_key: 步骤标识
    
    Returns:
        True if 异步步骤, False otherwise
    """
    return get_execution_mode(step_key) == "async"


def is_manual_step(step_key: str) -> bool:
    """
    判断是否为手动步骤
    
    Args:
        step_key: 步骤标识
    
    Returns:
        True if 手动步骤, False otherwise
    """
    return get_execution_mode(step_key) == "manual"


def get_sub_steps(stage_key: str) -> list:
    """
    获取阶段包含的子步骤列表
    
    Args:
        stage_key: 阶段标识
    
    Returns:
        子步骤键列表
    """
    if stage_key in STEP_CONFIGURATIONS:
        return STEP_CONFIGURATIONS[stage_key].get("sub_steps", [])
    
    stage_def = get_stage_definition(stage_key)
    return [step["step_key"] for step in stage_def.get("steps", [])]


def get_step_order(step_key: str) -> int:
    """
    获取步骤的执行顺序
    
    Args:
        step_key: 步骤标识
    
    Returns:
        步骤顺序号
    """
    # 如果是阶段本身，返回阶段定义的order
    if step_key in [stage["stage_key"] for stage in STAGE_DEFINITIONS]:
        return get_stage_definition(step_key)["order"]
    
    # 否则查找子步骤定义中的order
    config = get_step_config(step_key)
    stage_key = config.get("stage_key")
    stage_def = get_stage_definition(stage_key)
    
    for step_def in stage_def.get("steps", []):
        if step_def["step_key"] == step_key:
            return step_def["order"]
    
    return 100  # 默认靠后


def can_skip_step(step_key: str) -> bool:
    """
    判断步骤是否可以跳过
    
    Args:
        step_key: 步骤标识
    
    Returns:
        True if 可跳过, False otherwise
    """
    config = get_step_config(step_key)
    return config.get("can_skip", False)


def get_retry_policy(step_key: str) -> dict:
    """
    获取步骤的重试策略
    
    Args:
        step_key: 步骤标识
    
    Returns:
        重试策略字典
    """
    config = get_step_config(step_key)
    return config.get("retry_policy", {})


def get_timeout(step_key: str) -> int:
    """
    获取步骤的超时时间（秒）
    
    Args:
        step_key: 步骤标识
    
    Returns:
        超时秒数，None表示无限制
    """
    config = get_step_config(step_key)
    return config.get("timeout")


def get_monitoring_config(step_key: str) -> dict:
    """
    获取步骤的监控配置
    
    Args:
        step_key: 步骤标识
    
    Returns:
        监控配置字典
    """
    config = get_step_config(step_key)
    return config.get("monitoring", {})


def get_inputs(step_key: str) -> list:
    """
    获取步骤的输入文件模式列表
    
    Args:
        step_key: 步骤标识
    
    Returns:
        输入文件模式列表
    """
    config = get_step_config(step_key)
    return config.get("inputs", [])


def get_outputs(step_key: str) -> list:
    """
    获取步骤的输出文件模式列表
    
    Args:
        step_key: 步骤标识
    
    Returns:
        输出文件模式列表
    """
    config = get_step_config(step_key)
    return config.get("outputs", [])


def get_metadata_template(step_key: str) -> dict:
    """
    获取步骤的元数据模板
    
    Args:
        step_key: 步骤标识
    
    Returns:
        元数据模板字典（深拷贝）
    """
    config = get_step_config(step_key)
    import copy
    return copy.deepcopy(config.get("metadata_template", {}))
