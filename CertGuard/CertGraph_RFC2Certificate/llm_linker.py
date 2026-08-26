from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

try:
    import tiktoken
except ModuleNotFoundError:  # pragma: no cover - environment bootstrap
    subprocess.check_call([sys.executable, "-m", "pip", "install", "tiktoken"])
    import tiktoken

from tqdm import tqdm

from CertGuard.config.llm_backend import build_client, chat_text
from .models import LinkDecision, dedupe_link_decisions, normalize_link_type
from .llm_utils import disable_proxy_for_localhost
from CertGuard.project_documents.json_store import read_json, write_json


PARAGRAPH_LINKING_SYSTEM_PROMPT = """You are an expert in X.509 PKI and RFC text analysis.

Your task is to link one RFC paragraph to the most relevant certificate or CRL structure nodes.

You will receive:
1. The target paragraph
2. Section context
3. Nearby paragraph context
4. A list of candidate structure nodes

Your goals:
1. Select only the structure nodes that the paragraph directly constrains, explicitly defines, or clearly provides supporting field-specific context for.
2. Do not invent nodes outside the candidate list.
3. Treat section headings as strong field-localizing evidence. If the current section heading names a specific field, extension, bit, value, or profile item, prefer that candidate unless the paragraph clearly shifts scope to a different target.
4. Treat the parent heading and the full section path as additional localization evidence.
5. Prefer the most specific node that matches the paragraph.
6. Do not include redundant ancestors when a specific descendant already captures the paragraph.
7. If the paragraph is not meaningfully about any candidate structure node, return an empty list.

Use exactly one link_type per selected node:
- "direct_constraint": the paragraph imposes a concrete requirement, prohibition, permission, encoding rule, presence rule, cardinality rule, value restriction, or processing constraint on that structure node.
- "descriptive_definition": the paragraph mainly defines the meaning, semantics, or role of that structure node, without being primarily a direct conformance constraint.
- "supporting_context": the paragraph is not itself the main rule for the node, but it provides field-specific supporting context that would be useful when analyzing the node.

Output requirements:
Return JSON only. Do not include explanations outside JSON.

Output format:
{
  "links": [
    {
      "node_id": "candidate node id",
      "link_type": "direct_constraint | descriptive_definition | supporting_context",
      "reason": "short explanation"
    }
  ],
  "overall_reason": "short explanation"
}

Additional constraints:
- node_id values must come only from the candidate list.
- A section heading may disambiguate a broad paragraph. For example, if the paragraph says "this extension" and the section heading is "Basic Constraints", that heading is a major signal for the target node.
- Do not choose a root container merely because the paragraph says "certificate" or "CRL" when the heading points to a specific child field.
- Keep reasons concise.
- Do not repeat node ids.
- Return {"links": [], "overall_reason": "..."} when no candidate fits.
"""

DEFAULT_MAX_USER_PROMPT_TOKENS = 120000
DEFAULT_TOKEN_ENCODING = "cl100k_base"


def process_linking_dataset_with_llm(
    dataset_path: str,
    base_url: str,
    api_key: str,
    model: str,
    backend: str = "openai",
    limit: Optional[int] = None,
    force: bool = False,
    timeout: float = 120.0,
    temperature: float = 0.0,
    response_dir: Optional[str] = None,
    error_dir: Optional[str] = None,
    max_user_prompt_tokens: int = DEFAULT_MAX_USER_PROMPT_TOKENS,
) -> Dict[str, int]:
    disable_proxy_for_localhost()
    client = build_client(
        backend=backend,
        base_url=base_url,
        api_key=api_key,
        timeout=timeout,
        model=model,
        temperature=temperature,
    )
    dataset = read_json(dataset_path)

    processed = 0
    attempted = 0
    skipped = 0
    errors = 0
    auto_completed = 0

    ordered_items = _ordered_items(dataset.get("items", []), force=force)
    planned_items = _items_until_attempt_limit(ordered_items, force=force, limit=limit)
    with tqdm(
        total=len(planned_items),
        desc="RFC2Certificate LLM",
        unit="item",
        dynamic_ncols=True,
    ) as progress:
        for item in planned_items:
            if not force and _is_llm_completed(item):
                skipped += 1
                _update_progress(progress, processed, skipped, errors, auto_completed, attempted)
                continue

            candidate_nodes = item.get("input", {}).get("candidate_nodes") or []
            if not candidate_nodes:
                item["status"] = "llm_completed"
                item["llm_result"] = {
                    "links": [],
                    "overall_reason": "No candidate structure nodes were retrieved for this paragraph.",
                    "raw_response": None,
                    "model": None,
                    "processed_at": _utc_now(),
                }
                item.setdefault("import_status", {})
                item["import_status"]["imported"] = False
                item["import_status"]["error"] = None
                auto_completed += 1
                write_json(dataset_path, dataset)
                _update_progress(progress, processed, skipped, errors, auto_completed, attempted)
                continue

            item_id = str(item.get("item_id") or "<unknown>")
            try:
                attempted += 1
                prompt = build_user_prompt(
                    item.get("input", {}),
                    model=model,
                    max_user_prompt_tokens=max_user_prompt_tokens,
                )
                content = chat_text(
                    backend=backend,
                    client=client,
                    model=model,
                    temperature=temperature,
                    messages=[
                        {"role": "system", "content": PARAGRAPH_LINKING_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                ) or '{"links":[],"overall_reason":""}'
                parsed = parse_linking_response(content, item.get("input", {}))
                item["status"] = "llm_completed"
                item["llm_result"] = {
                    "links": parsed["links"],
                    "overall_reason": parsed.get("overall_reason"),
                    "raw_response": content,
                    "model": model,
                    "processed_at": _utc_now(),
                }
                item.setdefault("import_status", {})
                item["import_status"]["imported"] = False
                item["import_status"]["error"] = None
                processed += 1
                _write_artifact(
                    response_dir,
                    item_id,
                    {
                        "item_id": item_id,
                        "raw_response": content,
                        "parsed_result": parsed,
                        "model": model,
                        "processed_at": item["llm_result"]["processed_at"],
                    },
                )
            except Exception as exc:
                item["status"] = "llm_error"
                item.setdefault("llm_result", {})
                item["llm_result"]["error"] = str(exc)
                item["llm_result"]["processed_at"] = _utc_now()
                errors += 1
                _write_artifact(
                    error_dir,
                    item_id,
                    {
                        "item_id": item_id,
                        "error": str(exc),
                        "processed_at": item["llm_result"]["processed_at"],
                    },
                )

            write_json(dataset_path, dataset)
            _update_progress(progress, processed, skipped, errors, auto_completed, attempted)

    return {
        "attempted": attempted,
        "processed": processed,
        "skipped": skipped,
        "errors": errors,
        "auto_completed": auto_completed,
    }


def build_user_prompt(
    item_input: Dict[str, Any],
    model: Optional[str] = None,
    max_user_prompt_tokens: int = DEFAULT_MAX_USER_PROMPT_TOKENS,
) -> str:
    section_context = item_input.get("section_context", {}) or {}
    title_signals = section_context.get("title_signals") or {}
    payload = {
        "important_instruction": {
            "section_headings_are_strong_signals": True,
            "rule": "Use the current section heading, parent heading, and section path as important evidence for which structure node this paragraph is about.",
        },
        "title_signals": title_signals,
        "paragraph": item_input.get("target_paragraph", {}),
        "section_context": section_context,
        "local_context": item_input.get("local_context", {}),
        "candidate_nodes": _trim_candidate_nodes(item_input.get("candidate_nodes", [])),
    }
    prompt_prefix = "Select the best structure nodes for the following RFC paragraph context:\n\n"
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    prompt = prompt_prefix + serialized
    if _estimate_tokens(prompt, model=model) <= max_user_prompt_tokens:
        return prompt

    trimmed_payload = dict(payload)
    local_context = dict(trimmed_payload.get("local_context") or {})
    for field_name in ("next_paragraphs", "previous_paragraphs", "section_intro_paragraphs"):
        if field_name in local_context:
            local_context[field_name] = []
            trimmed_payload["local_context"] = local_context
            serialized = json.dumps(trimmed_payload, ensure_ascii=False, indent=2)
            prompt = prompt_prefix + serialized
            if _estimate_tokens(prompt, model=model) <= max_user_prompt_tokens:
                return prompt

    paragraph = dict(trimmed_payload.get("paragraph") or {})
    paragraph["text"] = _truncate_text_to_token_limit(
        str(paragraph.get("text") or ""),
        token_limit=800,
        model=model,
    )
    trimmed_payload["paragraph"] = paragraph
    serialized = json.dumps(trimmed_payload, ensure_ascii=False, indent=2)
    prompt = prompt_prefix + serialized
    if _estimate_tokens(prompt, model=model) <= max_user_prompt_tokens:
        return prompt

    prompt = _truncate_text_to_token_limit(
        prompt,
        token_limit=max_user_prompt_tokens,
        model=model,
    )
    return prompt


def parse_linking_response(content: str, item_input: Dict[str, Any]) -> Dict[str, Any]:
    parsed = json.loads(extract_json_object(content))
    if not isinstance(parsed, dict):
        raise ValueError("LLM response must be a JSON object.")

    allowed_ids = {
        candidate["id"]
        for candidate in item_input.get("candidate_nodes", [])
        if isinstance(candidate, dict) and candidate.get("id")
    }
    decisions: List[LinkDecision] = []
    for link in parsed.get("links") or []:
        if not isinstance(link, dict):
            continue
        node_id = link.get("node_id")
        if not isinstance(node_id, str) or node_id not in allowed_ids:
            continue
        link_type = normalize_link_type(link.get("link_type"))
        if not link_type:
            continue
        reason = str(link.get("reason") or "").strip()
        decisions.append(LinkDecision(node_id=node_id, link_type=link_type, reason=reason))

    overall_reason = parsed.get("overall_reason")
    if overall_reason is not None and not isinstance(overall_reason, str):
        overall_reason = str(overall_reason)

    return {
        "links": [decision.to_dict() for decision in dedupe_link_decisions(decisions)],
        "overall_reason": overall_reason,
    }


def extract_json_object(content: str) -> str:
    stripped = content.strip()
    fence_match = re.search(r"```(?:json)?\s*(.*?)```", stripped, re.DOTALL | re.IGNORECASE)
    if fence_match:
        stripped = fence_match.group(1).strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        return stripped[start : end + 1]
    raise ValueError("No JSON object found in LLM response.")


def _ordered_items(items: Sequence[Dict[str, Any]], force: bool) -> List[Dict[str, Any]]:
    if force:
        return list(items)
    failed = [item for item in items if _is_llm_failed(item)]
    pending = [
        item
        for item in items
        if not _is_llm_completed(item) and not _is_llm_failed(item)
    ]
    completed = [item for item in items if _is_llm_completed(item)]
    return failed + pending + completed


def _items_until_attempt_limit(
    items: Sequence[Dict[str, Any]],
    force: bool,
    limit: Optional[int],
) -> List[Dict[str, Any]]:
    if limit is None:
        return list(items)

    planned: List[Dict[str, Any]] = []
    attempts = 0
    for item in items:
        if attempts >= limit:
            break
        planned.append(item)
        if not force and _is_llm_completed(item):
            continue
        candidate_nodes = item.get("input", {}).get("candidate_nodes") or []
        if candidate_nodes:
            attempts += 1
    return planned


def _update_progress(
    progress: tqdm,
    processed: int,
    skipped: int,
    errors: int,
    auto_completed: int,
    attempted: int,
) -> None:
    progress.update(1)
    progress.set_postfix(
        attempted=attempted,
        processed=processed,
        skipped=skipped,
        auto=auto_completed,
        errors=errors,
    )


def _is_llm_completed(item: Dict[str, Any]) -> bool:
    if _is_llm_failed(item):
        return False
    if item.get("status") in {"llm_completed", "imported"}:
        return True
    llm_result = item.get("llm_result") or {}
    return bool(llm_result.get("processed_at")) and "links" in llm_result


def _is_llm_failed(item: Dict[str, Any]) -> bool:
    if item.get("status") == "llm_error":
        return True
    llm_result = item.get("llm_result") or {}
    return bool(llm_result.get("error"))


def _trim_candidate_nodes(candidates: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    trimmed = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        trimmed.append(
            {
                "id": candidate.get("id"),
                "name": candidate.get("name"),
                "path": candidate.get("path"),
                "domain": candidate.get("domain"),
                "description": _truncate_text(str(candidate.get("description") or ""), 240),
                "score": candidate.get("score"),
                "reason": _truncate_text(str(candidate.get("reason") or ""), 180),
            }
        )
    return trimmed


def _truncate_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    if limit <= 3:
        return value[:limit]
    return value[: limit - 3] + "..."


def _truncate_text_to_token_limit(
    value: str,
    token_limit: int,
    model: Optional[str] = None,
) -> str:
    if token_limit <= 0:
        return ""
    if _estimate_tokens(value, model=model) <= token_limit:
        return value

    encoding = _get_token_encoding(model)
    tokens = encoding.encode(value)
    if token_limit <= 1:
        return encoding.decode(tokens[:token_limit])
    truncated = encoding.decode(tokens[: max(1, token_limit - 1)]).rstrip()
    while truncated and _estimate_tokens(truncated + "...", model=model) > token_limit:
        truncated = truncated[:-1].rstrip()
    return truncated + "..."


def _estimate_tokens(value: str, model: Optional[str] = None) -> int:
    encoding = _get_token_encoding(model)
    return len(encoding.encode(value))


def _get_token_encoding(model: Optional[str] = None):
    if model:
        try:
            return tiktoken.encoding_for_model(model)
        except KeyError:
            pass
    return tiktoken.get_encoding(DEFAULT_TOKEN_ENCODING)


def _write_artifact(directory: Optional[str], item_id: str, payload: Dict[str, Any]) -> None:
    if not directory:
        return
    os.makedirs(directory, exist_ok=True)
    filename = re.sub(r"[^A-Za-z0-9._-]+", "_", item_id).strip("_") or "item"
    write_json(os.path.join(directory, "%s.json" % filename), payload)


def _utc_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
