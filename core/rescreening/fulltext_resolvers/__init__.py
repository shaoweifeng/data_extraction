"""合法开放全文查找器。

当前只接入开放获取/官方 API 来源，不实现 Sci-Hub 等非合规下载。
"""

from .pipeline import auto_bind_fulltexts_with_resolvers

__all__ = ['auto_bind_fulltexts_with_resolvers']
