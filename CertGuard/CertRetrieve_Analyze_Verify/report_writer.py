from __future__ import annotations

import os
from typing import Any, Dict, List, Sequence

from CertGuard.project_documents.json_store import write_json


def write_mode_reports(
    mode_root: str,
    mode: str,
    result: Dict[str, Any],
    analyses: Sequence[Dict[str, Any]],
    evaluations: Sequence[Dict[str, Any]],
) -> Dict[str, str]:
    paths: Dict[str, str] = {}

    analysis_md = render_analysis_markdown(result, analyses)
    evaluation_md = render_evaluation_markdown(result, evaluations)
    final_md = render_final_report_markdown(result)
    final_json = build_public_final_json(result)

    analysis_dir = os.path.join(mode_root, "analysis")
    evaluation_dir = os.path.join(mode_root, "evaluate")
    analysis_path = os.path.join(analysis_dir, "analysis.md")
    evaluation_path = os.path.join(evaluation_dir, "evaluate.md")
    final_md_path = os.path.join(mode_root, "final.md")
    final_json_path = os.path.join(mode_root, "final.json")

    _write_text(analysis_path, analysis_md)
    _write_text(evaluation_path, evaluation_md)
    _write_text(final_md_path, final_md)
    write_json(final_json_path, final_json)
    _copy_chunk_jsons(analyses, analysis_dir)
    _copy_chunk_jsons(evaluations, evaluation_dir)

    paths["analysis_md"] = analysis_path
    paths["evaluate_md"] = evaluation_path
    paths["final_md"] = final_md_path
    paths["final_json"] = final_json_path
    return paths


def render_analysis_markdown(
    result: Dict[str, Any],
    analyses: Sequence[Dict[str, Any]],
) -> str:
    lines: List[str] = []
    lines.append("# Analysis")
    lines.append("")
    lines.append("- Node: `%s`" % result.get("node_id"))
    lines.append("- Mode: `%s`" % result.get("mode"))
    lines.append("")

    for artifact in analyses:
        chunk_id = artifact.get("chunk_id") or "<unknown>"
        parsed = artifact.get("parsed") or {}
        lines.append("## %s" % chunk_id)
        lines.append("")
        if parsed.get("overall_note"):
            lines.append(parsed["overall_note"])
            lines.append("")
        problems = parsed.get("problems") or []
        if not problems:
            lines.append("No findings reported by analyzer.")
            lines.append("")
            continue
        for index, problem in enumerate(problems, start=1):
            lines.append("### Finding %d: %s" % (index, problem.get("title") or "<untitled>"))
            lines.append("")
            lines.append("- Paragraph IDs: `%s`" % "`, `".join(problem.get("paragraph_ids") or []))
            lines.append("- Reason: %s" % (problem.get("reason") or ""))
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def build_run_summary(
    node_id: str,
    document_keys: Sequence[str],
    mode_results: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    summary = {
        "node_id": node_id,
        "documents": list(document_keys),
        "modes": [],
        "accepted_findings": [],
    }
    for mode_result in mode_results:
        mode = mode_result.get("mode") or "<unknown>"
        mode_summary = mode_result.get("summary") or {}
        summary["modes"].append(
            {
                "mode": mode,
                "accepted_problem_count": mode_summary.get("accepted_problem_count", 0),
                "rejected_problem_count": mode_summary.get("rejected_problem_count", 0),
                "chunk_count": mode_summary.get("chunk_count", 0),
            }
        )
        for problem in mode_result.get("problems") or []:
            summary["accepted_findings"].append(
                {
                    "mode": mode,
                    "texts": [paragraph.get("text") or "" for paragraph in (problem.get("paragraphs") or [])],
                    "reason": problem.get("reason"),
                }
            )
    return summary


def build_public_final_json(result: Dict[str, Any]) -> Dict[str, Any]:
    problems = []
    if result.get("mode") == "cross_document":
        for problem in result.get("problems") or []:
            problems.append(
                {
                    "texts": [paragraph.get("text") or "" for paragraph in (problem.get("paragraphs") or [])],
                    "reason": problem.get("reason") or "",
                }
            )
        return {"problems": problems}

    for problem in result.get("problems") or []:
        paragraphs = problem.get("paragraphs") or []
        problems.append(
            {
                "documents": sorted(
                    {
                        paragraph.get("document") or ""
                        for paragraph in paragraphs
                        if paragraph.get("document")
                    }
                ),
                "paragraphs": [
                    {
                        "document": paragraph.get("document") or "",
                        "section": paragraph.get("section") or "",
                        "text": paragraph.get("text") or "",
                    }
                    for paragraph in paragraphs
                ],
                "texts": [paragraph.get("text") or "" for paragraph in paragraphs],
                "reason": problem.get("reason") or "",
            }
        )
    return {"problems": problems}


def render_evaluation_markdown(
    result: Dict[str, Any],
    evaluations: Sequence[Dict[str, Any]],
) -> str:
    lines: List[str] = []
    lines.append("# Evaluation")
    lines.append("")
    lines.append("- Node: `%s`" % result.get("node_id"))
    lines.append("- Mode: `%s`" % result.get("mode"))
    lines.append("")

    for artifact in evaluations:
        chunk_id = artifact.get("chunk_id") or "<unknown>"
        parsed = artifact.get("parsed") or {}
        lines.append("## %s" % chunk_id)
        lines.append("")
        if parsed.get("overall_note"):
            lines.append(parsed["overall_note"])
            lines.append("")

        accepted = parsed.get("accepted") or []
        rejected = parsed.get("rejected") or []

        if accepted:
            lines.append("### Accepted")
            lines.append("")
            for finding in accepted:
                lines.append("- **%s**" % (finding.get("title") or "<untitled>"))
                lines.append("  - Paragraph IDs: `%s`" % "`, `".join(finding.get("paragraph_ids") or []))
                lines.append("  - Reason: %s" % (finding.get("reason") or ""))
            lines.append("")

        if rejected:
            lines.append("### Rejected")
            lines.append("")
            for finding in rejected:
                lines.append("- **%s**" % (finding.get("title") or "<untitled>"))
                lines.append("  - Reason: %s" % (finding.get("reason") or ""))
            lines.append("")

        if not accepted and not rejected:
            lines.append("No findings to evaluate.")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_final_report_markdown(result: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# Final Report")
    lines.append("")
    lines.append("- Node: `%s`" % result.get("node_id"))
    lines.append("- Mode: `%s`" % result.get("mode"))
    lines.append("")

    summary = result.get("summary") or {}
    lines.append("## Summary")
    lines.append("")
    lines.append("- Evidence paragraphs: %s" % summary.get("evidence_count", 0))
    lines.append("- Chunks: %s" % summary.get("chunk_count", 0))
    lines.append("- Analyzer calls: %s" % summary.get("analyzer_call_count", 0))
    lines.append("- Evaluator calls: %s" % summary.get("evaluator_call_count", 0))
    lines.append("- Accepted findings: %s" % summary.get("accepted_problem_count", 0))
    lines.append("- Rejected findings: %s" % summary.get("rejected_problem_count", 0))
    lines.append("")

    problems = result.get("problems") or []
    if problems:
        lines.append("## Accepted Findings")
        lines.append("")
        for index, problem in enumerate(problems, start=1):
            lines.extend(
                _problem_markdown(
                    problem,
                    index,
                    include_document=result.get("mode") != "cross_document",
                )
            )
            lines.append("")
    else:
        lines.append("## Accepted Findings")
        lines.append("")
        lines.append("No accepted findings.")
        lines.append("")

    rejected = result.get("rejected") or []
    if rejected:
        lines.append("## Rejected Findings")
        lines.append("")
        for index, finding in enumerate(rejected, start=1):
            lines.append("### Rejected %d: %s" % (index, finding.get("title") or "<untitled>"))
            lines.append("")
            lines.append(finding.get("reason") or "")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _problem_markdown(
    problem: Dict[str, Any],
    index: int,
    include_document: bool = False,
) -> List[str]:
    lines: List[str] = []
    lines.append("### Finding %d: %s" % (index, problem.get("title") or "<untitled>"))
    lines.append("")
    paragraphs = problem.get("paragraphs") or []
    if paragraphs:
        section_labels = []
        for paragraph in paragraphs:
            section = paragraph.get("section")
            if section and section not in section_labels:
                section_labels.append(section)
        if section_labels:
            lines.append("- Sections: `%s`" % "`, `".join(section_labels))
    lines.append("")
    lines.append("#### Problematic Text")
    lines.append("")
    for paragraph in paragraphs:
        label_parts = []
        if include_document and paragraph.get("document"):
            label_parts.append(paragraph.get("document"))
        label_parts.append(paragraph.get("section") or "<unknown section>")
        lines.append("**%s**" % " - ".join(label_parts))
        lines.append("")
        lines.append("> %s" % (paragraph.get("text") or "").replace("\n", "\n> "))
        lines.append("")
    lines.append("#### Explanation")
    lines.append("")
    lines.append(problem.get("reason") or "")
    return lines


def _mode_title(mode: str) -> str:
    if mode == "semantic_impact":
        return "Semantic / Implementation-Impacting Issues"
    if mode == "editorial_low_impact":
        return "Editorial / Low-Impact Issues"
    if mode == "inconsistency":
        return "Inconsistencies"
    if mode == "underspecification":
        return "Underspecifications"
    if mode == "cross_document":
        return "Cross-Document Mismatches"
    return mode


def _write_text(path: str, content: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        file.write(content)


def _copy_chunk_jsons(artifacts: Sequence[Dict[str, Any]], target_dir: str) -> None:
    os.makedirs(target_dir, exist_ok=True)
    for artifact in artifacts:
        chunk_id = artifact.get("chunk_id")
        if not chunk_id:
            continue
        write_json(os.path.join(target_dir, "%s.json" % chunk_id), artifact)
