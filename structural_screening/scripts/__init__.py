"""
纯净脚本包 - 数据提取平台

提供三个核心功能：
- parser: 文献解析（RIS/BIB/NBIB/XML → 统一格式）
- screener: AI筛选（批处理调用AI API）
- aggregator: 结果聚合（JSON → Excel/RIS）

设计原则：
- 纯函数式，无副作用
- 无数据库操作
- 无状态管理
- 易于测试和复用
"""

__version__ = "2.0.0"
