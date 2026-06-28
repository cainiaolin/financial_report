"""数据获取层: 数据源 + 公司名称."""
from .company_info import CompanyInfo
from .manager import FetcherManager

__all__ = ["CompanyInfo", "FetcherManager"]
