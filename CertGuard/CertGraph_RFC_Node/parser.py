from __future__ import annotations

import re
from typing import Dict, List, Optional

from .models import Paragraph, RfcDocument, Section


SECTION_RE = re.compile(
    r"^\s*(?P<number>(?:[1-9]\d*|0)(?:\.(?:[1-9]\d*|0))*\.?)\s+"
    r"(?P<title>\S.*)$"
)
LIST_ITEM_RE = re.compile(r"^\s*\([A-Za-z0-9]+\)\s+")
NUMBERED_ITEM_RE = re.compile(r"^\s*(?:\d+|[A-Za-z]|[ivxlcdmIVXLCDM]+)\.\s+")
DEFINITION_ITEM_RE = re.compile(r"^\s*[A-Za-z][A-Za-z0-9 /-]{0,40}:\s+\S")
ASN1_FIELD_RE = re.compile(r"^\s*[A-Za-z][A-Za-z0-9-]*\s+\[[0-9]+\]\s+")
ASN1_ASSIGN_RE = re.compile(r"^\s*[A-Za-z][A-Za-z0-9-]*\s*::=\s+")

PAGE_HEADER_RE = re.compile(r"^\s*RFC\s+\d+\b", re.IGNORECASE)
PAGE_FOOTER_RE = re.compile(r"^\s*\[[Pp]age\s+\d+\]\s*$")
PAGE_MARKER_RE = re.compile(r"^\s*\[\[PAGE\s+\d+\]\]\s*$", re.IGNORECASE)
FORM_FEED = "\f"


def parse_rfc_text(text: str, rfc_id: str, title: Optional[str] = None) -> RfcDocument:
    lines = _normalize_lines(text)
    doc = RfcDocument(id=rfc_id, title=title or _extract_title(lines) or rfc_id)
    section_stack: List[Section] = []
    section_order = 0
    paragraph_buffers: Dict[str, List[str]] = {}

    def flush_paragraph(section: Optional[Section]) -> None:
        if section is None:
            return
        buffer = paragraph_buffers.get(section.id)
        if not buffer:
            return
        paragraph_order = len(section.paragraphs) + 1
        paragraph = Paragraph(
            id="%s-p%d" % (section.id, paragraph_order),
            text=" ".join(part.strip() for part in buffer if part.strip()),
            order=paragraph_order,
        )
        if paragraph.text:
            section.paragraphs.append(paragraph)
        paragraph_buffers[section.id] = []

    current_section: Optional[Section] = None

    for index, raw_line in enumerate(lines):
        line = raw_line.rstrip()
        stripped = line.strip()

        if _is_noise_line(stripped):
            continue

        previous_stripped = lines[index - 1].strip() if index > 0 else ""
        next_stripped = lines[index + 1].strip() if index + 1 < len(lines) else ""
        section_match = _match_section_heading(line, previous_stripped, next_stripped)
        if section_match:
            flush_paragraph(current_section)
            section_order += 1
            number = _normalize_section_number(section_match.group("number"))
            section = Section(
                id="%s-sec-%s" % (rfc_id, number),
                number=number,
                title=section_match.group("title").strip(),
                order=section_order,
            )
            _attach_section(doc, section_stack, section)
            paragraph_buffers[section.id] = []
            current_section = section
            continue

        if current_section is None:
            continue

        if not stripped:
            if _is_soft_paragraph_break(lines, index, paragraph_buffers.get(current_section.id, [])):
                continue
            flush_paragraph(current_section)
            continue

        paragraph_buffers.setdefault(current_section.id, []).append(stripped)

    flush_paragraph(current_section)
    return doc


def parse_rfc_file(
    path: str,
    rfc_id: str,
    title: Optional[str] = None,
    encoding: str = "utf-8",
) -> RfcDocument:
    with open(path, "r", encoding=encoding) as file:
        return parse_rfc_text(file.read(), rfc_id=rfc_id, title=title)


def iter_sections(document: RfcDocument) -> List[Section]:
    sections: List[Section] = []

    def visit(section: Section) -> None:
        sections.append(section)
        for subsection in section.subsections:
            visit(subsection)

    for top_level in document.sections:
        visit(top_level)
    return sections


def _normalize_lines(text: str) -> List[str]:
    return text.replace(FORM_FEED, "\n").splitlines()


def _extract_title(lines: List[str]) -> Optional[str]:
    for line in lines:
        stripped = line.strip()
        if stripped:
            return stripped
    return None


def _is_noise_line(stripped: str) -> bool:
    if not stripped:
        return False
    return bool(
        PAGE_HEADER_RE.match(stripped)
        or PAGE_FOOTER_RE.match(stripped)
        or PAGE_MARKER_RE.match(stripped)
    )


def _match_section_heading(
    line: str,
    previous_stripped: str = "",
    next_stripped: str = "",
) -> Optional[re.Match]:
    if previous_stripped:
        return None
    match = SECTION_RE.match(line)
    if not match:
        return None
    title = match.group("title").strip()
    if not title or title.endswith("."):
        return None
    if next_stripped[:1].islower():
        return None
    return match


def _normalize_section_number(number: str) -> str:
    return number.rstrip(".")


def _is_soft_paragraph_break(lines: List[str], index: int, buffer: List[str]) -> bool:
    if not buffer:
        return False
    previous_text = buffer[-1].strip()
    if not previous_text:
        return False
    next_text = _next_content_line(lines, index + 1)
    if not next_text:
        return False
    if _looks_like_new_block(next_text):
        return False
    if next_text[:1].islower() or next_text[:1].isdigit():
        return True
    if previous_text.endswith("-"):
        return True
    if not re.search(r"[.!?;:)]$", previous_text):
        return True
    return False


def _next_content_line(lines: List[str], start_index: int) -> Optional[str]:
    for raw_line in lines[start_index:]:
        stripped = raw_line.strip()
        if not stripped or _is_noise_line(stripped):
            continue
        return stripped
    return None


def _looks_like_new_block(text: str) -> bool:
    if not text:
        return False
    if SECTION_RE.match(text):
        return True
    if LIST_ITEM_RE.match(text):
        return True
    if NUMBERED_ITEM_RE.match(text):
        return True
    if DEFINITION_ITEM_RE.match(text):
        return True
    if ASN1_FIELD_RE.match(text):
        return True
    if ASN1_ASSIGN_RE.match(text):
        return True
    return False


def _section_depth(number: str) -> int:
    return number.count(".") + 1


def _attach_section(
    document: RfcDocument,
    section_stack: List[Section],
    section: Section,
) -> None:
    depth = _section_depth(section.number)
    while len(section_stack) >= depth:
        section_stack.pop()

    if section_stack:
        section_stack[-1].subsections.append(section)
    else:
        document.sections.append(section)

    section_stack.append(section)
