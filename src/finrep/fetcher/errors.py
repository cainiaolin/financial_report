"""数据获取错误分类 — 决定重试还是跳过 (避免对不可恢复错误做无效重试)."""
from __future__ import annotations


class FetchError(Exception):
    """数据获取层所有异常的基类."""


class NetworkError(FetchError):
    """网络错误 (超时/连接失败) → 指数退避重试."""


class RateLimitError(FetchError):
    """限频错误 (HTTP 429/源站封禁) → 延长退避 + 切换备源."""


class DataError(FetchError):
    """数据错误 (字段缺失/单位异常/恒等式超阈值) → 标记不阻断, 写校验日志."""


class BusinessError(FetchError):
    """业务错误 (公司退市/代码无效/无数据) → 跳过并记录, 不重试."""
