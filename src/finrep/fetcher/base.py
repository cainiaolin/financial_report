"""数据获取层抽象基类与数据模型 (DIP: 上层依赖抽象, 不依赖具体数据源)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import pandas as pd

from .field_map import REPORT_MAP, ReportType


@dataclass
class FetchRequest:
    """单次抓取请求."""
    code: str                                   # 任意格式代码, 内部会 normalize
    report_type: ReportType


@dataclass
class FetchResult:
    """标准化抓取结果 (统一英文字段名 + 单位:元)."""
    code: str                                   # 6 位标准代码
    report_type: ReportType
    source: str                                 # 'sina' / 'tushare'
    data: pd.DataFrame
    rows: int = field(init=False)

    def __post_init__(self) -> None:
        self.rows = len(self.data)


class FetcherBase(ABC):
    """数据源抽象 — 模板方法: fetch() 编排, 子类实现 _fetch_raw() 与可选 _field_mapping().

    标准化逻辑(字段重命名/数值清洗/排序)在基类复用, 各源只提供自己的映射表 (DRY).
    """
    source_name: str = "base"

    def fetch(self, request: FetchRequest) -> FetchResult:
        from .codes import normalize_code
        code6 = normalize_code(request.code)
        raw = self._fetch_raw(code6, request.report_type)
        mapping = self._field_mapping(request.report_type)
        standardized = self._standardize(raw, mapping)
        return FetchResult(
            code=code6,
            report_type=request.report_type,
            source=self.source_name,
            data=standardized,
        )

    @abstractmethod
    def _fetch_raw(self, code6: str, report_type: ReportType) -> pd.DataFrame:
        """子类实现: 调用具体数据源, 返回原始 DataFrame."""

    def _field_mapping(self, report_type: ReportType) -> dict[str, str]:
        """源特定字段映射 → 标准名. 默认新浪中文映射, 其他源可覆盖."""
        if report_type not in REPORT_MAP:
            raise ValueError(f"不支持的报表类型: {report_type}")
        return REPORT_MAP[report_type]

    @staticmethod
    def _standardize(raw: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
        """字段重命名 + report_date 解析 + 数值清洗 + 按报告期升序."""
        available = {k: v for k, v in mapping.items() if k in raw.columns}
        if not available:
            raise ValueError("原始数据无可映射字段")
        df = raw[list(available)].rename(columns=available).copy()
        if "report_date" in df.columns:
            df["report_date"] = pd.to_datetime(df["report_date"], errors="coerce")
            df = df.dropna(subset=["report_date"]).sort_values("report_date").reset_index(drop=True)
        for col in df.columns:
            if col == "report_date":
                continue
            if df[col].dtype == object:
                df[col] = df[col].astype(str).str.replace(",", "", regex=False)
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df
