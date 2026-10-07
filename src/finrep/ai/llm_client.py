"""LLM 客户端: OpenAI 兼容接口, 按 config 在 GLM(智谱)/DeepSeek 间切换.

两者均完全兼容 OpenAI SDK, 只需 base_url + api_key + model 名不同.
- 重试: 依赖 OpenAI SDK 内置 max_retries (连接错误/429/5xx 自动退避, 无需 tenacity)
- 异常: API 错误向上传播, 由调用方(Streamlit/CLI)统一处理 (fail-fast, 不吞异常)
- 流式: chat_stream 供 st.write_stream 实时显示
"""
from __future__ import annotations

import logging
from collections.abc import Iterator

from openai import OpenAI

from ..config import get_settings

logger = logging.getLogger(__name__)

_DEFAULT_TEMPERATURE = 0.3
_DEFAULT_MAX_TOKENS = 4096
_MAX_RETRIES = 3
_KEY_ENV = {"glm": "ZHIPU_API_KEY", "deepseek": "DEEPSEEK_API_KEY"}


class LLMClient:
    """统一 LLM 客户端: 构造时确定 provider, 复用 OpenAI 兼容连接."""

    def __init__(self, provider: str | None = None) -> None:
        ai = get_settings().get("ai", {})
        self.provider = provider or ai.get("provider", "glm")
        cfg = ai.get(self.provider)
        if not cfg:                              # provider 配置缺失 → 回退 glm
            self.provider = "glm"
            cfg = ai.get("glm", {})
        api_key = cfg.get("api_key", "")
        if not api_key:
            env = _KEY_ENV.get(self.provider, "ZHIPU_API_KEY")
            raise ValueError(f"{self.provider} API key 未配置 (请在 .env 设 {env})")
        base_url = cfg.get("base_url")
        if not base_url:
            raise ValueError(f"{self.provider} base_url 未配置")
        self.model = cfg.get("model", "glm-4.5-air")
        self.client = OpenAI(api_key=api_key, base_url=base_url, max_retries=_MAX_RETRIES)
        self.temperature = float(ai.get("temperature", _DEFAULT_TEMPERATURE))
        self.max_tokens = int(ai.get("max_tokens", _DEFAULT_MAX_TOKENS))
        logger.info("LLM 客户端就绪: provider=%s model=%s", self.provider, self.model)

    def chat_stream(self, system: str, user: str) -> Iterator[str]:
        """流式输出, yield 文本片段 (供 st.write_stream)."""
        self._validate_input(system, user)
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            stream=True,
        )
        for chunk in resp:
            if not chunk.choices:
                continue
            text = getattr(chunk.choices[0].delta, "content", None)
            if text:
                yield text

    def chat(self, system: str, user: str) -> str:
        """非流式, 返回完整文本."""
        return "".join(self.chat_stream(system, user))

    @staticmethod
    def _validate_input(system: str, user: str) -> None:
        if not system or not system.strip():
            raise ValueError("system prompt 不能为空")
        if not user or not user.strip():
            raise ValueError("user 内容不能为空")
