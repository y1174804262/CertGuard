from __future__ import annotations

from collections import OrderedDict
from typing import Dict, Iterable, List, Sequence, Tuple

from .models import ContextChunk, ParagraphEvidence, estimate_tokens


SAME_DOCUMENT_MODES = {"semantic_impact", "editorial_low_impact"}


def build_context_chunks(
    node_id: str,
    mode: str,
    evidences: Sequence[ParagraphEvidence],
    max_context_tokens: int = 48000,
) -> List[ContextChunk]:
    if not evidences:
        return []

    usable_tokens = max(2048, max_context_tokens - 1200)
    if mode in SAME_DOCUMENT_MODES:
        return _build_same_document_chunks(
            node_id=node_id,
            mode=mode,
            evidences=evidences,
            usable_tokens=usable_tokens,
        )
    return _build_sequential_chunks(
        node_id=node_id,
        mode=mode,
        evidences=evidences,
        usable_tokens=usable_tokens,
    )


def build_document_order_chunks(
    document_key: str,
    mode: str,
    evidences: Sequence[ParagraphEvidence],
    max_context_tokens: int = 16000,
    overlap_paragraphs: int = 2,
) -> List[ContextChunk]:
    if not evidences:
        return []

    usable_tokens = max(2048, max_context_tokens - 1200)
    chunks: List[List[ParagraphEvidence]] = []
    current: List[ParagraphEvidence] = []
    current_tokens = 0

    for evidence in evidences:
        evidence_tokens = _chunk_tokens([evidence])
        if current and current_tokens + evidence_tokens > usable_tokens:
            chunks.append(list(current))
            current = list(current[-max(0, overlap_paragraphs) :])
            current_tokens = _chunk_tokens(current)
        current.append(evidence)
        current_tokens += evidence_tokens

    if current:
        chunks.append(list(current))

    rendered: List[ContextChunk] = []
    for index, chunk_evidences in enumerate(chunks, start=1):
        deduped = _dedupe_preserve_order(chunk_evidences)
        rendered.append(
            ContextChunk(
                chunk_id="chunk_%03d" % index,
                node_id="document:%s" % document_key,
                mode=mode,
                evidences=deduped,
                estimated_tokens=_chunk_tokens(deduped),
            )
        )
    return rendered


def _build_same_document_chunks(
    node_id: str,
    mode: str,
    evidences: Sequence[ParagraphEvidence],
    usable_tokens: int,
) -> List[ContextChunk]:
    grouped_by_document: "OrderedDict[str, List[ParagraphEvidence]]" = OrderedDict()
    for evidence in evidences:
        grouped_by_document.setdefault(evidence.document_key, []).append(evidence)

    chunks: List[ContextChunk] = []
    next_index = 1
    for document_evidences in grouped_by_document.values():
        document_chunks = _build_sequential_chunks(
            node_id=node_id,
            mode=mode,
            evidences=document_evidences,
            usable_tokens=usable_tokens,
            start_index=next_index,
        )
        chunks.extend(document_chunks)
        next_index += len(document_chunks)
    return chunks


def _build_sequential_chunks(
    node_id: str,
    mode: str,
    evidences: Sequence[ParagraphEvidence],
    usable_tokens: int,
    start_index: int = 1,
) -> List[ContextChunk]:
    ordered = _dedupe_preserve_order(list(evidences))
    chunks: List[List[ParagraphEvidence]] = []
    current: List[ParagraphEvidence] = []
    current_tokens = 0

    for evidence in ordered:
        evidence_tokens = _chunk_tokens([evidence])
        if current and current_tokens + evidence_tokens > usable_tokens:
            chunks.append(list(current))
            current = []
            current_tokens = 0
        current.append(evidence)
        current_tokens += evidence_tokens

    if current:
        chunks.append(list(current))

    return [
        ContextChunk(
            chunk_id="chunk_%03d" % index,
            node_id=node_id,
            mode=mode,
            evidences=chunk_evidences,
            estimated_tokens=_chunk_tokens(chunk_evidences),
        )
        for index, chunk_evidences in enumerate(chunks, start=start_index)
    ]


def _chunk_tokens(evidences: Iterable[ParagraphEvidence]) -> int:
    token_total = 0
    for evidence in evidences:
        token_total += estimate_tokens(evidence.prompt_block(1)) + 12
    return token_total


def _dedupe_preserve_order(evidences: Sequence[ParagraphEvidence]) -> List[ParagraphEvidence]:
    deduped: List[ParagraphEvidence] = []
    seen: Dict[Tuple[str, str, str], bool] = {}
    for evidence in evidences:
        key = (evidence.document_key, evidence.paragraph_id, evidence.link_type)
        if key in seen:
            continue
        seen[key] = True
        deduped.append(evidence)
    return deduped
