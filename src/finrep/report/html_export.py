"""HTML 报告导出: Jinja2 模板 + pyecharts 图表嵌入.

生成自包含 HTML (含交互图表), 可浏览器打开/邮件分发.
异常处理: fail-fast — 数据/模板/IO 错误向上传播, 由调用方(CLI/看板)统一处理.
安全说明: 图表来自 pyecharts render_embed (受控数值), 表格用 pandas to_html (默认转义),
故模板中以 | safe 嵌入是安全的 (无用户可控的原始 HTML).
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..analysis import peer_compare, trend_summary
from ..config import get_settings
from ..metrics import compute_metrics, list_metrics
from ..storage import Repository
from ..viz.charts import peer_radar_chart, trend_line_chart

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)
_RADAR_DIMS = ["roe", "gross_margin", "debt_to_asset", "revenue_yoy", "ncf_to_np", "current_ratio"]
_PEER_SUFFIX = ("_median", "_pct", "_rank")


def _latest_annual(metrics_df: pd.DataFrame) -> pd.Series:
    """取最新年报行; 无年报则取最后一期. 空表 raise ValueError."""
    if metrics_df.empty:
        raise ValueError("指标数据为空, 无法取最新年报")
    annual = metrics_df[metrics_df["report_date"].dt.month == 12]
    return annual.iloc[-1] if not annual.empty else metrics_df.iloc[-1]


def render_report(code: str, repo: Repository, peers: list[str] | None = None,
                  output: str | Path | None = None) -> Path:
    """渲染单公司 HTML 报告 (含趋势图/同业雷达/指标表). 返回输出路径."""
    reports = repo.load_all(code)
    metrics_df = compute_metrics(reports)
    tr = trend_summary(code, repo, years=5)

    # 最新年报指标 → 干净 dict (NaN→None, 便于模板渲染)
    metrics_list = list_metrics()
    latest = _latest_annual(metrics_df)
    latest_clean: dict[str, float | None] = {}
    for m in metrics_list:
        v = latest.get(m["name"])
        latest_clean[m["name"]] = None if pd.isna(v) else round(float(v), 2)

    # 趋势图 (pyecharts render_embed, 受控内容)
    trend_charts = {
        m: trend_line_chart(metrics_df, m).render_embed()
        for m in ("roe", "gross_margin", "revenue_yoy")
    }
    cagr_rev = f"{tr['revenue_cagr'] * 100:.2f}%" if tr["revenue_cagr"] is not None else "N/A"
    cagr_np = f"{tr['net_profit_cagr'] * 100:.2f}%" if tr["net_profit_cagr"] is not None else "N/A"

    # 同业对比 (to_html 默认转义 HTML 字符)
    peer_table_html: str | None = None
    peer_radar_html: str | None = None
    if peers:
        peer = peer_compare([code] + peers, repo)
        display_cols = [c for c in peer.columns if not c.endswith(_PEER_SUFFIX)]
        peer_table_html = peer[display_cols].to_html(index=True, border=1)
        peer_radar_html = peer_radar_chart(peer, _RADAR_DIMS).render_embed()

    html = _env.get_template("report.html").render(
        code=code,
        metrics_list=metrics_list,
        latest=latest_clean,
        cagr_rev=cagr_rev,
        cagr_np=cagr_np,
        trend_charts=trend_charts,
        peer_table=peer_table_html,
        peer_radar=peer_radar_html,
    )

    output_path = Path(output) if output else (
        Path(get_settings()["paths"]["reports_dir"]) / "html" / f"{code}.html"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    logger.info("HTML 报告导出: %s", output_path)
    return output_path
