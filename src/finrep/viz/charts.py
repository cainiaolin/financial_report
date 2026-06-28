"""pyecharts 图表封装: 趋势折线 / 同业雷达 / 对比柱状.

所有函数返回 pyecharts Chart 对象, 由展示层 (app/report) 负责渲染.
数据来源于 metrics/analysis 的输出, 本模块不含计算逻辑 (SRP).
"""
from __future__ import annotations

from typing import Iterable

import pandas as pd
from pyecharts import options as opts
from pyecharts.charts import Bar, Line, Radar

from ..metrics.registry import get_metric_meta


def metric_title(metric: str) -> str:
    """指标英文 → 中文标题 (未知则原样)."""
    try:
        return get_metric_meta(metric).get("title", metric)
    except KeyError:
        return metric


def trend_line_chart(metrics_df: pd.DataFrame, metric: str, height: str = "380px") -> Line:
    """某指标随报告期变化的趋势折线图."""
    df = metrics_df.sort_values("report_date")
    title = metric_title(metric)
    x_axis = [d.strftime("%Y-%m") for d in df["report_date"]]
    y_axis = [None if pd.isna(v) else round(float(v), 2) for v in df[metric]]
    return (
        Line(init_opts=opts.InitOpts(height=height))
        .add_xaxis(x_axis)
        .add_yaxis(title, y_axis, is_connect_nones=True, symbol="circle", symbol_size=6)
        .set_global_opts(
            title_opts=opts.TitleOpts(title=f"{title} 趋势"),
            tooltip_opts=opts.TooltipOpts(trigger="axis"),
            datazoom_opts=[opts.DataZoomOpts(type_="inside")],
        )
    )


def peer_radar_chart(peer_df: pd.DataFrame, dimensions: Iterable[str], height: str = "420px") -> Radar:
    """多公司雷达图: 各维度取百分位 (_pct 列), 标准化到 0-100. 缺失维度自动跳过."""
    available: list[tuple[str, str]] = []
    for d in dimensions:
        col = f"{d}_pct" if f"{d}_pct" in peer_df.columns else d
        if col in peer_df.columns:
            available.append((d, col))
    schema = [opts.RadarIndicatorItem(name=metric_title(d), max_=100) for d, _ in available]
    radar = Radar(init_opts=opts.InitOpts(height=height))
    radar.add_schema(schema=schema)
    for code in peer_df.index:
        values = [
            0.0 if pd.isna(peer_df.loc[code, col]) else round(float(peer_df.loc[code, col]), 1)
            for _, col in available
        ]
        radar.add(str(code), [values], areastyle_opts=opts.AreaStyleOpts(opacity=0.15))
    radar.set_global_opts(title_opts=opts.TitleOpts(title="同业雷达 (百分位)"))
    return radar


def peer_bar_chart(peer_df: pd.DataFrame, metric: str, height: str = "380px") -> Bar:
    """某指标的多公司对比柱状图."""
    title = metric_title(metric)
    codes = [str(c) for c in peer_df.index]
    values = [0.0 if pd.isna(v) else round(float(v), 2) for v in peer_df[metric]]
    return (
        Bar(init_opts=opts.InitOpts(height=height))
        .add_xaxis(codes)
        .add_yaxis(title, values)
        .set_global_opts(title_opts=opts.TitleOpts(title=f"{title} 对比"))
    )
