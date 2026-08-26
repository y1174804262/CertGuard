from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Sequence


try:
    from google import genai
except ImportError:  # pragma: no cover - environment-dependent
    genai = None


DEFAULT_GENAI_MODEL = "gemini-3.5-flash"


@dataclass(frozen=True)
class GenAIConfig:
    api_key: Optional[str] = None
    model: str = DEFAULT_GENAI_MODEL


def _require_google_genai() -> None:
    if sys.version_info < (3, 10):
        raise RuntimeError(
            "google-genai requires Python 3.10+; current interpreter is %d.%d.%d."
            % (sys.version_info.major, sys.version_info.minor, sys.version_info.micro)
        )
    if genai is None:
        raise RuntimeError(
            "google-genai is not installed. Install it in a Python 3.10+ environment "
            "before using the 'genai' backend."
        )


def _to_genai_contents(contents: Any) -> str:
    if isinstance(contents, str):
        return contents
    if isinstance(contents, Sequence) and not isinstance(contents, (str, bytes, bytearray)):
        parts: List[str] = []
        for item in contents:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                role = str(item.get("role") or "").strip()
                content = item.get("content")
                if isinstance(content, list):
                    text_parts = []
                    for block in content:
                        if isinstance(block, dict) and str(block.get("type")) == "text":
                            text_parts.append(str(block.get("text") or ""))
                    rendered = "\n".join(part for part in text_parts if part)
                else:
                    rendered = str(content or "")
                if role:
                    parts.append("%s:\n%s" % (role, rendered))
                elif rendered:
                    parts.append(rendered)
                continue
            parts.append(str(item))
        return "\n\n".join(part for part in parts if part)
    return str(contents)


class _GenAIModelsAdapter:
    def __init__(self, raw_client) -> None:
        self._raw_client = raw_client

    def generate_content(
        self,
        *,
        model: str,
        contents: Any,
        system_instruction: Optional[str] = None,
        **kwargs: Any,
    ) -> SimpleNamespace:
        text = _to_genai_contents(contents)
        if system_instruction:
            text = "System instruction:\n%s\n\nUser content:\n%s" % (system_instruction, text)
        response = self._raw_client.models.generate_content(
            model=model,
            contents=text,
            **kwargs,
        )
        return SimpleNamespace(text=getattr(response, "text", ""), raw_response=response)


class GenAIClient:
    def __init__(self, config: Optional[GenAIConfig] = None) -> None:
        _require_google_genai()
        genai_config = config or GenAIConfig()
        api_key = genai_config.api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError(
                "No API key provided for google-genai. Set GEMINI_API_KEY / GOOGLE_API_KEY "
                "or pass api_key explicitly."
            )
        self.config = genai_config
        self._raw_client = genai.Client(api_key=api_key)
        self.models = _GenAIModelsAdapter(self._raw_client)


def create_genai_client(config: Optional[GenAIConfig] = None) -> GenAIClient:
    return GenAIClient(config=config)


def build_genai_client(
    api_key: Optional[str],
    model: str = DEFAULT_GENAI_MODEL,
) -> GenAIClient:
    return create_genai_client(
        GenAIConfig(
            api_key=api_key,
            model=model,
        )
    )
