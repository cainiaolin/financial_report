"""年报 MD&A 抓取: 巨潮公告→cninfo PDF 直链→下载→pdfplumber 抽取→定位 MD&A.

链路 (均已验证):
1. ak.stock_zh_a_disclosure_report_cninfo 拿年报公告列表 + 详情页链接
2. 从链接解析 announcementId + announcementTime, 构造 PDF 直链
   static.cninfo.com.cn/finalpage/{time}/{id}.PDF
3. requests 下载, pdfplumber 抽全文
4. 定位「经营情况讨论与分析」章节 → 下一节边界, 截取 MD&A
缓存: data/annual_reports/{code}_{year}.txt (年报每年一次, 永不重抓).
"""
from __future__ import annotations

import io
import logging
import re
from pathlib import Path

import akshare as ak
import pdfplumber
import requests

from ..config import get_settings
from .errors import BusinessError

logger = logging.getLogger(__name__)

_MAX_MDA_CHARS = 30000
_PDF_TIMEOUT = 60
_HEADERS = {"User-Agent": "Mozilla/5.0"}
_PDF_URL = "http://static.cninfo.com.cn/finalpage/{date}/{aid}.PDF"


class AnnualReport:
    """年报 MD&A 抓取与文本缓存."""

    def __init__(self) -> None:
        self.cache_dir = Path(get_settings()["paths"]["annual_reports"])
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, code: str, year: int) -> Path:
        return self.cache_dir / f"{code}_{year}.txt"

    def get_mda(self, code: str, year: int | None = None) -> dict:
        """返回 {year, title, mda_text}; 命中缓存或抓取."""
        listing = self._list_annual_reports(code)
        chosen = self._pick(listing, year)
        rep_year = chosen["year"]
        path = self._cache_path(code, rep_year)
        if path.exists():
            logger.info("年报磁盘命中 %s %d", code, rep_year)
            mda = path.read_text(encoding="utf-8")
        else:
            mda = self._fetch_and_extract(chosen)
            path.write_text(mda, encoding="utf-8")
        return {"year": rep_year, "title": chosen["title"], "mda_text": mda}

    def _list_annual_reports(self, code: str) -> list[dict]:
        try:
            df = ak.stock_zh_a_disclosure_report_cninfo(
                symbol=code, market="沪深京", category="年报",
                start_date="20200101", end_date="20261231",
            )
        except Exception as e:  # noqa: BLE001
            raise BusinessError(f"巨潮年报列表抓取失败 {code}: {type(e).__name__}") from e
        if df is None or df.empty:
            raise BusinessError(f"巨潮无年报公告 {code}")
        reports: list[dict] = []
        for _, row in df.iterrows():
            title = str(row.get("公告标题", ""))
            # 排除英文版/摘要, 只留年度报告正文
            if "年度报告" in title and "英文" not in title and "摘要" not in title:
                # 锚定"年度报告"前的年份, 避免误匹配标题里其他数字; 范围校验
                year_m = re.search(r"(\d{4})\s*年?\s*年度报告", title)
                year = int(year_m.group(1)) if year_m else 0
                if year < 2000 or year > 2100:
                    logger.warning("跳过无效年份年报: %s", title)
                    continue
                reports.append({
                    "title": title,
                    "time": str(row.get("公告时间", "")),
                    "link": str(row.get("公告链接", "")),
                    "year": year,
                })
        if not reports:
            raise BusinessError(f"未筛选到年报正文 {code}")
        return reports

    def _pick(self, reports: list[dict], year: int | None) -> dict:
        if year:
            for r in reports:
                if r["year"] == year:
                    return r
        # 默认最新 (按公告时间降序)
        return sorted(reports, key=lambda r: r["time"], reverse=True)[0]

    @staticmethod
    def _parse_link(link: str) -> tuple[str, str]:
        """从详情页 URL 提取 announcementId 与公告日期 (YYYY-MM-DD)."""
        aid = re.search(r"announcementId=(\d+)", link)
        date = re.search(r"announcementTime=(\d{4}-\d{2}-\d{2})", link)
        if not aid or not date:
            raise BusinessError(f"无法解析公告链接: {link}")
        return aid.group(1), date.group(1)

    def _fetch_and_extract(self, report: dict) -> str:
        aid, date = self._parse_link(report["link"])
        url = _PDF_URL.format(date=date, aid=aid)
        logger.info("下载年报 PDF: %s", url)
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=_PDF_TIMEOUT)
        except requests.RequestException as e:
            raise BusinessError(f"PDF 下载失败: {type(e).__name__}") from e
        if resp.status_code != 200:
            raise BusinessError(f"PDF 下载 HTTP {resp.status_code}")
        full = self._extract_text(resp.content)
        mda = self._extract_mda(full)
        logger.info("MD&A 抽取: 全文 %d 字 → MD&A %d 字", len(full), len(mda))
        return mda

    @staticmethod
    def _extract_text(pdf_bytes: bytes) -> str:
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                pages = [p.extract_text() or "" for p in pdf.pages]
        except Exception as e:  # noqa: BLE001
            raise BusinessError(f"PDF 解析失败: {type(e).__name__}") from e
        return "\n".join(pages)

    @staticmethod
    def _extract_mda(full_text: str, max_chars: int = _MAX_MDA_CHARS) -> str:
        """定位「经营情况讨论与分析」章节到下一节边界."""
        anchor = "经营情况讨论与分析"
        idx = full_text.find(anchor)
        if idx < 0:
            logger.warning("未定位 MD&A 锚点, 取全文前 %d 字", max_chars)
            return full_text[:max_chars]
        boundary = -1
        for kw in ("第五节", "重要事项", "监事会"):
            b = full_text.find(kw, idx + len(anchor))
            if b > 0:
                boundary = b
                break
        end = boundary if boundary > idx else min(idx + max_chars, len(full_text))
        return full_text[idx:end]
