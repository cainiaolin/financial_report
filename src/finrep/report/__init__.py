"""报告导出: HTML (Jinja2 + 图表) + Excel (XlsxWriter)."""
from .excel_export import export_excel
from .html_export import render_report

__all__ = ["render_report", "export_excel"]
