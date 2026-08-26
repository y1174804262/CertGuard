from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Dict, List


LINK_TYPE_PRIORITY = {
    "direct_constraint": 0,
    "descriptive_definition": 1,
    "supporting_context": 2,
}


@dataclass(frozen=True)
class ParagraphEvidence:
    document_key: str
    document_id: str
    document_title: str
    paragraph_id: str
    paragraph_order: int
    section_number: str
    section_title: str
    text: str
    link_type: str
    score: float
    candidate_reason: str
    overall_reason: str

    @property
    def section_label(self) -> str:
        if self.section_number and self.section_title:
            return "%s %s" % (self.section_number, self.section_title)
        return self.section_number or self.section_title or "<unknown section>"

    @property
    def priority(self) -> int:
        return LINK_TYPE_PRIORITY.get(self.link_type, 99)

    def prompt_block(self, rank: int) -> str:
        lines = [
            "### Evidence %d" % rank,
            "paragraph_id: %s" % self.paragraph_id,
            "document_key: %s" % self.document_key,
            "document_title: %s" % self.document_title,
            "section: %s" % self.section_label,
            "link_type: %s" % self.link_type,
            "retrieval_score: %.4f" % self.score,
            "paragraph_text:",
            self.text.strip(),
        ]
        return "\n".join(lines)

    def to_result_dict(self) -> Dict[str, str]:
        return {
            "document": self.document_key,
            "section": self.section_label,
            "paragraph_id": self.paragraph_id,
            "text": self.text,
        }


@dataclass(frozen=True)
class ContextChunk:
    chunk_id: str
    node_id: str
    mode: str
    evidences: List[ParagraphEvidence]
    estimated_tokens: int

    def render(self) -> str:
        blocks = [
            "Target structure node: %s" % self.node_id,
            "Mode: %s" % self.mode,
            "Evidence count: %d" % len(self.evidences),
            "",
        ]
        for index, evidence in enumerate(self.evidences, start=1):
            blocks.append(evidence.prompt_block(index))
            blocks.append("")
        return "\n".join(blocks).strip()

    def paragraph_map(self) -> Dict[str, ParagraphEvidence]:
        return {evidence.paragraph_id: evidence for evidence in self.evidences}

    def to_dict(self) -> Dict[str, object]:
        return {
            "chunk_id": self.chunk_id,
            "node_id": self.node_id,
            "mode": self.mode,
            "estimated_tokens": self.estimated_tokens,
            "evidences": [
                {
                    "document_key": evidence.document_key,
                    "document_id": evidence.document_id,
                    "document_title": evidence.document_title,
                    "paragraph_id": evidence.paragraph_id,
                    "paragraph_order": evidence.paragraph_order,
                    "section_number": evidence.section_number,
                    "section_title": evidence.section_title,
                    "text": evidence.text,
                    "link_type": evidence.link_type,
                    "score": evidence.score,
                    "candidate_reason": evidence.candidate_reason,
                    "overall_reason": evidence.overall_reason,
                }
                for evidence in self.evidences
            ],
        }


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, int(math.ceil(len(text) / 4.0)))


def section_sort_key(section_number: str) -> List[object]:
    if not section_number:
        return [999999]
    parts = re.findall(r"\d+|[A-Za-z]+", section_number)
    key: List[object] = []
    for part in parts:
        if part.isdigit():
            key.append(int(part))
        else:
            key.append(part.lower())
    return key
