from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

from .models import ContextChunk, ParagraphEvidence


def aggregate_mode_results(
    node_id: str,
    mode: str,
    document_keys: Sequence[str],
    evidences: Sequence[ParagraphEvidence],
    chunks: Sequence[ContextChunk],
    analyses: Sequence[Dict[str, Any]],
    evaluations: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    paragraph_by_id: Dict[str, ParagraphEvidence] = {
        evidence.paragraph_id: evidence for evidence in evidences
    }

    accepted = _collect_accepted(evaluations, paragraph_by_id)
    rejected = _collect_rejected(evaluations)

    return {
        "node_id": node_id,
        "mode": mode,
        "documents": list(document_keys),
        "summary": {
            "evidence_count": len(evidences),
            "chunk_count": len(chunks),
            "analyzer_call_count": len(analyses),
            "evaluator_call_count": len(evaluations),
            "accepted_problem_count": len(accepted),
            "rejected_problem_count": len(rejected),
        },
        "problems": accepted,
        "rejected": rejected,
    }


def _collect_accepted(
    evaluations: Sequence[Dict[str, Any]],
    paragraph_by_id: Dict[str, ParagraphEvidence],
) -> List[Dict[str, Any]]:
    accepted: List[Dict[str, Any]] = []
    seen = set()

    for evaluation in evaluations:
        parsed = evaluation.get("parsed") or {}
        for finding in parsed.get("accepted") or []:
            if not isinstance(finding, dict):
                continue
            paragraph_ids = _valid_unique_paragraph_ids(
                finding.get("paragraph_ids") or [],
                paragraph_by_id,
            )
            title = str(finding.get("title") or "").strip()
            reason = str(finding.get("reason") or "").strip()
            if not title or not reason or not paragraph_ids:
                continue
            dedupe_key: Tuple[str, Tuple[str, ...]] = (title.lower(), tuple(paragraph_ids))
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            accepted.append(
                _finding_entry(
                    title=title,
                    reason=reason,
                    paragraph_ids=paragraph_ids,
                    paragraph_by_id=paragraph_by_id,
                )
            )

    return accepted


def _finding_entry(
    title: str,
    reason: str,
    paragraph_ids: Sequence[str],
    paragraph_by_id: Dict[str, ParagraphEvidence],
) -> Dict[str, Any]:
    return {
        "title": title,
        "paragraphs": [
            paragraph_by_id[paragraph_id].to_result_dict()
            for paragraph_id in paragraph_ids
        ],
        "reason": reason,
    }


def _valid_unique_paragraph_ids(
    paragraph_ids: Sequence[object],
    paragraph_by_id: Dict[str, ParagraphEvidence],
) -> List[str]:
    valid: List[str] = []
    for paragraph_id in paragraph_ids:
        if not isinstance(paragraph_id, str):
            continue
        if paragraph_id not in paragraph_by_id:
            continue
        if paragraph_id in valid:
            continue
        valid.append(paragraph_id)
    return valid


def _collect_rejected(evaluations: Sequence[Dict[str, Any]]) -> List[Dict[str, str]]:
    merged: List[Dict[str, str]] = []
    seen = set()
    for evaluation in evaluations:
        parsed = evaluation.get("parsed") or {}
        for finding in parsed.get("rejected") or []:
            if not isinstance(finding, dict):
                continue
            title = str(finding.get("title") or "").strip()
            reason = str(finding.get("reason") or "").strip()
            if not title or not reason:
                continue
            dedupe_key = (title.lower(), reason.lower())
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            merged.append({"title": title, "reason": reason})
    return merged
