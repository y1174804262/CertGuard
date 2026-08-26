from __future__ import annotations

import os
from typing import Iterable, List, Optional, Sequence, Set

from CertGuard.project_documents.json_store import read_json
from CertGuard.project_documents.paths import document_dir, normalize_document_key

from .models import ParagraphEvidence, section_sort_key


def default_dataset_path(document_key: str) -> str:
    key = normalize_document_key(document_key)
    return os.path.join(
        document_dir(key),
        "rfc2certificate",
        "%s_paragraph_node_linking_dataset.json" % key,
    )


def resolve_dataset_paths(
    document_keys: Sequence[str],
    dataset_paths: Sequence[str],
    project_root: str,
) -> List[str]:
    resolved: List[str] = []
    seen: Set[str] = set()

    for document_key in document_keys:
        path = os.path.abspath(default_dataset_path(document_key))
        if path not in seen:
            resolved.append(path)
            seen.add(path)

    for dataset_path in dataset_paths:
        if not dataset_path:
            continue
        if os.path.isabs(dataset_path):
            path = dataset_path
        else:
            path = os.path.abspath(os.path.join(project_root, dataset_path))
        if path not in seen:
            resolved.append(path)
            seen.add(path)

    return resolved


def load_evidence_for_node(
    node_id: str,
    dataset_paths: Sequence[str],
    link_types: Optional[Iterable[str]] = None,
    max_evidence: Optional[int] = None,
) -> List[ParagraphEvidence]:
    allowed_link_types = {value.strip() for value in (link_types or []) if value and value.strip()}
    evidences: List[ParagraphEvidence] = []
    seen = set()

    for dataset_path in dataset_paths:
        if not os.path.exists(dataset_path):
            continue
        dataset = read_json(dataset_path)
        document = dataset.get("document") or {}
        document_id = str(document.get("id") or "")
        document_title = str(document.get("title") or "")
        document_key = _infer_document_key(dataset_path, document_id)

        for item in dataset.get("items", []):
            if not isinstance(item, dict):
                continue
            item_input = item.get("input") or {}
            metadata = item_input.get("metadata") or {}
            paragraph = item_input.get("target_paragraph") or {}
            section_context = item_input.get("section_context") or {}
            llm_result = item.get("llm_result") or {}
            candidate_nodes = item_input.get("candidate_nodes") or []
            candidate_by_id = {
                candidate.get("id"): candidate
                for candidate in candidate_nodes
                if isinstance(candidate, dict) and candidate.get("id")
            }

            for link in llm_result.get("links") or []:
                if not isinstance(link, dict):
                    continue
                if link.get("node_id") != node_id:
                    continue
                link_type = str(link.get("link_type") or "").strip()
                if allowed_link_types and link_type not in allowed_link_types:
                    continue

                paragraph_id = str(paragraph.get("id") or metadata.get("paragraph_id") or "")
                if not paragraph_id:
                    continue
                unique_key = (document_key, paragraph_id, link_type)
                if unique_key in seen:
                    continue
                seen.add(unique_key)

                candidate = candidate_by_id.get(node_id) or {}
                evidences.append(
                    ParagraphEvidence(
                        document_key=document_key,
                        document_id=document_id,
                        document_title=document_title,
                        paragraph_id=paragraph_id,
                        paragraph_order=int(paragraph.get("order") or metadata.get("paragraph_order") or 0),
                        section_number=str(section_context.get("section_number") or ""),
                        section_title=str(section_context.get("section_title") or ""),
                        text=str(paragraph.get("text") or ""),
                        link_type=link_type,
                        score=float(candidate.get("score") or 0.0),
                        candidate_reason=str(candidate.get("reason") or ""),
                        overall_reason=str(llm_result.get("overall_reason") or ""),
                    )
                )
                if max_evidence is not None and len(evidences) >= max_evidence:
                    return _sort_evidences(evidences)

    return _sort_evidences(evidences)


def load_document_evidence(
    dataset_path: str,
    max_evidence: Optional[int] = None,
) -> List[ParagraphEvidence]:
    if not os.path.exists(dataset_path):
        return []

    dataset = read_json(dataset_path)
    document = dataset.get("document") or {}
    document_id = str(document.get("id") or "")
    document_title = str(document.get("title") or "")
    document_key = _infer_document_key(dataset_path, document_id)
    evidences: List[ParagraphEvidence] = []
    seen = set()

    for item in dataset.get("items", []):
        if not isinstance(item, dict):
            continue
        item_input = item.get("input") or {}
        metadata = item_input.get("metadata") or {}
        paragraph = item_input.get("target_paragraph") or {}
        section_context = item_input.get("section_context") or {}

        paragraph_id = str(paragraph.get("id") or metadata.get("paragraph_id") or "")
        text = str(paragraph.get("text") or "").strip()
        if not paragraph_id or not text:
            continue
        unique_key = (document_key, paragraph_id)
        if unique_key in seen:
            continue
        seen.add(unique_key)

        evidences.append(
            ParagraphEvidence(
                document_key=document_key,
                document_id=document_id,
                document_title=document_title,
                paragraph_id=paragraph_id,
                paragraph_order=int(paragraph.get("order") or metadata.get("paragraph_order") or 0),
                section_number=str(section_context.get("section_number") or ""),
                section_title=str(section_context.get("section_title") or ""),
                text=text,
                link_type="document_scan",
                score=0.0,
                candidate_reason="document-level editorial scan",
                overall_reason="Included without structure-node filtering for document-level editorial detection.",
            )
        )
        if max_evidence is not None and len(evidences) >= max_evidence:
            break

    return sorted(
        evidences,
        key=lambda item: (
            section_sort_key(item.section_number),
            item.paragraph_order,
            item.paragraph_id,
        ),
    )


def _sort_evidences(evidences: Sequence[ParagraphEvidence]) -> List[ParagraphEvidence]:
    return sorted(
        evidences,
        key=lambda item: (
            item.priority,
            item.document_key.lower(),
            section_sort_key(item.section_number),
            item.paragraph_order,
            item.paragraph_id,
        ),
    )


def _infer_document_key(dataset_path: str, document_id: str) -> str:
    parent_dir = os.path.basename(os.path.dirname(os.path.dirname(dataset_path)))
    if parent_dir:
        return parent_dir
    return document_id or "document"
