"""限频与重试: 请求前随机延时 + tenacity 指数退避 (仅对网络/限频错误重试)."""
from __future__ import annotations

import random
import time
from typing import Callable, TypeVar

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..config import get_settings
from .errors import NetworkError, RateLimitError

T = TypeVar("T")


def fetch_retry(func: Callable[..., T]) -> Callable[..., T]:
    """装饰器: 对 NetworkError/RateLimitError 指数退避重试; 其他异常立即抛出."""
    max_attempts = int(get_settings().get("limits", {}).get("retry_max", 5))
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        retry=retry_if_exception_type((NetworkError, RateLimitError)),
        reraise=True,
    )(func)


def rate_limit_sleep() -> None:
    """请求前随机延时, 规避 IP 限频. 区间来自 settings.sources.akshare.request_interval."""
    interval = (
        get_settings().get("sources", {}).get("akshare", {}).get("request_interval", [0.5, 2.0])
    )
    if isinstance(interval, list) and len(interval) == 2:
        lo, hi = interval[0], interval[1]
    else:
        lo, hi = 0.5, 2.0
    time.sleep(random.uniform(lo, hi))
