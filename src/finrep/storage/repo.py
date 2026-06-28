"""数据存储层: Parquet 原始归档 + DuckDB 增量同步状态.

职责 (SRP — 只管存取与元数据, 不含业务计算):
- 标准化报表落地 Parquet (按 report_type 分区, 每股一个文件)
- DuckDB 维护 sync_state 表, 支持增量更新
- 入库前资产负债恒等式校验 (超阈值告警不阻断)
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from ..config import get_settings
from ..fetcher.base import FetchResult

logger = logging.getLogger(__name__)

REPORT_TYPES = ("balance_sheet", "income_statement", "cash_flow")

SYNC_SCHEMA = """
CREATE TABLE IF NOT EXISTS sync_state (
    code        VARCHAR    NOT NULL,
    report_type VARCHAR    NOT NULL,
    source      VARCHAR,
    last_period DATE,
    row_count   INTEGER,
    updated_at  TIMESTAMP,
    PRIMARY KEY (code, report_type)
)
"""


class Repository:
    """本地数据仓库: Parquet 归档 + DuckDB 元数据.

    连接释放: 优先用 `with Repository() as repo:`; __del__ 作为兜底.
    """

    def __init__(self) -> None:
        paths = get_settings()["paths"]
        self.raw_dir = Path(paths["raw_dir"])
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = Path(paths["sync_state"])
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(str(self.db_path))
        self.con.execute(SYNC_SCHEMA)

    def __enter__(self) -> "Repository":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False

    def __del__(self) -> None:
        """GC 兜底释放连接 (不保证调用时机, 仅作最后防线)."""
        try:
            self.con.close()
        except Exception:
            pass

    # ---------------- 写入 ----------------
    def save(self, result: FetchResult) -> Path | None:
        """落地标准化报表到 Parquet + 校验 + 更新同步状态.

        空数据跳过写入返回 None; 其他失败记录日志后向上抛出 (不吞异常).
        """
        if result.data.empty:
            logger.warning("跳过空数据 %s %s", result.code, result.report_type)
            return None
        self._validate_balance_sheet_identity(result)
        path = self._parquet_path(result.code, result.report_type)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            result.data.to_parquet(path, index=False)
        except Exception as e:
            logger.error("Parquet 写入失败 %s %s -> %s: %s",
                         result.code, result.report_type, path, type(e).__name__)
            raise
        lp_ts = result.data["report_date"].max()
        last_period: date | None = lp_ts.date() if pd.notna(lp_ts) else None
        self._upsert_state(result.code, result.report_type, result.source, last_period, len(result.data))
        logger.info("已落地 %s %s (%d 行, 截至 %s)",
                    result.code, result.report_type, len(result.data), last_period or "无")
        return path

    # ---------------- 读取 ----------------
    def load(self, code: str, report_type: str) -> pd.DataFrame:
        """从 Parquet 读取标准化报表."""
        path = self._parquet_path(code, report_type)
        if not path.exists():
            raise FileNotFoundError(f"本地无数据: {code} {report_type} (请先 sync)")
        return pd.read_parquet(path)

    def load_all(self, code: str) -> dict[str, pd.DataFrame]:
        """读取某公司三大报表."""
        return {rt: self.load(code, rt) for rt in REPORT_TYPES}

    def last_period(self, code: str, report_type: str) -> date | None:
        """该公司某报表的最后已同步报告期 (增量同步依据)."""
        row = self.con.execute(
            "SELECT last_period FROM sync_state WHERE code = ? AND report_type = ?",
            [code, report_type],
        ).fetchone()
        return row[0] if row else None

    def synced_codes(self) -> list[str]:
        """已同步的公司代码清单."""
        rows = self.con.execute("SELECT DISTINCT code FROM sync_state ORDER BY code").fetchall()
        return [r[0] for r in rows]

    def close(self) -> None:
        self.con.close()

    # ---------------- 内部 ----------------
    def _parquet_path(self, code: str, report_type: str) -> Path:
        return self.raw_dir / report_type / f"{code}.parquet"

    def _upsert_state(self, code: str, report_type: str, source: str,
                      last_period: date | None, row_count: int) -> None:
        self.con.execute(
            """
            INSERT INTO sync_state (code, report_type, source, last_period, row_count, updated_at)
            VALUES (?, ?, ?, ?, ?, now())
            ON CONFLICT (code, report_type) DO UPDATE SET
                source      = excluded.source,
                last_period = excluded.last_period,
                row_count   = excluded.row_count,
                updated_at  = now()
            """,
            [code, report_type, source, last_period, row_count],
        )

    @staticmethod
    def _validate_balance_sheet_identity(result: FetchResult) -> None:
        """资产负债恒等式校验: |资产 - 负债 - 归母权益 - 少数股东权益| / |总资产| ≤ 阈值."""
        if result.report_type != "balance_sheet" or result.data.empty:
            return
        df = result.data
        required = ("total_assets", "total_liabilities", "parent_equity")
        if not all(c in df.columns for c in required):
            return
        # 少数股东权益缺失时用对齐索引的 0 Series, 避免标量广播歧义
        minority = (
            df["minority_equity"]
            if "minority_equity" in df.columns
            else pd.Series(0, index=df.index, dtype=float)
        )
        err = (df["total_assets"] - df["total_liabilities"] - df["parent_equity"] - minority).abs()
        # 分母取绝对值; 0 替换为 NA 避免除零 (NaN 不计入 bad)
        denom = df["total_assets"].abs().replace(0, pd.NA)
        ratio = err / denom
        threshold = float(get_settings().get("validation", {}).get("balance_identity_threshold", 0.001))
        bad = df[ratio > threshold]
        if not bad.empty:
            logger.warning("资产负债恒等式超阈值 %s: %d 期异常 (阈值 %.3f%%)", result.code, len(bad), threshold * 100)
