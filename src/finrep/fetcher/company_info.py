"""公司名称映射: 从沪深交易所源获取 code→name, 本地缓存.

数据源: ak.stock_info_sh_name_code (沪市主板+科创板) + ak.stock_info_sz_name_code (深市).
交易所源稳定且快 (~0s), 替代当前不可用的东财 stock_individual_info_em.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from ..config import get_settings
from .errors import BusinessError

logger = logging.getLogger(__name__)


class CompanyInfo:
    """股票代码 → 名称映射, 带本地 Parquet 缓存."""

    def __init__(self) -> None:
        self.cache_path = Path(get_settings()["paths"]["sync_state"]).parent / "company_names.parquet"
        self._map: dict[str, str] = self._load_cache()

    def _load_cache(self) -> dict[str, str]:
        if not self.cache_path.exists():
            return {}
        df = pd.read_parquet(self.cache_path)
        return dict(zip(df["code"].astype(str), df["name"]))

    def ensure_loaded(self) -> None:
        """首次使用时懒加载 (缓存不存在则抓取)."""
        if not self._map:
            self.refresh()

    def refresh(self) -> None:
        """从交易所源重新抓取全市场 code→name 并落盘."""
        import akshare as ak

        frames: list[pd.DataFrame] = []
        # 沪市: 主板A股 + 科创板
        for sym in ("主板A股", "科创板"):
            try:
                df = ak.stock_info_sh_name_code(symbol=sym)
                frames.append(pd.DataFrame({
                    "code": df["证券代码"].astype(str).str.zfill(6),
                    "name": df["证券简称"].astype(str).str.strip(),
                }))
            except Exception as e:  # noqa: BLE001
                logger.warning("sh %s 抓取失败: %s", sym, type(e).__name__)
        # 深市: A股列表 (主板+创业板)
        try:
            df = ak.stock_info_sz_name_code(symbol="A股列表")
            frames.append(pd.DataFrame({
                "code": df["A股代码"].astype(str).str.zfill(6),
                "name": df["A股简称"].astype(str).str.strip(),
            }))
        except Exception as e:  # noqa: BLE001
            logger.warning("sz 抓取失败: %s", type(e).__name__)

        if not frames:
            raise BusinessError("股票名称抓取全部失败 (沪深交易所源均不可用)")
        full = pd.concat(frames, ignore_index=True).drop_duplicates(subset="code", keep="first")
        self._map = dict(zip(full["code"], full["name"]))
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        full.to_parquet(self.cache_path, index=False)
        logger.info("公司名称缓存刷新: %d 只", len(full))

    def get(self, code: str) -> str:
        """取公司名称; 未命中返回代码本身."""
        self.ensure_loaded()
        return self._map.get(str(code).zfill(6), str(code))

    def label(self, code: str) -> str:
        """格式化: '600519 贵州茅台'; 无名称则仅代码."""
        name = self.get(code)
        return f"{code} {name}" if name and name != str(code) else str(code)
