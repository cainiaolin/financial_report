"""单公司多年趋势分析: 年报指标序列 + 营收/净利 CAGR."""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from ..metrics import compute_metrics
from ..storage import Repository

logger = logging.getLogger(__name__)


def _annual_only(df: pd.DataFrame, years: int) -> pd.DataFrame:
    """筛年报 (month==12) 并取最近 N 年."""
    annual = df[df["report_date"].dt.month == 12].sort_values("report_date")
    return annual.tail(years).reset_index(drop=True)


def _cagr(series: pd.Series) -> float | None:
    """复合增长率 (期末/期初)^(1/n) - 1. 期初<=0 或不足 2 期返回 None."""
    series = series.dropna()
    if len(series) < 2:
        return None
    start, end = float(series.iloc[0]), float(series.iloc[-1])
    if start <= 0:
        return None
    n = len(series) - 1
    return (end / start) ** (1 / n) - 1


def trend_summary(code: str, repo: Repository, years: int = 5) -> dict[str, Any]:
    """单公司多年趋势.

    返回: {metrics: 年报指标 DataFrame, revenue_cagr, net_profit_cagr, periods}.
    公司未同步抛 FileNotFoundError.
    """
    reports = repo.load_all(code)
    metrics_df = compute_metrics(reports)
    annual_metrics = _annual_only(metrics_df, years)
    annual_income = _annual_only(reports["income_statement"], years)

    result: dict[str, Any] = {
        "code": code,
        "periods": annual_metrics["report_date"].tolist(),
        "metrics": annual_metrics,
        "revenue_cagr": _cagr(annual_income["revenue"]),
        "net_profit_cagr": _cagr(annual_income["net_profit_parent"]),
    }
    logger.info("趋势分析 %s: %d 年, 营收CAGR=%s, 净利CAGR=%s",
                code, len(annual_metrics), result["revenue_cagr"], result["net_profit_cagr"])
    return result
