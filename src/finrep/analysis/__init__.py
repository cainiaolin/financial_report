"""分析对比层: 单公司趋势 + 同业横向对比."""
from .peer import peer_compare
from .trend import trend_summary

__all__ = ["peer_compare", "trend_summary"]
