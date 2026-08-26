from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
from typing import List

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE_ROOT = os.path.dirname(PROJECT_ROOT)
sys.path.insert(0, WORKSPACE_ROOT)

from CertGuard.project_documents.json_store import write_json

from CertGuard.config.llm import (
    DEFAULT_LLM_API_KEY,
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_MODEL,
    DEFAULT_LLM_TEMPERATURE,
    DEFAULT_LLM_TIMEOUT,
)
from .aggregator import aggregate_mode_results
from .analyzer import run_chunk_analysis
from .context_builder import build_context_chunks
from .CertRetrieve import load_evidence_for_node, resolve_dataset_paths
from .verify import run_chunk_evaluation
from .report_writer import write_mode_reports


SUPPORTED_MODES = ("semantic_impact", "editorial_low_impact", "cross_document")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Detect paragraph-level issues for a structure node using linked standards text."
    )
    parser.add_argument(
        "command",
        choices=("inspect-node", "analyze-node"),
        help="Inspect context or run the full LLM-based detection pipeline.",
    )
    parser.add_argument("--node-id", required=True, help="Structure node id to analyze.")
    parser.add_argument(
        "--document-key",
        action="append",
        default=[],
        help="Document key to include. Can be provided multiple times. Default: RFC5280",
    )
    parser.add_argument(
        "--dataset",
        action="append",
        default=[],
        help="Explicit dataset JSON path. Can be provided multiple times.",
    )
    parser.add_argument(
        "--mode",
        default="all",
        choices=("all",) + SUPPORTED_MODES,
        help="Detection mode to run.",
    )
    parser.add_argument(
        "--link-types",
        default="direct_constraint,descriptive_definition,supporting_context",
        help="Comma-separated linked paragraph types to include.",
    )
    parser.add_argument("--max-evidence", type=int, default=None)
    parser.add_argument("--max-context-tokens", type=int, default=48000)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Build context and artifacts without calling the LLM.")
    parser.add_argument(
        "--output-root",
        default=os.path.join(PROJECT_ROOT, "results", "runs"),
        help="Directory for cache and final result artifacts.",
    )
    parser.add_argument("--llm-base-url", default=DEFAULT_LLM_BASE_URL)
    parser.add_argument("--llm-api-key", default=DEFAULT_LLM_API_KEY)
    parser.add_argument("--llm-model", default=DEFAULT_LLM_MODEL)
    parser.add_argument("--llm-timeout", type=float, default=DEFAULT_LLM_TIMEOUT)
    parser.add_argument("--llm-temperature", type=float, default=DEFAULT_LLM_TEMPERATURE)
    parser.add_argument("--llm-backend", choices=("openai", "genai"), default="openai")
    args = parser.parse_args()

    document_keys = args.document_key or ["RFC5280"]
    dataset_paths = resolve_dataset_paths(
        document_keys=document_keys,
        dataset_paths=args.dataset,
        project_root=PROJECT_ROOT,
    )
    link_types = [value.strip() for value in args.link_types.split(",") if value.strip()]
    evidences = load_evidence_for_node(
        node_id=args.node_id,
        dataset_paths=dataset_paths,
        link_types=link_types,
        max_evidence=args.max_evidence,
    )

    if not evidences:
        raise SystemExit("No linked paragraph evidence found for node: %s" % args.node_id)

    output_root = os.path.abspath(args.output_root)
    run_root = os.path.join(output_root, _document_slug(document_keys), _slugify(args.node_id))
    os.makedirs(run_root, exist_ok=True)
    _cleanup_legacy_run_artifacts(run_root)

    if args.command == "inspect-node":
        chunks = build_context_chunks(
            node_id=args.node_id,
            mode="semantic_impact",
            evidences=evidences,
            max_context_tokens=args.max_context_tokens,
        )
        write_json(
            os.path.join(run_root, "inspect_chunks.json"),
            {
                "node_id": args.node_id,
                "chunk_count": len(chunks),
                "chunks": [chunk.to_dict() for chunk in chunks],
            },
        )
        print(
            "Prepared %d evidence paragraphs into %d chunks for node %s."
            % (len(evidences), len(chunks), args.node_id)
        )
        return

    modes = list(SUPPORTED_MODES) if args.mode == "all" else [args.mode]

    for mode in modes:
        mode_root = os.path.join(run_root, mode)
        os.makedirs(mode_root, exist_ok=True)
        _cleanup_legacy_mode_artifacts(mode_root)

        if mode == "cross_document" and len(_documents_in_evidences(evidences)) < 2:
            result = {
                "node_id": args.node_id,
                "mode": mode,
                "summary": {
                    "evidence_count": len(evidences),
                    "chunk_count": 0,
                    "analyzer_call_count": 0,
                    "evaluator_call_count": 0,
                    "accepted_problem_count": 0,
                    "rejected_problem_count": 0,
                },
                "problems": [],
                "rejected": [],
            }
            write_mode_reports(
                mode_root=mode_root,
                mode=mode,
                result=result,
                analyses=[],
                evaluations=[],
            )
            print("[%s] skipped: fewer than two documents in evidence set" % mode)
            continue

        chunks = build_context_chunks(
            node_id=args.node_id,
            mode=mode,
            evidences=evidences,
            max_context_tokens=args.max_context_tokens,
        )

        if args.dry_run:
            result = {
                "node_id": args.node_id,
                "mode": mode,
                "summary": {
                    "evidence_count": len(evidences),
                    "chunk_count": len(chunks),
                    "analyzer_call_count": 0,
                    "evaluator_call_count": 0,
                    "accepted_problem_count": 0,
                    "rejected_problem_count": 0,
                },
                "problems": [],
                "rejected": [],
            }
            report_paths = write_mode_reports(
                mode_root=mode_root,
                mode=mode,
                result=result,
                analyses=[],
                evaluations=[],
            )
            continue

        analyses = run_chunk_analysis(
            chunks=chunks,
            mode=mode,
            base_url=args.llm_base_url,
            api_key=args.llm_api_key,
            model=args.llm_model,
            backend=args.llm_backend,
            timeout=args.llm_timeout,
            temperature=args.llm_temperature,
            cache_dir=os.path.join(mode_root, "analysis"),
            force=args.force,
        )
        evaluations = run_chunk_evaluation(
            chunks=chunks,
            analyses=analyses,
            mode=mode,
            base_url=args.llm_base_url,
            api_key=args.llm_api_key,
            model=args.llm_model,
            backend=args.llm_backend,
            timeout=args.llm_timeout,
            temperature=args.llm_temperature,
            cache_dir=os.path.join(mode_root, "evaluate"),
            force=args.force,
        )
        result = aggregate_mode_results(
            node_id=args.node_id,
            mode=mode,
            document_keys=document_keys,
            evidences=evidences,
            chunks=chunks,
            analyses=analyses,
            evaluations=evaluations,
        )
        write_mode_reports(
            mode_root=mode_root,
            mode=mode,
            result=result,
            analyses=analyses,
            evaluations=evaluations,
        )
        print(
            "[%s] accepted=%d rejected=%d chunks=%d"
            % (
                mode,
                result["summary"]["accepted_problem_count"],
                result["summary"]["rejected_problem_count"],
                result["summary"]["chunk_count"],
            )
        )


def _slugify(value: str) -> str:
    cleaned = []
    for character in value:
        if character.isalnum():
            cleaned.append(character)
        else:
            cleaned.append("_")
    slug = "".join(cleaned).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    if not slug:
        return "node"
    max_length = 48
    if len(slug) <= max_length:
        return slug
    digest = hashlib.sha1(slug.encode("utf-8")).hexdigest()[:10]
    suffix_length = max_length - len(digest) - 1
    suffix = slug[-suffix_length:].strip("_") or slug[-suffix_length:]
    return "%s_%s" % (digest, suffix)


def _document_slug(document_keys: List[str]) -> str:
    joined = "__".join(document_keys)
    return _slugify(joined)


def _documents_in_evidences(evidences) -> List[str]:
    return sorted({evidence.document_key for evidence in evidences})


def _cleanup_legacy_run_artifacts(run_root: str) -> None:
    for name in ("context_manifest.json", "summary.json", "final_index.json", "inspect_chunks.json"):
        path = os.path.join(run_root, name)
        if os.path.exists(path):
            os.remove(path)


def _cleanup_legacy_mode_artifacts(mode_root: str) -> None:
    legacy_paths = [
        os.path.join(mode_root, "evaluation"),
        os.path.join(mode_root, "chunks.json"),
    ]
    for path in legacy_paths:
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        elif os.path.isfile(path):
            os.remove(path)


if __name__ == "__main__":
    main()
