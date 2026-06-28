"""新浪源中文字段 → 标准英文名映射 (基于实探测茅台 600519 三大报表列名).

单位: 新浪源统一为 '元'.
注意: 扣非净利润在三表中无独立字段, 需财务指标接口 (东财恢复/Tushare 接入后补充).
"""
from __future__ import annotations

from typing import Literal

ReportType = Literal["balance_sheet", "income_statement", "cash_flow"]

# 资产负债表 (实探测 147 列, 取核心科目)
BALANCE_SHEET = {
    "报告日": "report_date",
    "货币资金": "monetary_funds",
    "应收票据": "notes_receivable",
    "应收账款": "accounts_receivable",
    "存货": "inventory",
    "流动资产合计": "current_assets",
    "固定资产净额": "fixed_assets",
    "在建工程": "cip",                      # construction in progress
    "无形资产": "intangible_assets",
    "商誉": "goodwill",
    "资产总计": "total_assets",
    "短期借款": "short_term_loan",
    "应付账款": "accounts_payable",
    "流动负债合计": "current_liabilities",
    "一年内到期的非流动负债": "current_portion_lt_debt",
    "长期借款": "long_term_loan",
    "应付债券": "bonds_payable",
    "负债合计": "total_liabilities",
    "归属于母公司股东权益合计": "parent_equity",
    "少数股东权益": "minority_equity",
    "所有者权益(或股东权益)合计": "total_equity",
}

# 利润表 (实探测 83 列)
INCOME_STATEMENT = {
    "报告日": "report_date",
    "营业总收入": "total_revenue",
    "营业收入": "revenue",
    "营业总成本": "total_operate_cost",
    "营业成本": "operating_cost",
    "营业税金及附加": "taxes_surcharge",
    "销售费用": "sell_expense",
    "管理费用": "admin_expense",
    "研发费用": "rd_expense",
    "财务费用": "fin_expense",
    "利息费用": "interest_expense",
    "投资收益": "investment_income",
    "营业利润": "operate_profit",
    "营业外收入": "non_operate_income",
    "营业外支出": "non_operate_expense",
    "利润总额": "total_profit",
    "所得税费用": "income_tax",
    "净利润": "net_profit",
    "归属于母公司所有者的净利润": "net_profit_parent",
    "少数股东损益": "minority_income",
}

# 现金流量表 (实探测 71 列)
CASH_FLOW = {
    "报告日": "report_date",
    "销售商品、提供劳务收到的现金": "sales_cash_received",
    "经营活动现金流入小计": "cffo_inflow",
    "购买商品、接受劳务支付的现金": "goods_cash_paid",
    "支付给职工以及为职工支付的现金": "employee_cash_paid",
    "经营活动产生的现金流量净额": "cffo",
    "购建固定资产、无形资产和其他长期资产所支付的现金": "capex",
    "投资活动产生的现金流量净额": "cffi",
    "取得借款收到的现金": "borrowing_received",
    "偿还债务支付的现金": "debt_repaid",
    "分配股利、利润或偿付利息所支付的现金": "dividend_interest_paid",
    "筹资活动产生的现金流量净额": "cfff",
}

# 报表类型 → 字段映射
REPORT_MAP: dict[str, dict[str, str]] = {
    "balance_sheet": BALANCE_SHEET,
    "income_statement": INCOME_STATEMENT,
    "cash_flow": CASH_FLOW,
}

# 新浪源 stock_financial_report_sina 的 symbol 中文参数名
SINA_REPORT_NAME: dict[str, str] = {
    "balance_sheet": "资产负债表",
    "income_statement": "利润表",
    "cash_flow": "现金流量表",
}
