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
    """统一对外入口: 容灾(主力失败→备源) + 可选双源交叉校验关键字段.

    2026-10-06 调整: **tushare 为默认主源**（结构化接口稳定），sina 降为备源容灾。
    此前 sina 为主源时，页面结构漂移/限流会间歇性返回空帧或字段全 NaN 的残缺帧
    （不抛异常），流入指标层后污染了 117 只股票的指标缓存。
    tushare 未配置时自动退回 sina 单源。
    """

    def __init__(self) -> None:
        self.backup: SinaFetcher | None = SinaFetcher()
        if is_tushare_configured():
            self.primary = TushareFetcher()
        else:
            self.primary = self.backup
            self.backup = None
            logger.warning("Tushare 未配置, 仅启用新浪单源 (无法双源校验)")

    @staticmethod
    def _frame_usable(df: pd.DataFrame | None) -> bool:
        """数据质量门：非空，且除 report_date 外至少一列有 ≥50% 非空值.

        拦截"行数存在但值列全 NaN"的残缺帧（sina 页面漂移的典型故障形态），
        这类帧流入 compute_metrics 会产出全 None 指标并被上游缓存。
        """
        if df is None or df.empty:
            return False
        value_cols = [c for c in df.columns if c != "report_date"]
        if not value_cols:
            return False
        return any(df[c].notna().mean() >= 0.5 for c in value_cols)

    def fetch(self, code: str, report_type: ReportType) -> FetchResult:
        """容灾抓取: 主力失败/返回空数据/数据残缺时自动切换备源."""
        req = FetchRequest(code=code, report_type=report_type)
        try:
            result = self.primary.fetch(req)
        except FetchError as e:
            if self.backup is None:
                raise
            logger.warning("主源(tushare)失败 %s %s: %s → 切换备源", code, report_type, e)
            return self.backup.fetch(req)
        if self._frame_usable(result.data):
            return result
        if self.backup is None:
            logger.warning("主源(tushare)数据不可用 %s %s 且无备源", code, report_type)
            return result
        logger.warning("主源(tushare)数据空/残缺 %s %s → 切换备源(sina)", code, report_type)
        try:
            fallback = self.backup.fetch(req)
        except FetchError as e:
            logger.warning("备源(sina)也失败 %s %s: %s → 返回主源结果", code, report_type, e)
            return result
        return fallback if self._frame_usable(fallback.data) else result

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
