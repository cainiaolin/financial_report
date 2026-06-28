"""配置加载: .env 注入 + settings.yaml 读取, 支持 ${VAR} 占位符.

设计:
- 纯标准库解析 .env (含引号剥离与行内注释), 不依赖 python-dotenv (KISS, 减依赖).
- 敏感凭证(token)只从环境变量读取, 绝不硬编码 (安全规范).
- fail-fast: 配置文件缺失或 YAML 格式错误时立即抛出明确异常, 不静默吞错.
- get_settings() 进程内缓存: 启动加载一次, CLI 单次运行 / Streamlit 长进程均适用.
"""
from __future__ import annotations

import logging
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_ENV_VAR_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _validate_project_root() -> Path:
    """定位项目根目录 (本文件位于 <root>/src/finrep/config.py) 并验证 config 目录存在."""
    root = Path(__file__).resolve().parents[2]
    if not (root / "config").is_dir():
        raise FileNotFoundError(f"项目 config 目录不存在: {root / 'config'}")
    return root


_PROJECT_ROOT = _validate_project_root()


def load_env(env_path: Path | None = None) -> None:
    """从 .env 加载环境变量到 os.environ (系统变量优先, 但空值时用 .env 覆盖).

    解析规则: 跳过空行与 # 注释行; 引号包裹值保留内部内容(含 #); 否则剥离 ' #' 行内注释.
    """
    path = env_path or (_PROJECT_ROOT / ".env")
    if not path.exists():
        logger.debug(".env 不存在, 跳过环境变量加载: %s", path)
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # 引号包裹 → 去成对引号, 保留内部内容; 否则剥离 ' #' 行内注释
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        # 系统环境变量优先; 但若已存在空值, 用 .env 覆盖 (避免空变量阻止 .env 生效)
        if not os.environ.get(key):
            os.environ[key] = value


def _expand(value: Any, missing: list[str]) -> Any:
    """递归把 ${VAR} 替换为环境变量值.

    单层语义: 环境变量的值作为字面量, 不对其内部再次展开 ${}, 因此不存在循环引用风险.
    缺失变量记入 missing 并替换为空串, 同时记录 warning 日志.
    """
    if isinstance(value, str):
        def _sub(match: re.Match[str]) -> str:
            var = match.group(1)
            val = os.environ.get(var)
            if val is None:
                missing.append(var)
                logger.warning("环境变量未配置, 占位符替换为空串: %s", var)
                return ""
            return val
        return _ENV_VAR_PATTERN.sub(_sub, value)
    if isinstance(value, dict):
        return {k: _expand(v, missing) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v, missing) for v in value]
    return value


@lru_cache(maxsize=1)
def get_settings() -> dict[str, Any]:
    """加载并缓存 settings.yaml, 注入环境变量. 缺失的占位符变量记入 _missing_vars."""
    load_env()
    config_path = _PROJECT_ROOT / "config" / "settings.yaml"
    try:
        with config_path.open(encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except FileNotFoundError as e:
        raise FileNotFoundError(f"配置文件不存在: {config_path}") from e
    except yaml.YAMLError as e:
        raise ValueError(f"配置文件 YAML 格式错误: {config_path}\n{e}") from e
    if not isinstance(raw, dict):
        raise ValueError(f"配置文件顶层必须是字典: {config_path}")
    missing: list[str] = []
    settings = _expand(raw, missing)
    settings["_missing_vars"] = missing
    logger.info("配置加载完成 (缺失变量: %s)", missing or "无")
    return settings


def is_tushare_configured() -> bool:
    """Tushare token 是否就绪 — 从 settings 读取 (进程启动时加载 .env, 运行时改 env 需重启进程)."""
    token = get_settings().get("sources", {}).get("tushare", {}).get("token", "")
    return bool(token)
