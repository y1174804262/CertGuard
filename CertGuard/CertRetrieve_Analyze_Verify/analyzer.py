from __future__ import annotations

import json
import os
import re
import hashlib
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from CertGuard.config.llm_backend import build_client, chat_text
from CertGuard.CertGraph_RFC2Certificate.llm_utils import disable_proxy_for_localhost
from CertGuard.project_documents.json_store import read_json, write_json

from .models import ContextChunk
from .prompts import ANALYZER_SYSTEM_PROMPTS, build_analyzer_user_prompt


def run_chunk_analysis(
    chunks: Sequence[ContextChunk],
    mode: str,
    base_url: str,
    api_key: str,
    model: str,
    backend: str,
    timeout: float,
    temperature: float,
    cache_dir: str,
    force: bool = False,
) -> List[Dict[str, Any]]:
    os.makedirs(cache_dir, exist_ok=True)
    disable_proxy_for_localhost()
    client = build_client(
        backend=backend,
        base_url=base_url,
        api_key=api_key,
        timeout=timeout,
        model=model,
        temperature=temperature,
    )
    results: List[Dict[str, Any]] = []

    for chunk in chunks:
        artifact_path = os.path.join(cache_dir, "%s.json" % chunk.chunk_id)
        system_prompt = ANALYZER_SYSTEM_PROMPTS[mode]
        user_prompt = build_analyzer_user_prompt(chunk.node_id, chunk)
        context_fingerprint = _chunk_fingerprint(chunk)
        prompt_fingerprint = _prompt_fingerprint(system_prompt, user_prompt)
        if not force and os.path.exists(artifact_path):
            cached = read_json(artifact_path)
            if (
                cached.get("context_fingerprint") == context_fingerprint
                and cached.get("prompt_fingerprint") == prompt_fingerprint
            ):
                results.append(cached)
                continue

        raw_response = chat_text(
            backend=backend,
            client=client,
            model=model,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        ) or '{"problems":[],"overall_note":""}'
        parse_error = None
        try:
            parsed = _parse_analyzer_response(raw_response, chunk, mode)
        except Exception as exc:
            parse_error = "%s: %s" % (exc.__class__.__name__, exc)
            parsed = {
                "problems": [],
                "overall_note": "Analyzer response could not be parsed as valid JSON: %s" % parse_error,
            }
        artifact = {
            "chunk_id": chunk.chunk_id,
            "node_id": chunk.node_id,
            "mode": mode,
            "model": model,
            "processed_at": _utc_now(),
            "context_fingerprint": context_fingerprint,
            "prompt_fingerprint": prompt_fingerprint,
            "prompt": {
                "system": system_prompt,
                "user": user_prompt,
            },
            "raw_response": raw_response,
            "parsed": parsed,
        }
        if parse_error:
            artifact["parse_error"] = parse_error
        write_json(artifact_path, artifact)
        results.append(artifact)

    return results


def _parse_analyzer_response(content: str, chunk: ContextChunk, mode: str) -> Dict[str, Any]:
    data = json.loads(_extract_json_object(content))
    if not isinstance(data, dict):
        raise ValueError("Analyzer output must be a JSON object.")

    allowed_ids = set(chunk.paragraph_map().keys())
    problems: List[Dict[str, Any]] = []
    seen = set()

    for problem in data.get("problems") or []:
        if not isinstance(problem, dict):
            continue
        title = str(problem.get("title") or "").strip()
        reason = str(problem.get("reason") or "").strip()
        paragraph_ids = []
        for paragraph_id in problem.get("paragraph_ids") or []:
            if not isinstance(paragraph_id, str):
                continue
            if paragraph_id not in allowed_ids:
                continue
            if paragraph_id not in paragraph_ids:
                paragraph_ids.append(paragraph_id)
        if not title or not reason or not paragraph_ids:
            continue
        if mode == "cross_document":
            document_count = len({chunk.paragraph_map()[paragraph_id].document_key for paragraph_id in paragraph_ids})
            if document_count < 2:
                continue
        if not title or not reason or not paragraph_ids:
            continue
        dedupe_key = (title.lower(), tuple(paragraph_ids))
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        problems.append(
            {
                "title": title,
                "paragraph_ids": paragraph_ids,
                "reason": reason,
            }
        )

    overall_note = data.get("overall_note")
    if overall_note is not None and not isinstance(overall_note, str):
        overall_note = str(overall_note)

    return {
        "problems": problems,
        "overall_note": overall_note or "",
    }


def _extract_json_object(content: str) -> str:
    stripped = content.strip()
    fence_match = re.search(r"```(?:json)?\s*(.*?)```", stripped, re.IGNORECASE | re.DOTALL)
    if fence_match:
        stripped = fence_match.group(1).strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        return stripped[start : end + 1]
    raise ValueError("No JSON object found in analyzer response.")


def _utc_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _chunk_fingerprint(chunk: ContextChunk) -> str:
    payload = json.dumps(chunk.to_dict(), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _prompt_fingerprint(system_prompt: str, user_prompt: str) -> str:
    payload = json.dumps(
        {"system": system_prompt, "user": user_prompt},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
