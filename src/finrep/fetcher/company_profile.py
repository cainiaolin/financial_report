"""公司业务描述: 巨潮 stock_profile_cninfo 抓主营业务/经营范围/机构简介.

数据源: 巨潮资讯网 cninfo (稳定, ~0.7s). 内容极少变更 → 本地长期缓存.
用于 AI 分析的业务定性素材 (公司是做什么的).
"""
from __future__ import annotations

import logging
from pathlib import Path

import akshare as ak
import pandas as pd

from ..config import get_settings
from .errors import BusinessError

logger = logging.getLogger(__name__)

_PROFILE_KEYS = ("主营业务", "经营范围", "机构简介", "所属行业")


class CompanyProfile:
    """公司业务描述, 带本地 Parquet 缓存 (按 code)."""

    def __init__(self) -> None:
        self.cache_dir = Path(get_settings()["paths"]["sync_state"]).parent
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, dict[str, str]] = {}

    def _cache_path(self, code: str) -> Path:
        return self.cache_dir / f"profile_{code}.parquet"

    def get(self, code: str) -> dict[str, str]:
        """返回 {主营业务, 经营范围, 机构简介, 所属行业}; 命中缓存或抓取."""
        if code in self._cache:
            logger.debug("profile 内存命中 %s", code)
            return self._cache[code]
        path = self._cache_path(code)
        if path.exists():
            logger.debug("profile 磁盘命中 %s", code)
            row = pd.read_parquet(path).iloc[0].to_dict()
            # 仅保留标准字段, 屏蔽旧缓存可能的多余字段
            result = {k: str(row.get(k, "")).strip() for k in _PROFILE_KEYS}
            self._cache[code] = result
            return result
        return self._fetch(code)

    def _fetch(self, code: str) -> dict[str, str]:
        try:
            df = ak.stock_profile_cninfo(symbol=code)
        except Exception as e:  # noqa: BLE001
            raise BusinessError(f"巨潮 profile 抓取失败 {code}: {type(e).__name__}") from e
        if df is None or df.empty:
            raise BusinessError(f"巨潮 profile 无数据 {code}")
        row = df.iloc[0].to_dict()
        result = {k: str(row.get(k, "")).strip() for k in _PROFILE_KEYS}
        # 字段全部为空 → 数据源字段可能变更, fail-fast
        if not any(result.values()):
            raise BusinessError(f"巨潮 profile 字段全部为空 {code} (接口字段可能变更, 请检查)")
        self._cache[code] = result
        pd.DataFrame([result]).to_parquet(self._cache_path(code), index=False)
        logger.info("公司 profile 抓取成功 %s", code)
        return result

    def text(self, code: str) -> str:
        """拼接业务描述文本 (供 AI 分析)."""
        profile = self.get(code)
        parts = [
            f"主营业务: {profile['主营业务']}",
            f"经营范围: {profile['经营范围']}",
            f"机构简介: {profile['机构简介']}",
        ]
        if profile.get("所属行业"):
            parts.append(f"所属行业: {profile['所属行业']}")
        return "\n".join(parts)
