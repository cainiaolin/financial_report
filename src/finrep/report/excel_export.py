"""Excel 报告导出: XlsxWriter (多年指标表 + 同业对比表).

异常处理: fail-fast — 数据/IO 错误向上传播, 由调用方统一处理.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from ..analysis import peer_compare
from ..config import get_settings
from ..metrics import compute_metrics
from ..storage import Repository

logger = logging.getLogger(__name__)

_MAX_COL_WIDTH = 40
_COL_WIDTH_SAMPLE = 50


def _autofit(worksheet, df: pd.DataFrame) -> None:
    """按列名与样本值字符宽度自适应列宽."""
    reset = df.reset_index()
    for i, col in enumerate(reset.columns):
        values = reset.iloc[:, i].head(_COL_WIDTH_SAMPLE).tolist()
        max_len = max(len(str(col)), *(len(str(v)) for v in values))
        worksheet.set_column(i, i, min(max_len + 2, _MAX_COL_WIDTH))


def export_excel(code: str, repo: Repository, peers: list[str] | None = None,
                 output: str | Path | None = None) -> Path:
    """导出 Excel: sheet1 单公司多年指标, sheet2 同业对比 (有 peers 时)."""
    metrics_df = compute_metrics(repo.load_all(code))
    if metrics_df.empty:
        raise ValueError("指标数据为空, 无法导出")
    sheets: dict[str, pd.DataFrame] = {"单公司指标": metrics_df}
    if peers:
        sheets["同业对比"] = peer_compare([code] + peers, repo)

    output_path = Path(output) if output else (
        Path(get_settings()["paths"]["reports_dir"]) / "excel" / f"{code}.xlsx"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(output_path, engine="xlsxwriter") as writer:
        for name, df in sheets.items():
            df.to_excel(writer, sheet_name=name)
            if not df.empty:
                _autofit(writer.sheets[name], df)
    logger.info("Excel 报告导出: %s", output_path)
    return output_path
