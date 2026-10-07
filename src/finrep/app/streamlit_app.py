"""A股财报分析 Streamlit 看板.

运行: streamlit run src/finrep/app/streamlit_app.py
依赖: pip install finrep[web]
"""
from __future__ import annotations

import logging

import streamlit as st

from finrep.ai import analyze_stream
from finrep.analysis import peer_compare, trend_summary
from finrep.fetcher.codes import normalize_code
from finrep.fetcher.company_info import CompanyInfo
from finrep.fetcher.errors import FetchError
from finrep.fetcher.manager import FetcherManager
from finrep.metrics import compute_metrics, list_metrics, radar_dimensions
from finrep.storage import Repository
from finrep.viz.charts import peer_bar_chart, peer_radar_chart, trend_line_chart

logger = logging.getLogger(__name__)

_PERIOD_OPTIONS = {"最新年报": "annual_latest", "最新一期": "latest", "指定日期": "date"}


def render_chart(chart, height: int = 400) -> None:
    """渲染 pyecharts 图表到 Streamlit."""
    st.components.v1.html(chart.render_embed(), height=height)


def _valid_codes(raw_codes: list[str]) -> list[str]:
    valid: list[str] = []
    for c in raw_codes:
        try:
            valid.append(normalize_code(c))
        except ValueError:
            st.sidebar.warning(f"忽略无效代码: {c}")
    return valid


def _sync_codes(codes: list[str]) -> None:
    if not codes:
        return
    fm = FetcherManager()
    with Repository() as repo:
        progress = st.sidebar.progress(0.0)
        for i, c in enumerate(codes):
            try:
                for _, r in fm.fetch_all(c).items():
                    repo.save(r)
            except FetchError as e:
                logger.warning("%s 同步失败: %s", c, e)
                st.sidebar.warning(f"{c} 同步失败: {type(e).__name__}")
            progress.progress((i + 1) / len(codes))
        st.sidebar.success("同步完成")


def _single_company_section(repo: Repository, code: str, company_info: CompanyInfo) -> None:
    st.header(f"{company_info.label(code)} 单公司分析")
    metrics_df = compute_metrics(repo.load_all(code))
    options = [m["name"] for m in list_metrics()]
    metric = st.selectbox("选择指标", options, index=options.index("roe") if "roe" in options else 0)
    col_chart, col_latest = st.columns([2, 1])
    with col_chart:
        render_chart(trend_line_chart(metrics_df, metric))
    with col_latest:
        st.subheader("最新年报指标")
        annual = metrics_df[metrics_df["report_date"].dt.month == 12]
        latest = annual.iloc[-1] if not annual.empty else metrics_df.iloc[-1]
        st.dataframe(latest.drop("report_date").rename("值"))
    tr = trend_summary(code, repo, years=5)
    c1, c2 = st.columns(2)
    c1.metric("营收 CAGR (5年)", f"{tr['revenue_cagr']:.2%}" if tr["revenue_cagr"] is not None else "N/A")
    c2.metric("净利 CAGR (5年)", f"{tr['net_profit_cagr']:.2%}" if tr["net_profit_cagr"] is not None else "N/A")


def _peer_section(repo: Repository, codes: list[str], period: str, company_info: CompanyInfo) -> None:
    st.header("同业对比")
    try:
        peer = peer_compare(codes, repo, period=period)
    except ValueError as e:
        st.warning(str(e))
        return
    peer_view = peer.rename(index={c: company_info.label(c) for c in peer.index})
    render_chart(peer_radar_chart(peer_view, radar_dimensions()), height=450)
    st.subheader("指标排名表")
    st.dataframe(peer_view)
    bar_metric = st.selectbox(
        "柱状对比指标",
        [c for c in peer.columns if not c.endswith(("_median", "_pct", "_rank"))],
        key="bar_metric",
    )
    render_chart(peer_bar_chart(peer_view, bar_metric))


def _ai_section(repo: Repository, code: str, company_info: CompanyInfo, peers: list[str]) -> None:
    st.header("🤖 AI 价值投资分析 (巴菲特/芒格视角)")
    from finrep.config import get_settings
    ai = get_settings().get("ai", {})
    available = [p for p in ("glm", "deepseek") if ai.get(p, {}).get("api_key")]
    if not available:
        st.warning("⚠️ 未配置 LLM API key — 请在 .env 设 ZHIPU_API_KEY 或 DEEPSEEK_API_KEY 后重启")
        return
    col1, _col2 = st.columns([1, 4])
    with col1:
        default_idx = available.index("glm") if "glm" in available else 0
        provider = st.selectbox("LLM 提供商", available, index=default_idx)
        use_mda = st.checkbox("包含年报 MD&A 全文", value=True,
                              help="勾选后抓取巨潮年报 PDF 的「经营情况讨论与分析」章节")
        trigger = st.button("⚡ 生成 AI 分析", type="primary")
    if trigger:
        with st.spinner("AI 分析中 (含 MD&A 时首次需抓 PDF, 请稍候)..."):
            try:
                stream = analyze_stream(
                    code, repo,
                    company_label=company_info.label(code),
                    peers=peers or None,
                    use_mda=use_mda,
                    provider=provider,
                )
                st.write_stream(stream)
            except ValueError as e:
                st.error(f"配置错误: {e}")
            except Exception as e:  # noqa: BLE001
                st.error(f"AI 分析失败: {type(e).__name__}: {e}")


def main() -> None:
    st.set_page_config(page_title="A股财报分析", page_icon="📊", layout="wide")
    st.title("📊 A股财报分析系统")

    code_raw = st.sidebar.text_input("主公司代码", value="600519")
    peers_str = st.sidebar.text_input("对比公司 (逗号分隔)", value="000858,002304")
    peers_raw = [c.strip() for c in peers_str.split(",") if c.strip()]

    period_label = st.sidebar.selectbox("对比报告期", list(_PERIOD_OPTIONS), index=0)
    if period_label == "指定日期":
        period = st.sidebar.text_input("报告日期 (YYYY-MM-DD)", value="2024-12-31")
    else:
        period = _PERIOD_OPTIONS[period_label]

    codes = _valid_codes([code_raw] + peers_raw)
    if not codes:
        st.warning("请输入至少一个有效代码")
        return
    code, peers = codes[0], codes[1:]

    if st.sidebar.button("同步数据"):
        _sync_codes(codes)

    with st.spinner("加载公司名称库 (首次约 15s, 之后秒读缓存)..."):
        company_info = CompanyInfo()
        company_info.ensure_loaded()

    with Repository() as repo:
        try:
            _single_company_section(repo, code, company_info)
        except FileNotFoundError as e:
            st.warning(f"{e} — 请先点击「同步数据」")
            return
        _peer_section(repo, codes, period, company_info)
        _ai_section(repo, code, company_info, peers)


if __name__ == "__main__":
    main()
