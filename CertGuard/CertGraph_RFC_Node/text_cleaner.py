from __future__ import annotations

import re
import unicodedata
from typing import Dict, Iterable, List, Optional


PAGE_FOOTER_RE = re.compile(r"^\s*.+\[\s*[Pp]age\s+\d+\s*\]\s*$")
PAGE_HEADER_RE = re.compile(r"^\s*RFC\s+\d+\b.*$")
TOC_DOT_LEADER_RE = re.compile(r"\.{5,}")
PAGE_MARKER_RE = "[[PAGE {page}]]"
PAGE_MARKER_LINE_RE = re.compile(r"^\s*\[\[PAGE\s+\d+\]\]\s*$", re.IGNORECASE)
SECTION_HEADING_RE = re.compile(r"^\s*\d+(?:\.\d+)*\.?\s+\S")
APPENDIX_HEADING_RE = re.compile(r"^\s*(?:Appendix\s+)?[A-Z](?:\.\d+)*\.?\s+\S")
LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]\s+|\([A-Za-z0-9]+\)\s+)")
NUMBERED_ITEM_RE = re.compile(r"^\s*(?:\d+|[A-Za-z]|[ivxlcdmIVXLCDM]+)\.\s+")
DEFINITION_ITEM_RE = re.compile(r"^\s*[A-Za-z][A-Za-z0-9 /-]{0,40}:\s+\S")
ASN1_FIELD_RE = re.compile(r"^\s*[A-Za-z][A-Za-z0-9-]*\s+\[[0-9]+\]\s+")
ASN1_ASSIGN_RE = re.compile(r"^\s*[A-Za-z][A-Za-z0-9-]*\s*::=\s+")


def split_rfc_pages(raw_text: str) -> List[str]:
    normalized = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    pages = normalized.split("\f")
    if len(pages) == 1:
        return [normalized]
    return pages


def clean_rfc_text(
    raw_text: str,
    keep_page_markers: bool = True,
    drop_table_of_contents: bool = True,
) -> str:
    pages = split_rfc_pages(raw_text)
    output: List[str] = []
    in_toc = False
    body_started = False

    for page_number, page_text in enumerate(pages, start=1):
        page_lines = clean_rfc_page_lines(page_text.splitlines())
        if not page_lines:
            continue

        filtered_lines: List[str] = []
        for line in page_lines:
            stripped = line.strip()
            if drop_table_of_contents:
                if stripped.lower() == "table of contents":
                    in_toc = True
                    continue
                if in_toc:
                    if not stripped or TOC_DOT_LEADER_RE.search(stripped):
                        continue
                    if _looks_like_section_start(stripped):
                        in_toc = False
            if not body_started and _looks_like_section_start(stripped):
                body_started = True
            if body_started:
                filtered_lines.append(line)

        if not filtered_lines:
            continue

        if output and output[-1] != "":
            output.append("")
        if keep_page_markers:
            output.append(PAGE_MARKER_RE.format(page=page_number))
            output.append("")
        output.extend(filtered_lines)

    output = _repair_soft_break_lines(output)

    while output and output[0] == "":
        output.pop(0)
    while output and output[-1] == "":
        output.pop()
    return "\n".join(output).strip() + "\n"


def repair_soft_page_breaks(text: str) -> str:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    repaired = _repair_soft_break_lines([_normalize_line(line) for line in lines])
    while repaired and repaired[0] == "":
        repaired.pop(0)
    while repaired and repaired[-1] == "":
        repaired.pop()
    if not repaired:
        return ""
    return "\n".join(repaired) + "\n"


def clean_rfc_page_lines(lines: Iterable[str]) -> List[str]:
    normalized_lines = [_normalize_line(line) for line in lines]
    trimmed = _trim_page_headers_and_footers(normalized_lines)
    return _collapse_blank_lines(trimmed)


def summarize_rfc_text(raw_text: str, cleaned_text: str) -> Dict[str, int]:
    return {
        "page_count": len(split_rfc_pages(raw_text)),
        "raw_character_count": len(raw_text),
        "cleaned_character_count": len(cleaned_text),
        "cleaned_line_count": len(cleaned_text.splitlines()),
    }


def _normalize_line(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = re.sub(r"[ \t]+", " ", normalized.rstrip())
    return normalized


def _trim_page_headers_and_footers(lines: List[str]) -> List[str]:
    start = 0
    end = len(lines)

    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1

    if start < end and PAGE_FOOTER_RE.match(lines[start].strip()):
        start += 1
        while start < end and not lines[start].strip():
            start += 1

    if start < end and PAGE_HEADER_RE.match(lines[start].strip()):
        start += 1
        while start < end and not lines[start].strip():
            start += 1

    while end > start and PAGE_FOOTER_RE.match(lines[end - 1].strip()):
        end -= 1
        while end > start and not lines[end - 1].strip():
            end -= 1

    return lines[start:end]


def _collapse_blank_lines(lines: List[str]) -> List[str]:
    collapsed: List[str] = []
    previous_blank = False
    for line in lines:
        if not line.strip():
            if not previous_blank:
                collapsed.append("")
            previous_blank = True
            continue
        collapsed.append(line.strip())
        previous_blank = False
    while collapsed and collapsed[0] == "":
        collapsed.pop(0)
    while collapsed and collapsed[-1] == "":
        collapsed.pop()
    return collapsed


def _looks_like_section_start(text: str) -> bool:
    if not text:
        return False
    return bool(re.match(r"^\d+(?:\.\d+)*\.?\s+\S", text))


def _repair_soft_break_lines(lines: List[str]) -> List[str]:
    repaired: List[str] = []
    previous_blank = False

    for index, line in enumerate(lines):
        if line.strip():
            repaired.append(line)
            previous_blank = False
            continue

        previous_text = _previous_content_line(lines, index - 1)
        next_text = _next_content_line(lines, index + 1)
        if _is_soft_blank_break(previous_text, next_text):
            continue

        if not previous_blank:
            repaired.append("")
        previous_blank = True

    return repaired


def _previous_content_line(lines: List[str], start_index: int) -> Optional[str]:
    for index in range(start_index, -1, -1):
        stripped = lines[index].strip()
        if not stripped or PAGE_MARKER_LINE_RE.match(stripped):
            continue
        return stripped
    return None


def _next_content_line(lines: List[str], start_index: int) -> Optional[str]:
    for line in lines[start_index:]:
        stripped = line.strip()
        if not stripped or PAGE_MARKER_LINE_RE.match(stripped):
            continue
        return stripped
    return None


def _is_soft_blank_break(previous_text: Optional[str], next_text: Optional[str]) -> bool:
    if not previous_text or not next_text:
        return False
    if _looks_like_new_block(next_text):
        return False
    if previous_text.endswith("-"):
        return True
    if next_text[:1].islower() or next_text[:1].isdigit():
        return True
    if not re.search(r"[.!?;:)]$", previous_text):
        return True
    return False


def _looks_like_new_block(text: str) -> bool:
    if not text:
        return False
    if SECTION_HEADING_RE.match(text):
        return True
    if APPENDIX_HEADING_RE.match(text):
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
