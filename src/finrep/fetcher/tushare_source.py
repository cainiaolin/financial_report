"""Tushare Pro 备选源 (需 5000 积分 token, 用于双源交叉校验).

接口: pro.balancesheet/income/cashflow(ts_code='600519.SH')
字段为 Tushare 英文缩写, 通过 _field_mapping 覆盖为标准名.
"""
from __future__ import annotations

import logging

import pandas as pd
import tushare as ts

from .base import FetcherBase, ReportType
from .errors import BusinessError, NetworkError, RateLimitError
from .retry import fetch_retry

logger = logging.getLogger(__name__)

TUSHARE_API = {
    "balance_sheet": "balancesheet",
    "income_statement": "income",
    "cash_flow": "cashflow",
}

# Tushare 英文字段 → 标准名 (覆盖基类的中文映射)
TUSHARE_MAP: dict[str, dict[str, str]] = {
    "balance_sheet": {
        "end_date": "report_date",
        "total_assets": "total_assets",
        "total_liab": "total_liabilities",
        "total_cur_assets": "current_assets",
        "total_cur_liab": "current_liabilities",
        "inventory": "inventory",
        "accounts_rece": "accounts_receivable",
        "goodwill": "goodwill",
        "st_borrow": "short_term_loan",
        "lt_borrow": "long_term_loan",
        "total_hldr_eqy_exc_min_int": "parent_equity",
        "total_hldr_eqy_inc_min_int": "total_equity",
    },
    "income_statement": {
        "end_date": "report_date",
        "total_revenue": "total_revenue",
        "revenue": "revenue",
        "oper_cost": "operating_cost",
        "sell_exp": "sell_expense",
        "admin_exp": "admin_expense",
        "rd_exp": "rd_expense",
        "fin_exp": "fin_expense",
        "operate_profit": "operate_profit",
        "total_profit": "total_profit",
        "income_tax": "income_tax",
        "n_income": "net_profit",
        "n_income_attr_p": "net_profit_parent",
        "minority_int": "minority_income",
    },
    "cash_flow": {
        "end_date": "report_date",
        "n_cashflow_act": "cffo",
        "c_fr_sale_sg": "sales_cash_received",
        "c_pay_acq_const_fiolta": "capex",
    },
}


class TushareFetcher(FetcherBase):
    """Tushare 备源 — 仅在 token 配置后可用. _api 为实例属性避免多实例竞态."""
    source_name = "tushare"

    def __init__(self) -> None:
        from ..config import get_settings
        token = get_settings().get("sources", {}).get("tushare", {}).get("token", "")
        if not token:
            raise BusinessError("Tushare token 未配置 (请在 .env 设 TUSHARE_TOKEN 或系统环境变量)")
        ts.set_token(token)
        self._api = ts.pro_api()                    # 实例属性, 避免类属性竞态

    def _field_mapping(self, report_type: ReportType) -> dict[str, str]:
        if report_type not in TUSHARE_MAP:
            raise ValueError(f"不支持的报表类型: {report_type}")
        return TUSHARE_MAP[report_type]

    @fetch_retry
    def _fetch_raw(self, code6: str, report_type: ReportType) -> pd.DataFrame:
        from .codes import to_ts_code
        ts_code = to_ts_code(code6)
        api_name = TUSHARE_API[report_type]
        try:
            df = getattr(self._api, api_name)(ts_code=ts_code)
        except Exception as e:
            etype = type(e).__name__               # 脱敏: 只记异常类型
            msg = str(e).lower()
            name = etype.lower()
            if any(k in msg for k in ("频率", "每天", "上限", "积分", "permission", "limit")):
                raise RateLimitError(f"tushare 限频/权限 {code6}: {etype}") from e
            if any(k in name for k in ("connection", "timeout")):
                raise NetworkError(f"tushare 连接失败 {code6}: {etype}") from e
            raise BusinessError(f"tushare 抓取失败 {code6}: {etype}") from e
        if df is None or len(df) == 0:
            raise BusinessError(f"tushare 无数据 {code6} {report_type}")
        logger.info("tushare 抓取成功 %s %s: %d 行", code6, report_type, len(df))
        return df
