"""同行业横向对比: 多公司指标对比 + 中位数/百分位/排名.

period: annual_latest(最新年报, 默认) | latest(最新一期) | 'YYYY-MM-DD'(指定报告期).
方法论: 基准用中位数 (财务分布右偏); 百分位按指标方向 (higher/lower_better).
MVP: 公司清单由调用方指定 (自动申万行业圈定留 V1).
"""
from __future__ import annotations

import logging

import pandas as pd

from ..metrics import compute_metrics
from ..metrics.registry import get_metric_meta
from ..storage import Repository

logger = logging.getLogger(__name__)


def _direction(metric: str) -> str:
    """查询指标方向; 未知指标按 higher_better."""
    try:
        return get_metric_meta(metric).get("direction", "higher_better")
    except KeyError:
        return "higher_better"


def _select_row(metrics_df: pd.DataFrame, period: str = "annual_latest") -> pd.Series:
    """根据 period 选取对比行.

    annual_latest: 最新年报 (month==12) | latest: 最新一期 | 'YYYY-MM-DD': 指定报告期.
    指定日期未命中时回退到最新年报.
    """
    if period == "latest":
        return metrics_df.iloc[-1]
    if period != "annual_latest":
        target = pd.to_datetime(period, errors="coerce")
        if pd.notna(target):
            matched = metrics_df[metrics_df["report_date"] == target]
            if not matched.empty:
                return matched.iloc[-1]
    annual = metrics_df[metrics_df["report_date"].dt.month == 12]
    return annual.sort_values("report_date").iloc[-1] if not annual.empty else metrics_df.iloc[-1]


def peer_compare(codes: list[str], repo: Repository,
                 metrics: list[str] | None = None, period: str = "annual_latest") -> pd.DataFrame:
    """多公司横向对比.

    返回 DataFrame (index=code): 每个指标含 原值 / _median / _pct(0-100) / _rank.
    period 控制对比报告期. 未同步的公司跳过并告警.
    """
    rows: dict[str, pd.Series] = {}
    for code in codes:
        try:
            reports = repo.load_all(code)
            latest = _select_row(compute_metrics(reports), period)
            rows[code] = latest
        except FileNotFoundError as e:
            logger.warning("跳过未同步公司 %s: %s", code, e)

    if not rows:
        raise ValueError("无可用公司 (请先 sync 对比清单中的公司)")

    df = pd.DataFrame(rows).T
    df.index.name = "code"
    metric_cols = [c for c in df.columns if c != "report_date"] if metrics is None else metrics
    df = df[metric_cols].apply(pd.to_numeric, errors="coerce")

    result = df.copy()
    for col in metric_cols:
        ascending_good = _direction(col) != "lower_better"
        result[f"{col}_median"] = result[col].median()
        # 好的 → 高百分位; 好的 → rank 1 (小数字)
        result[f"{col}_pct"] = result[col].rank(pct=True, ascending=ascending_good) * 100
        result[f"{col}_rank"] = result[col].rank(ascending=not ascending_good).astype("Int64")
    logger.info("同业对比: %d 家, %d 指标, period=%s", len(df), len(metric_cols), period)
    return result
