from __future__ import annotations

from typing import Any, Dict, List, Literal

from .genai_llm import DEFAULT_GENAI_MODEL, build_genai_client
from .llm import (
    DEFAULT_LLM_TEMPERATURE,
    DEFAULT_LLM_MODEL,
    build_openai_client,
    chat_completion as openai_chat_completion,
    disable_proxy_for_localhost,
)


LLMBackend = Literal["openai", "genai"]


def _normalize_model_for_backend(backend: LLMBackend, model: str) -> str:
    if backend == "genai" and (not model or model == DEFAULT_LLM_MODEL):
        return DEFAULT_GENAI_MODEL
    return model


def build_client(
    *,
    backend: LLMBackend,
    base_url: str,
    api_key: str,
    timeout: float,
    model: str,
    temperature: float,
):
    disable_proxy_for_localhost()
    if backend == "genai":
        return build_genai_client(
            api_key=api_key,
            model=_normalize_model_for_backend(backend, model),
        )
    return build_openai_client(base_url=base_url, api_key=api_key, timeout=timeout)


def chat_text(
    *,
    backend: LLMBackend,
    client,
    model: str,
    messages: List[Dict[str, str]],
    temperature: float = DEFAULT_LLM_TEMPERATURE,
    **kwargs: Any,
) -> str:
    model = _normalize_model_for_backend(backend, model)
    if backend == "genai":
        system_parts = [message.get("content", "") for message in messages if message.get("role") == "system"]
        non_system_messages = [message for message in messages if message.get("role") != "system"]
        response = client.models.generate_content(
            model=model,
            contents=non_system_messages,
            system_instruction="\n\n".join(part for part in system_parts if part) or None,
            **kwargs,
        )
        return response.text or ""
    return openai_chat_completion(
        client=client,
        model=model,
        messages=messages,
        temperature=temperature,
        **kwargs,
    )
