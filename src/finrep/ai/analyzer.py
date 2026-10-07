"""AI 价值投资分析器: 组合公司素材(业务描述+财务+MD&A) → 调 LLM 流式输出分析."""
from __future__ import annotations

import logging
from collections.abc import Iterator

import pandas as pd

from ..analysis import peer_compare, trend_summary
from ..fetcher.annual_report import AnnualReport
from ..fetcher.company_profile import CompanyProfile
from ..metrics import compute_metrics, list_metrics
from ..storage import Repository
from .llm_client import LLMClient
from .prompts import BUFFETT_MUNGER_SYSTEM

logger = logging.getLogger(__name__)

_MDA_TRUNCATE = 15000


def _fmt(value, unit: str) -> str:
    """格式化指标值 (NaN→N/A; percent 加 %)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "N/A"
    suffix = "%" if unit == "percent" else ""
    return f"{value:.2f}{suffix}"


def build_financial_text(code: str, repo: Repository, peers: list[str] | None = None) -> str:
    """构造财务素材文本: 最新年报指标 + 5年CAGR + 同业对比(可选)."""
    metrics_df = compute_metrics(repo.load_all(code))
    annual = metrics_df[metrics_df["report_date"].dt.month == 12]
    latest = annual.iloc[-1] if not annual.empty else metrics_df.iloc[-1]

    lines = [f"最新年报报告期: {latest['report_date'].date()}"]
    for m in list_metrics():
        lines.append(f"  {m['title']}: {_fmt(latest.get(m['name']), m['unit'])}")

    tr = trend_summary(code, repo, years=5)
    rev, net = tr["revenue_cagr"], tr["net_profit_cagr"]
    lines.append(f"5年营收CAGR: {rev:.2%}" if rev is not None else "5年营收CAGR: N/A")
    lines.append(f"5年净利CAGR: {net:.2%}" if net is not None else "5年净利CAGR: N/A")

    if peers:
        try:
            peer = peer_compare([code] + peers, repo)
            total = len(peer)
            lines.append(f"同业对比 (共{total}家, 最新年报):")
            value_cols = [c for c in peer.columns if not c.endswith(("_median", "_pct", "_rank"))]
            for col in value_cols[:8]:
                rank = peer.loc[code, f"{col}_rank"] if f"{col}_rank" in peer.columns else None
                med = peer.loc[code, f"{col}_median"] if f"{col}_median" in peer.columns else None
                rank_s = f"{int(rank)}/{total}" if pd.notna(rank) else "N/A"
                lines.append(f"  {col}: 本公司={_fmt(peer.loc[code, col], 'ratio')} "
                             f"中位数={_fmt(med, 'ratio')} 排名={rank_s}")
        except Exception as e:  # noqa: BLE001
            lines.append(f"(同业对比失败: {type(e).__name__})")
    return "\n".join(lines)


def analyze_stream(
    code: str,
    repo: Repository,
    company_label: str = "",
    peers: list[str] | None = None,
    use_mda: bool = True,
    provider: str | None = None,
) -> Iterator[str]:
    """组合业务描述 + 财务 + MD&A 素材, 调 LLM 流式输出价值投资分析."""
    try:
        profile_text = CompanyProfile().text(code)
    except Exception as e:  # noqa: BLE001
        profile_text = f"(业务描述抓取失败: {type(e).__name__})"

    fin_text = build_financial_text(code, repo, peers)

    mda_section = ""
    if use_mda:
        try:
            mda = AnnualReport().get_mda(code)
            mda_section = f"\n\n【年报 MD&A 原文 ({mda['year']}年)】\n{mda['mda_text'][:_MDA_TRUNCATE]}"
        except Exception as e:  # noqa: BLE001
            logger.warning("MD&A 抓取失败, 仅基于财务数据分析: %s", type(e).__name__)
            mda_section = "\n(MD&A 抓取失败, 仅基于财务数据分析)"

    user = f"""公司: {company_label or code}

【业务描述】
{profile_text}

【财务数据】
{fin_text}{mda_section}

请按框架深度分析这家公司。"""
    client = LLMClient(provider=provider)
    logger.info("AI 分析发起: code=%s provider=%s mda=%s", code, client.provider, use_mda)
    yield from client.chat_stream(BUFFETT_MUNGER_SYSTEM, user)
