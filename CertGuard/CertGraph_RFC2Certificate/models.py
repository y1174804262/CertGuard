from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence


RELATES_TO_STRUCTURE = "RELATES_TO_STRUCTURE"

LINK_TYPE_DIRECT_CONSTRAINT = "direct_constraint"
LINK_TYPE_DESCRIPTIVE_DEFINITION = "descriptive_definition"
LINK_TYPE_SUPPORTING_CONTEXT = "supporting_context"
LINK_TYPES = (
    LINK_TYPE_DIRECT_CONSTRAINT,
    LINK_TYPE_DESCRIPTIVE_DEFINITION,
    LINK_TYPE_SUPPORTING_CONTEXT,
)

VALID_DOMAINS = ("certificate", "crl", "both", "none")


@dataclass(frozen=True)
class ParagraphBundle:
    rfc_id: str
    paragraph_id: str
    paragraph_order: int
    section_id: str
    section_number: str
    section_title: str
    section_path: List[Dict[str, str]]
    parent_section_title: Optional[str]
    text: str
    previous_paragraphs: List[Dict[str, Any]]
    next_paragraphs: List[Dict[str, Any]]
    section_intro_paragraphs: List[Dict[str, Any]]
    inferred_domain: str

    def to_item_input(self) -> Dict[str, Any]:
        title_signals = {
            "current_section_heading": {
                "number": self.section_number,
                "title": self.section_title,
            },
            "parent_section_heading": (
                {
                    "title": self.parent_section_title,
                }
                if self.parent_section_title
                else None
            ),
            "section_path_headings": self.section_path,
        }
        return {
            "metadata": {
                "rfc_id": self.rfc_id,
                "section_id": self.section_id,
                "paragraph_id": self.paragraph_id,
                "paragraph_order": self.paragraph_order,
                "inferred_domain": self.inferred_domain,
            },
            "section_context": {
                "section_number": self.section_number,
                "section_title": self.section_title,
                "section_path": self.section_path,
                "parent_section_title": self.parent_section_title,
                "title_signals": title_signals,
            },
            "target_paragraph": {
                "id": self.paragraph_id,
                "order": self.paragraph_order,
                "text": self.text,
            },
            "local_context": {
                "section_intro_paragraphs": self.section_intro_paragraphs,
                "previous_paragraphs": self.previous_paragraphs,
                "next_paragraphs": self.next_paragraphs,
            },
            "candidate_nodes": [],
        }


@dataclass(frozen=True)
class StructureCandidate:
    node_id: str
    name: str
    path: str
    domain: str
    description: str
    depth: int
    is_leaf: bool
    score: float
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.node_id,
            "name": self.name,
            "path": self.path,
            "domain": self.domain,
            "description": self.description,
            "depth": self.depth,
            "is_leaf": self.is_leaf,
            "score": round(self.score, 4),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class LinkDecision:
    node_id: str
    link_type: str
    reason: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "node_id": self.node_id,
            "link_type": self.link_type,
            "reason": self.reason,
        }


def normalize_link_type(value: Any) -> Optional[str]:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in LINK_TYPES:
            return normalized
    return None


def normalize_domain(value: Any) -> str:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in VALID_DOMAINS:
            return normalized
    return "none"


def dedupe_link_decisions(decisions: Sequence[LinkDecision]) -> List[LinkDecision]:
    seen = set()
    deduped: List[LinkDecision] = []
    for decision in decisions:
        if decision.node_id in seen:
            continue
        seen.add(decision.node_id)
        deduped.append(decision)
    return deduped
