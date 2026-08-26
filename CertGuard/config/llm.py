from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx
from openai import OpenAI


# DEFAULT_LLM_BASE_URL = "http://localhost:2166/v1"
# DEFAULT_LLM_API_KEY = "dummy"
# DEFAULT_LLM_MODEL = "modelscope-router"
# DEFAULT_LLM_TIMEOUT = 120.0
# DEFAULT_LLM_TEMPERATURE = 0.0

DEFAULT_LLM_BASE_URL = "https://api.siliconflow.cn/v1"
DEFAULT_LLM_API_KEY = "sk-vcbgcrxpzuffndhwvopcwjmamizfxknqygmfajeoqxraidcw"
DEFAULT_LLM_MODEL = "deepseek-ai/DeepSeek-R1-0528-Qwen3-8B"
DEFAULT_LLM_TIMEOUT = 120.0
DEFAULT_LLM_TEMPERATURE = 0.0


@dataclass(frozen=True)
class LLMConfig:
    base_url: str = DEFAULT_LLM_BASE_URL
    api_key: str = DEFAULT_LLM_API_KEY
    model: str = DEFAULT_LLM_MODEL
    timeout: float = DEFAULT_LLM_TIMEOUT
    temperature: float = DEFAULT_LLM_TEMPERATURE


def disable_proxy_for_localhost() -> None:
    no_proxy_values = ["localhost", "127.0.0.1", "::1"]
    existing = os.environ.get("NO_PROXY") or os.environ.get("no_proxy")
    if existing:
        no_proxy_values.insert(0, existing)
    value = ",".join(no_proxy_values)
    os.environ["NO_PROXY"] = value
    os.environ["no_proxy"] = value


def create_llm_client(config: Optional[LLMConfig] = None) -> OpenAI:
    llm_config = config or LLMConfig()
    disable_proxy_for_localhost()
    http_client = httpx.Client(trust_env=False, timeout=llm_config.timeout)
    return OpenAI(
        api_key=llm_config.api_key,
        base_url=llm_config.base_url,
        http_client=http_client,
        max_retries=0,
    )


def build_openai_client(base_url: str, api_key: str, timeout: float) -> OpenAI:
    return create_llm_client(
        LLMConfig(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
        )
    )


def chat_completion(
    client: OpenAI,
    model: str,
    messages: List[Dict[str, str]],
    temperature: float = DEFAULT_LLM_TEMPERATURE,
    **kwargs: Any,
) -> str:
    response = client.chat.completions.create(
        model=model,
        temperature=temperature,
        messages=messages,
        **kwargs,
    )
    return response.choices[0].message.content or ""
