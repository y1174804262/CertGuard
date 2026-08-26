from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE_ROOT = os.path.dirname(PROJECT_ROOT)
sys.path.insert(0, WORKSPACE_ROOT)

from CertGuard.config.llm import (
    DEFAULT_LLM_API_KEY,
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_MODEL,
    DEFAULT_LLM_TEMPERATURE,
    DEFAULT_LLM_TIMEOUT,
)

from .aggregator import aggregate_mode_results
from .analyzer import run_chunk_analysis
from .context_builder import build_document_order_chunks
from .CertRetrieve import default_dataset_path, load_document_evidence
from .verify import run_chunk_evaluation
from .report_writer import write_mode_reports


MODE = "editorial_low_impact"


def main() -> None:
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("--config", default=None)
    pre_args, remaining_args = pre_parser.parse_known_args()
    config_defaults = _load_config_defaults(pre_args.config)

    parser = argparse.ArgumentParser(
        description="Run document-level editorial errata detection without structure-node filtering.",
        parents=[pre_parser],
    )
    parser.add_argument(
        "--document-key",
        action="append",
        default=config_defaults.get("document_keys", []),
        help="Document key to scan. Can be provided multiple times. Default: RFC5280.",
    )
    parser.add_argument(
        "--dataset",
        action="append",
        default=config_defaults.get("datasets", []),
        help="Explicit dataset JSON path. Can be provided multiple times.",
    )
    parser.add_argument("--max-context-tokens", type=int, default=config_defaults.get("max_context_tokens", 16000))
    parser.add_argument("--overlap-paragraphs", type=int, default=config_defaults.get("overlap_paragraphs", 2))
    parser.add_argument("--max-evidence", type=int, default=config_defaults.get("max_evidence"))
    parser.add_argument(
        "--chunk-index",
        type=int,
        default=config_defaults.get("chunk_index"),
        help="Run only one 1-based chunk index.",
    )
    parser.add_argument("--max-chunks", type=int, default=config_defaults.get("max_chunks"))
    parser.add_argument("--force", action="store_true", default=bool(config_defaults.get("force", False)))
    parser.add_argument("--dry-run", action="store_true", default=bool(config_defaults.get("dry_run", False)))
    parser.add_argument(
        "--output-root",
        default=config_defaults.get(
            "output_root",
            os.path.join(PROJECT_ROOT, "results", "runs", "editorial_document"),
        ),
    )
    parser.add_argument("--llm-base-url", default=config_defaults.get("llm_base_url", DEFAULT_LLM_BASE_URL))
    parser.add_argument("--llm-api-key", default=config_defaults.get("llm_api_key", DEFAULT_LLM_API_KEY))
    parser.add_argument("--llm-model", default=config_defaults.get("llm_model", DEFAULT_LLM_MODEL))
    parser.add_argument("--llm-timeout", type=float, default=config_defaults.get("llm_timeout", DEFAULT_LLM_TIMEOUT))
    parser.add_argument(
        "--llm-temperature",
        type=float,
        default=config_defaults.get("llm_temperature", DEFAULT_LLM_TEMPERATURE),
    )
    parser.add_argument("--llm-backend", choices=("openai", "genai"), default=config_defaults.get("llm_backend", "openai"))
    args = parser.parse_args(remaining_args)

    document_keys = args.document_key or ["RFC5280"]
    dataset_paths = _resolve_document_inputs(document_keys, args.dataset)

    for document_key, dataset_path in dataset_paths:
        evidences = load_document_evidence(
            dataset_path=dataset_path,
            max_evidence=args.max_evidence,
        )
        if not evidences:
            print("[%s] skipped: no paragraphs loaded from %s" % (document_key, dataset_path))
            continue

        chunks = build_document_order_chunks(
            document_key=document_key,
            mode=MODE,
            evidences=evidences,
            max_context_tokens=args.max_context_tokens,
            overlap_paragraphs=args.overlap_paragraphs,
        )
        if args.max_chunks is not None:
            chunks = chunks[: max(0, args.max_chunks)]
        if args.chunk_index is not None:
            if args.chunk_index < 1 or args.chunk_index > len(chunks):
                print(
                    "[%s] skipped: chunk-index %s outside 1..%d"
                    % (document_key, args.chunk_index, len(chunks))
                )
                continue
            chunks = [chunks[args.chunk_index - 1]]

        mode_root = os.path.join(os.path.abspath(args.output_root), document_key, MODE)
        os.makedirs(mode_root, exist_ok=True)

        if args.dry_run:
            result = _empty_result(document_key, evidences, chunks)
            write_mode_reports(mode_root, MODE, result, [], [])
            print(
                "[%s] dry-run paragraphs=%d chunks=%d"
                % (document_key, len(evidences), len(chunks))
            )
            continue

        analyses = run_chunk_analysis(
            chunks=chunks,
            mode=MODE,
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
            mode=MODE,
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
            node_id="document:%s" % document_key,
            mode=MODE,
            document_keys=[document_key],
            evidences=evidences,
            chunks=chunks,
            analyses=analyses,
            evaluations=evaluations,
        )
        write_mode_reports(mode_root, MODE, result, analyses, evaluations)
        print(
            "[%s] accepted=%d rejected=%d chunks=%d paragraphs=%d"
            % (
                document_key,
                result["summary"]["accepted_problem_count"],
                result["summary"]["rejected_problem_count"],
                result["summary"]["chunk_count"],
                result["summary"]["evidence_count"],
            )
        )


def _resolve_document_inputs(document_keys: List[str], dataset_paths: List[str]) -> List[tuple[str, str]]:
    resolved: List[tuple[str, str]] = []
    seen = set()
    for document_key in document_keys:
        path = os.path.abspath(default_dataset_path(document_key))
        if path not in seen:
            resolved.append((document_key, path))
            seen.add(path)
    for dataset_path in dataset_paths:
        path = dataset_path
        if not os.path.isabs(path):
            path = os.path.abspath(os.path.join(PROJECT_ROOT, path))
        document_key = _document_key_from_dataset_path(path)
        if path not in seen:
            resolved.append((document_key, path))
            seen.add(path)
    return resolved


def _load_config_defaults(config_path: str | None) -> Dict[str, Any]:
    if not config_path:
        return {}
    path = config_path
    if not os.path.isabs(path):
        path = os.path.join(PROJECT_ROOT, path)
    with open(path, "r", encoding="utf-8") as file:
        data = json.load(file)
    parameters = data.get("parameters", data)
    defaults: Dict[str, Any] = {}
    for key, value in parameters.items():
        if key.startswith("_"):
            continue
        if isinstance(value, dict) and "value" in value:
            defaults[key] = value["value"]
        else:
            defaults[key] = value
    return defaults


def _document_key_from_dataset_path(path: str) -> str:
    parent = os.path.basename(os.path.dirname(os.path.dirname(path)))
    return parent or os.path.splitext(os.path.basename(path))[0]


def _empty_result(document_key, evidences, chunks):
    return {
        "node_id": "document:%s" % document_key,
        "mode": MODE,
        "documents": [document_key],
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


if __name__ == "__main__":
    main()
