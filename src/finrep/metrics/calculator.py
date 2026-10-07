"""指标计算层 — 纯函数, 无副作用 (输入三大报表 → 输出指标 DataFrame).

口径说明 (MVP, 年报口径最准):
- ROE 用摊薄口径: 归母净利润 / 期末归母净资产.
- 周转率/ROA 用期末资产、累计营收/成本 (近似).
- 同比增长率按 report_date 月份对齐 (groupby month 后 pct_change): 今年Q1 vs 去年Q1.
- 缺失字段/除零 → 指标自动 NaN, 不阻断 (统一走 _safe_div).
- 百分比类指标统一 ×100.
"""
from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)

DAYS_PER_YEAR = 365
_REQUIRED_REPORTS = ("balance_sheet", "income_statement", "cash_flow")
# 百分比类指标 (结果 ×100)
_PCT_COLS = ("gross_margin", "net_margin", "net_margin_parent", "roe", "roa", "roic",
             "debt_to_asset", "revenue_yoy", "net_profit_yoy")


def _series(df: pd.DataFrame, name: str) -> pd.Series:
    """取列; 缺失返回对齐索引的 0 Series (避免标量广播歧义)."""
    if name in df.columns:
        return df[name]
    return pd.Series(0, index=df.index, dtype=float)


def _safe_div(num: pd.Series, den: pd.Series) -> pd.Series:
    """安全除法: 分母 0 替换为 NA, 返回 NaN 而非 inf."""
    return num / den.replace(0, pd.NA)


# compute_metrics 直接按键取的列全集（含 _series 兜底的可选列）——merge 后保证存在
_COMPUTE_COLS = (
    "income_tax", "total_profit", "net_profit", "net_profit_parent", "revenue",
    "operating_cost", "total_assets", "parent_equity", "inventory",
    "accounts_receivable", "total_liabilities", "current_assets",
    "current_liabilities", "cffo", "sales_cash_received", "capex",
    "interest_expense", "short_term_loan", "long_term_loan", "bonds_payable",
)


def _coalesce_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    """同名列后缀净化：merge 产生的 col/col_x/col_y 合并为单列（按顺序取首个非空）.

    2026-10-06 修复：上游若对报表帧补过占位列（防 KeyError 的容错），三表会出现
    同名列，merge 后生成 _x/_y 后缀且第三表的占位列占据标准名，导致 compute_metrics
    取到全 NaN 列（曾使全部指标输出 None）。coalesce 语义：同名科目取唯一非空来源。
    """
    suffixed = [c for c in df.columns if c.endswith(("_x", "_y"))]
    if not suffixed:
        return df
    bases = {c[:-2] for c in suffixed}
    for b in bases:
        variants = [c for c in (b, f"{b}_x", f"{b}_y") if c in df.columns]
        if len(variants) > 1:
            df[b] = df[variants].bfill(axis=1).iloc[:, 0]
        df = df.drop(columns=[c for c in variants if c != b])
    return df


def merge_reports(reports: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """按 report_date 合并三大报表. 缺键或空表 fail-fast.

    合并后做两件事（2026-10-06）：
    1. 同名列 coalesce（见 _coalesce_duplicates）；
    2. 计算所需列若缺失则补 NaN 列——在合并后的唯一真相帧上补，
       而不是像旧设计那样对原始报表帧注入（那会引发后缀分裂）。
    """
    missing = [k for k in _REQUIRED_REPORTS if k not in reports]
    if missing:
        raise ValueError(f"缺少报表: {missing}")
    if any(reports[k].empty for k in _REQUIRED_REPORTS):
        raise ValueError("存在空报表, 无法计算指标")
    df = (
        reports["balance_sheet"]
        .merge(reports["income_statement"], on="report_date", how="outer")
        .merge(reports["cash_flow"], on="report_date", how="outer")
    )
    df = _coalesce_duplicates(df)
    for col in _COMPUTE_COLS:
        if col not in df.columns:
            df[col] = float("nan")
    return df.sort_values("report_date").reset_index(drop=True)


def _yoy(df: pd.DataFrame, col: str) -> pd.Series:
    """同比增长率: 按 report_date 月份分组后 pct_change, 对齐回原顺序."""
    tmp = df[["report_date", col]].copy()
    tmp["month"] = tmp["report_date"].dt.month
    tmp = tmp.sort_values(["month", "report_date"])
    yoy = tmp.groupby("month")[col].pct_change()
    return yoy.reindex(df.index)


def compute_metrics(reports: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """计算核心指标, 返回按 report_date 升序的指标 DataFrame."""
    df = merge_reports(reports)

    # 衍生字段
    interest = _series(df, "interest_expense")
    tax_rate = _safe_div(df["income_tax"], df["total_profit"]).clip(lower=0, upper=1).fillna(0)
    interest_bearing = (
        _series(df, "short_term_loan") + _series(df, "long_term_loan") + _series(df, "bonds_payable")
    )
    nopat = df["net_profit"] + interest * (1 - tax_rate)
    invested_capital = df["parent_equity"] + interest_bearing
    revenue = df["revenue"]

    m = pd.DataFrame({"report_date": df["report_date"]})
    # ---- 盈利能力 ----
    m["gross_margin"] = _safe_div(revenue - df["operating_cost"], revenue)
    m["net_margin"] = _safe_div(df["net_profit"], revenue)
    m["net_margin_parent"] = _safe_div(df["net_profit_parent"], revenue)
    m["roe"] = _safe_div(df["net_profit_parent"], df["parent_equity"])
    m["roa"] = _safe_div(df["net_profit"], df["total_assets"])
    m["roic"] = _safe_div(nopat, invested_capital)
    # ---- 营运能力 ----
    m["asset_turnover"] = _safe_div(revenue, df["total_assets"])
    m["inventory_days"] = _safe_div(DAYS_PER_YEAR * df["inventory"], df["operating_cost"])
    m["receivable_days"] = _safe_div(DAYS_PER_YEAR * df["accounts_receivable"], revenue)
    # ---- 偿债能力 ----
    m["debt_to_asset"] = _safe_div(df["total_liabilities"], df["total_assets"])
    m["current_ratio"] = _safe_div(df["current_assets"], df["current_liabilities"])
    m["interest_coverage"] = _safe_div(df["total_profit"] + interest, interest)
    m["equity_multiplier"] = _safe_div(df["total_assets"], df["parent_equity"])
    # ---- 现金流 ----
    m["ncf_to_np"] = _safe_div(df["cffo"], df["net_profit"])
    m["cash_to_revenue"] = _safe_div(df["sales_cash_received"], revenue)
    m["fcf"] = df["cffo"] - _series(df, "capex")
    # ---- 成长能力 (同比, 同月对齐) ----
    m["revenue_yoy"] = _yoy(df, "revenue")
    m["net_profit_yoy"] = _yoy(df, "net_profit_parent")

    for c in _PCT_COLS:
        if c in m.columns:
            m[c] = m[c] * 100

    # 兜底: 清理残余 inf (理论上 _safe_div 已处理, 此为双保险)
    m = m.replace([float("inf"), float("-inf")], pd.NA)
    return m.sort_values("report_date").reset_index(drop=True)
