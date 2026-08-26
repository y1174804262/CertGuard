from __future__ import annotations

import json
import os
import re
import hashlib
from datetime import datetime
from typing import Any, Dict, List, Sequence

from CertGuard.config.llm_backend import build_client, chat_text
from CertGuard.CertGraph_RFC2Certificate.llm_utils import disable_proxy_for_localhost
from CertGuard.project_documents.json_store import read_json, write_json

from .models import ContextChunk
from .prompts import (
    ANALYZER_SYSTEM_PROMPTS,
    EVALUATOR_SYSTEM_PROMPTS,
    build_evaluator_user_prompt,
)


EVALUATOR_PARSER_VERSION = "evaluator_parser_editorial_plain_copyedit_v11"


def run_chunk_evaluation(
    chunks: Sequence[ContextChunk],
    analyses: Sequence[Dict[str, Any]],
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
    analysis_by_chunk = {artifact.get("chunk_id"): artifact for artifact in analyses}
    results: List[Dict[str, Any]] = []

    for chunk in chunks:
        artifact_path = os.path.join(cache_dir, "%s.json" % chunk.chunk_id)
        context_fingerprint = _chunk_fingerprint(chunk)
        analysis = analysis_by_chunk.get(chunk.chunk_id) or {}
        parsed = analysis.get("parsed") or {}
        system_prompt = EVALUATOR_SYSTEM_PROMPTS[mode]
        analyzer_system_prompt = ANALYZER_SYSTEM_PROMPTS[mode]
        user_prompt = build_evaluator_user_prompt(
            chunk.node_id,
            chunk,
            parsed,
            analyzer_system_prompt,
        )
        prompt_fingerprint = _prompt_fingerprint(system_prompt, user_prompt)
        parser_fingerprint = _parser_fingerprint()
        if not force and os.path.exists(artifact_path):
            cached = read_json(artifact_path)
            if (
                cached.get("context_fingerprint") == context_fingerprint
                and cached.get("prompt_fingerprint") == prompt_fingerprint
                and cached.get("parser_fingerprint") == parser_fingerprint
            ):
                results.append(cached)
                continue

        if not parsed.get("problems"):
            artifact = {
                "chunk_id": chunk.chunk_id,
                "node_id": chunk.node_id,
                "mode": mode,
                "model": None,
                "processed_at": _utc_now(),
                "context_fingerprint": context_fingerprint,
                "prompt_fingerprint": prompt_fingerprint,
                "parser_fingerprint": parser_fingerprint,
                "prompt": None,
                "raw_response": None,
                "parsed": {
                    "accepted": [],
                    "rejected": [],
                    "overall_note": "No analyzer findings to evaluate.",
                },
            }
            write_json(artifact_path, artifact)
            results.append(artifact)
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
        ) or '{"accepted":[],"rejected":[],"overall_note":""}'
        parse_error = None
        try:
            normalized = _parse_evaluator_response(raw_response, chunk, mode)
        except Exception as exc:
            parse_error = "%s: %s" % (exc.__class__.__name__, exc)
            normalized = {
                "accepted": [],
                "rejected": [],
                "overall_note": "Evaluator response could not be parsed as valid JSON: %s" % parse_error,
            }
        artifact = {
            "chunk_id": chunk.chunk_id,
            "node_id": chunk.node_id,
            "mode": mode,
            "model": model,
            "processed_at": _utc_now(),
            "context_fingerprint": context_fingerprint,
            "prompt_fingerprint": prompt_fingerprint,
            "parser_fingerprint": parser_fingerprint,
            "prompt": {
                "system": system_prompt,
                "user": user_prompt,
            },
            "raw_response": raw_response,
            "parsed": normalized,
        }
        if parse_error:
            artifact["parse_error"] = parse_error
        write_json(artifact_path, artifact)
        results.append(artifact)

    return results


def _parse_evaluator_response(content: str, chunk: ContextChunk, mode: str) -> Dict[str, Any]:
    data = json.loads(_extract_json_object(content))
    if not isinstance(data, dict):
        raise ValueError("Evaluator output must be a JSON object.")

    allowed_ids = set(chunk.paragraph_map().keys())
    paragraph_map = chunk.paragraph_map()
    evidence_id_by_number = {
        index: evidence.paragraph_id
        for index, evidence in enumerate(chunk.evidences, start=1)
    }
    accepted: List[Dict[str, Any]] = []
    rejected: List[Dict[str, str]] = []
    for finding in data.get("accepted") or []:
        if not isinstance(finding, dict):
            continue
        title = str(finding.get("title") or "").strip()
        reason = str(finding.get("reason") or "").strip()
        paragraph_ids = []
        for paragraph_id in finding.get("paragraph_ids") or []:
            if isinstance(paragraph_id, str) and paragraph_id in allowed_ids and paragraph_id not in paragraph_ids:
                paragraph_ids.append(paragraph_id)
        if mode == "cross_document" and paragraph_ids:
            document_count = len({paragraph_map[paragraph_id].document_key for paragraph_id in paragraph_ids})
            if document_count < 2:
                continue
        missing_referenced = _missing_referenced_evidence_ids(
            reason=reason,
            paragraph_ids=paragraph_ids,
            evidence_id_by_number=evidence_id_by_number,
        )
        if missing_referenced:
            rejected.append(
                {
                    "title": title or "Rejected evidence-reference mismatch",
                    "reason": (
                        "Rejected because the reason cites evidence not included in paragraph_ids: "
                        + ", ".join(missing_referenced)
                    ),
                }
            )
            continue
        if title and reason and paragraph_ids:
            accepted.append(
                {
                    "title": title,
                    "paragraph_ids": paragraph_ids,
                    "reason": reason,
                }
            )

    for finding in data.get("rejected") or []:
        if not isinstance(finding, dict):
            continue
        title = str(finding.get("title") or "").strip()
        reason = str(finding.get("reason") or "").strip()
        if title and reason:
            rejected.append({"title": title, "reason": reason})

    overall_note = data.get("overall_note")
    if overall_note is not None and not isinstance(overall_note, str):
        overall_note = str(overall_note)

    return {
        "accepted": accepted,
        "rejected": rejected,
        "overall_note": overall_note or "",
    }


def _missing_referenced_evidence_ids(
    reason: str,
    paragraph_ids: Sequence[str],
    evidence_id_by_number: Dict[int, str],
) -> List[str]:
    missing: List[str] = []
    selected = set(paragraph_ids)
    for match in re.finditer(r"\bEvidence\s+(\d+)\b", reason, flags=re.IGNORECASE):
        evidence_number = int(match.group(1))
        paragraph_id = evidence_id_by_number.get(evidence_number)
        if paragraph_id and paragraph_id not in selected:
            label = "Evidence %d (%s)" % (evidence_number, paragraph_id)
            if label not in missing:
                missing.append(label)
    return missing


def _extract_json_object(content: str) -> str:
    stripped = content.strip()
    fence_match = re.search(r"```(?:json)?\s*(.*?)```", stripped, re.IGNORECASE | re.DOTALL)
    if fence_match:
        stripped = fence_match.group(1).strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        return stripped[start : end + 1]
    raise ValueError("No JSON object found in evaluator response.")


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


def _parser_fingerprint() -> str:
    return hashlib.sha256(EVALUATOR_PARSER_VERSION.encode("utf-8")).hexdigest()
