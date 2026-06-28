"""数据获取编排: 主力(sina) + 备源(tushare) 容灾切换 + 双源交叉校验."""
from __future__ import annotations

import logging

import pandas as pd

from ..config import get_settings, is_tushare_configured
from .base import FetchRequest, FetchResult, ReportType
from .errors import FetchError
from .sina_source import SinaFetcher
from .tushare_source import TushareFetcher

logger = logging.getLogger(__name__)


class FetcherManager:
    """统一对外入口: 容灾(主力失败→备源) + 可选双源交叉校验关键字段."""

    def __init__(self) -> None:
        self.primary: SinaFetcher = SinaFetcher()
        self.backup: TushareFetcher | None = TushareFetcher() if is_tushare_configured() else None
        if self.backup is None:
            logger.warning("Tushare 未配置, 仅启用新浪单源 (无法双源校验)")

    def fetch(self, code: str, report_type: ReportType) -> FetchResult:
        """容灾抓取: 主力失败时自动切换备源."""
        req = FetchRequest(code=code, report_type=report_type)
        try:
            return self.primary.fetch(req)
        except FetchError as e:
            if self.backup is None:
                raise
            logger.warning("主力源失败 %s %s: %s → 切换 tushare", code, report_type, e)
            return self.backup.fetch(req)

    def fetch_all(self, code: str) -> dict[str, FetchResult]:
        """抓取三大报表."""
        return {rt: self.fetch(code, rt) for rt in ("balance_sheet", "income_statement", "cash_flow")}

    def fetch_validated(self, code: str, report_type: ReportType) -> FetchResult:
        """双源抓取并交叉校验关键字段 (差异超阈值标记不阻断, 返回主力数据)."""
        primary = self.primary.fetch(FetchRequest(code=code, report_type=report_type))
        if primary.data.empty or self.backup is None:
            return primary
        try:
            backup = self.backup.fetch(FetchRequest(code=code, report_type=report_type))
        except FetchError as e:
            logger.warning("备源校验抓取失败, 跳过交叉校验: %s", e)
            return primary
        self._cross_validate(primary.data, backup.data, code, report_type)
        return primary

    @staticmethod
    def _cross_validate(a: pd.DataFrame, b: pd.DataFrame, code: str, report_type: ReportType) -> None:
        cfg = get_settings().get("validation", {})
        try:
            threshold = float(cfg.get("cross_source_threshold", 0.01))
        except (TypeError, ValueError):
            threshold = 0.01
        key_fields = cfg.get("key_fields", []) or []
        merged = pd.merge(a, b, on="report_date", suffixes=("_sina", "_ts"))
        if merged.empty:
            return
        for f in key_fields:
            ca, cb = f"{f}_sina", f"{f}_ts"
            if ca not in merged.columns or cb not in merged.columns:
                continue
            base_val = merged[ca].abs()
            mask = base_val > 1e-6                       # 排除 0 与极小值, 避免除零
            if not mask.any():
                continue
            ratio = ((merged.loc[mask, ca] - merged.loc[mask, cb]).abs() / base_val[mask]).dropna()
            if not ratio.empty and (ratio > threshold).any():
                logger.warning(
                    "双源差异超阈值 %s %s.%s: 最大 %.2f%% (阈值 %.0f%%)",
                    code, report_type, f, ratio.max() * 100, threshold * 100,
                )
