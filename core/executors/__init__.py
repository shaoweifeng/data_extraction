"""
任务执行器包 - 数据提取平台

提供统一的任务执行框架：
- BaseExecutor: 执行器基类
- SyncExecutor: 同步执行器
- AsyncExecutor: 异步执行器
"""

from .base import BaseExecutor, TaskLogger

__all__ = ['BaseExecutor', 'TaskLogger']
