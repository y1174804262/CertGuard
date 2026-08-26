from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import List


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS_ROOT = PROJECT_ROOT / "results" / "runs" / "RFC5280"
DEFAULT_OUTPUT = PROJECT_ROOT / "results" / "RFC5280_all_final_reports.md"


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge all final.md reports without filtering.")
    parser.add_argument("--results-root", default=str(DEFAULT_RESULTS_ROOT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    results_root = Path(args.results_root).resolve()
    output_path = Path(args.output).resolve()
    final_paths = _final_report_paths(results_root)
    content = _render_merged_report(results_root, final_paths)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    print("Merged %d final.md files into %s" % (len(final_paths), output_path))


def _final_report_paths(results_root: Path) -> List[Path]:
    mode_order = {"semantic_impact": 0, "editorial_low_impact": 1, "cross_document": 2}
    paths = [
        path
        for path in results_root.glob("*/**/final.md")
        if path.parent.name in mode_order
    ]
    return sorted(
        paths,
        key=lambda path: (
            path.parent.parent.name.lower(),
            mode_order.get(path.parent.name, 99),
            str(path).lower(),
        ),
    )


def _render_merged_report(results_root: Path, final_paths: List[Path]) -> str:
    lines: List[str] = []
    lines.append("# RFC5280 All Final Reports")
    lines.append("")
    lines.append("- Results root: `%s`" % results_root)
    lines.append("- Merged final.md files: `%d`" % len(final_paths))
    lines.append("")
    lines.append("## Table of Contents")
    lines.append("")
    for index, path in enumerate(final_paths, start=1):
        node = _extract_field(path, r"- Node: `([^`]+)`") or path.parent.parent.name
        mode = _extract_field(path, r"- Mode: `([^`]+)`") or path.parent.name
        accepted = _extract_field(path, r"- Accepted findings: ([0-9]+)") or "0"
        rejected = _extract_field(path, r"- Rejected findings: ([0-9]+)") or "0"
        lines.append(
            "%d. `%s` / `%s` / accepted=%s / rejected=%s"
            % (index, node, mode, accepted, rejected)
        )
    lines.append("")
    lines.append("---")
    lines.append("")

    for index, path in enumerate(final_paths, start=1):
        raw = path.read_text(encoding="utf-8").strip()
        node = _extract_field(path, r"- Node: `([^`]+)`") or path.parent.parent.name
        mode = _extract_field(path, r"- Mode: `([^`]+)`") or path.parent.name
        lines.append("## Report %d: `%s` / `%s`" % (index, node, mode))
        lines.append("")
        lines.append("- Source file: `%s`" % path)
        lines.append("")
        lines.append(_demote_headings(raw))
        lines.append("")
        lines.append("---")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _extract_field(path: Path, pattern: str) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(pattern, text)
    return match.group(1) if match else ""


def _demote_headings(markdown: str) -> str:
    lines = []
    for line in markdown.splitlines():
        if line.startswith("#"):
            lines.append("##" + line)
        else:
            lines.append(line)
    return "\n".join(lines)


if __name__ == "__main__":
    main()
