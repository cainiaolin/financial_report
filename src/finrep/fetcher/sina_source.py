"""AkShare 新浪源数据获取 (主力源 — 东财源当前 ConnectionError 不可用).

接口: ak.stock_financial_report_sina(stock='sh600519', symbol='资产负债表')
单位: 元. 返回全历史报告期, 一次请求 ~3s.
"""
from __future__ import annotations

import logging

import akshare as ak
import pandas as pd

from .base import FetcherBase, ReportType
from .codes import to_ak_sina
from .errors import BusinessError, NetworkError, RateLimitError
from .field_map import SINA_REPORT_NAME
from .retry import fetch_retry, rate_limit_sleep

logger = logging.getLogger(__name__)

# 视为网络/限频错误的关键词 (异常名或消息中出现)
_NET_KEYWORDS = ("connection", "timeout", "remotedisconnected", "connect", "timed out", "read time")
_RATE_KEYWORDS = ("429", "rate", "频繁", "限制", "blocked")


class SinaFetcher(FetcherBase):
    """新浪源三大报表抓取."""
    source_name = "sina"

    @fetch_retry
    def _fetch_raw(self, code6: str, report_type: ReportType) -> pd.DataFrame:
        sina_code = to_ak_sina(code6)               # sh600519
        symbol = SINA_REPORT_NAME[report_type]
        rate_limit_sleep()
        try:
            df = ak.stock_financial_report_sina(stock=sina_code, symbol=symbol)
        except Exception as e:
            # 仅记录异常类型, 不透传原始消息 (避免潜在凭证泄露)
            etype = type(e).__name__
            msg = str(e).lower()
            name = etype.lower()
            if any(k in name or k in msg for k in _NET_KEYWORDS):
                raise NetworkError(f"新浪源连接失败 {code6} {report_type}: {etype}") from e
            if any(k in msg for k in _RATE_KEYWORDS):
                raise RateLimitError(f"新浪源限频 {code6}: {etype}") from e
            raise BusinessError(f"新浪源抓取失败 {code6} {report_type}: {etype}") from e
        if df is None or len(df) == 0:
            raise BusinessError(f"新浪源无数据 {code6} {report_type}")
        logger.info("sina 抓取成功 %s %s: %d 行", code6, report_type, len(df))
        return df
