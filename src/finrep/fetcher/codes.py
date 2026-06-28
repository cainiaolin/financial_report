"""证券代码工具: 统一内部用 6 位纯数字代码, 按需转换为各数据源格式."""
from __future__ import annotations

from typing import Literal


def normalize_code(code: str) -> str:
    """各种格式 → 6 位纯数字.

    例: 'SH600519' / '600519.SH' / 'sh600519' / '600519' → '600519'.
    """
    c = code.strip().upper()
    # 先去交易所后缀 (600519.SH)
    for ext in (".SH", ".SZ", ".BJ"):
        if c.endswith(ext):
            c = c[:-3]
            break
    # 再去交易所前缀 (SH600519 / SZ000895)
    for prefix in ("SH", "SZ", "BJ"):
        if c.startswith(prefix) and c[len(prefix):].isdigit():
            c = c[len(prefix):]
            break
    if not c.isdigit():
        raise ValueError(f"无效的证券代码: {code!r}")
    return c.zfill(6)


def exchange_of(code6: str) -> Literal["SH", "SZ", "BJ"]:
    """6 位代码 → 交易所. 沪: 60/68/90; 深: 00/30/20; 京: 43/83/87/88/92."""
    if code6.startswith(("60", "68", "90")):
        return "SH"
    if code6.startswith(("00", "30", "20")):
        return "SZ"
    if code6.startswith(("43", "83", "87", "88", "92")):
        return "BJ"
    raise ValueError(f"无法识别交易所: {code6}")


def to_ak_sina(stock_code: str) -> str:
    """新浪源格式: sh600519 (小写交易所前缀 + 6 位)."""
    c = normalize_code(stock_code)
    return f"{exchange_of(c).lower()}{c}"


def to_ts_code(stock_code: str) -> str:
    """Tushare 格式: 600519.SH."""
    c = normalize_code(stock_code)
    return f"{c}.{exchange_of(c)}"
