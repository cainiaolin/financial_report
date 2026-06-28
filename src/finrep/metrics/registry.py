"""指标元数据注册表: 加载 config/metrics.yaml, 提供 title/unit/direction 查询.

计算逻辑在 calculator.py 显式实现 (安全, 无 eval); registry 仅提供声明式元数据,
供展示层把英文指标名映射为中文标题、单位、方向性.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

# 本文件位于 <root>/src/finrep/metrics/registry.py → parents[3] 为项目根
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_METRICS_FILE = _PROJECT_ROOT / "config" / "metrics.yaml"


@lru_cache(maxsize=1)
def load_metrics_meta() -> dict:
    """加载并缓存 metrics.yaml. 文件缺失或格式错误时 fail-fast."""
    try:
        with _METRICS_FILE.open(encoding="utf-8") as f:
            meta = yaml.safe_load(f)
    except FileNotFoundError as e:
        raise FileNotFoundError(f"指标配置不存在: {_METRICS_FILE}") from e
    except yaml.YAMLError as e:
        raise ValueError(f"指标配置 YAML 格式错误: {e}") from e
    if not isinstance(meta, dict):
        raise ValueError(f"指标配置顶层必须是字典: {_METRICS_FILE}")
    return meta


def get_metric_meta(name: str) -> dict:
    """查询单个指标的元数据 (title/unit/direction/depends)."""
    for m in load_metrics_meta().get("metrics", []):
        if m.get("name") == name:
            return m
    raise KeyError(f"未知指标: {name}")


def list_metrics(category: str | None = None) -> list[dict]:
    """列出指标; 可按 category 过滤 (profitability/operating/solvency/growth/cashflow)."""
    metrics = load_metrics_meta().get("metrics", [])
    return [m for m in metrics if category is None or m.get("category") == category]


def radar_dimensions() -> list[str]:
    """雷达图维度指标名清单."""
    return load_metrics_meta().get("radar_dimensions", [])
