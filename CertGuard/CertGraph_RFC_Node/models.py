from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class Paragraph:
    id: str
    text: str
    order: int


@dataclass
class Section:
    id: str
    number: str
    title: str
    order: int
    paragraphs: List[Paragraph] = field(default_factory=list)
    subsections: List["Section"] = field(default_factory=list)


@dataclass
class RfcDocument:
    id: str
    title: str
    sections: List[Section] = field(default_factory=list)
