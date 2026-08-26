from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]

from CertGuard.project_documents.paths import document_dir, normalize_document_key
from .main import _document_slug, _slugify


def main() -> None:
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("--config", default=None)
    pre_args, remaining_args = pre_parser.parse_known_args()
    config_defaults = _load_config_defaults(pre_args.config)

    parser = argparse.ArgumentParser(
        description="Batch-run inconsistency detection by structure node.",
        parents=[pre_parser],
    )
    parser.add_argument("--document-key", action="append", default=config_defaults.get("document_keys", []))
    parser.add_argument("--dataset", action="append", default=config_defaults.get("datasets", []))
    parser.add_argument(
        "--batch-index",
        type=int,
        default=config_defaults.get("batch_index", 0),
        help="Zero-based batch index.",
    )
    parser.add_argument("--batch-size", type=int, default=config_defaults.get("batch_size", 50))
    parser.add_argument("--mode", default=config_defaults.get("mode", "all"))
    parser.add_argument(
        "--max-context-tokens",
        type=int,
        default=config_defaults.get("max_context_tokens", 48000),
    )
    parser.add_argument("--llm-timeout", type=float, default=config_defaults.get("llm_timeout", 300.0))
    parser.add_argument("--workers", type=int, default=config_defaults.get("workers", 1))
    parser.add_argument(
        "--output-root",
        default=config_defaults.get(
            "output_root",
            str(PROJECT_ROOT / "results" / "runs"),
        ),
    )
    parser.add_argument("--force", action="store_true", default=bool(config_defaults.get("force", False)))
    args = parser.parse_args(remaining_args)

    document_keys = args.document_key or ["RFC5280"]
    dataset_paths = _resolve_dataset_paths(document_keys, args.dataset)
    nodes = _linked_nodes(dataset_paths)
    start = args.batch_index * args.batch_size
    end = start + args.batch_size
    batch_nodes = nodes[start:end]

    output_root = Path(args.output_root).resolve()
    log_dir = output_root / "_batch_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / ("batch_%03d.jsonl" % args.batch_index)

    print(
        "Batch %d: nodes %d-%d of %d"
        % (args.batch_index, start + 1, min(end, len(nodes)), len(nodes))
    )
    if not batch_nodes:
        print("No nodes in this batch.")
        return

    tasks = []
    skipped = 0
    for offset, node_id in enumerate(batch_nodes, start=1):
        ordinal = start + offset
        if not args.force and _node_has_final_outputs(
            node_id=node_id,
            document_keys=document_keys,
            output_root=output_root,
            mode=args.mode,
        ):
            skipped += 1
            _write_log(log_path, node_id, "skipped", "final outputs already exist")
            print("[%d/%d] skipped %s" % (ordinal, len(nodes), node_id))
            continue

        command = [
            sys.executable,
            "-m",
            "CertGuard.CertRetrieve_Analyze_Verify.main",
            "analyze-node",
            "--node-id",
            node_id,
            "--mode",
            args.mode,
            "--max-context-tokens",
            str(args.max_context_tokens),
            "--llm-timeout",
            str(args.llm_timeout),
            "--output-root",
            str(output_root),
        ]
        for document_key in document_keys:
            command.extend(["--document-key", document_key])
        for dataset_path in args.dataset:
            command.extend(["--dataset", dataset_path])
        if args.force:
            command.append("--force")

        tasks.append(
            {
                "ordinal": ordinal,
                "total": len(nodes),
                "node_id": node_id,
                "command": command,
            }
        )

    completed = 0
    failed = 0
    worker_count = max(1, args.workers)
    if worker_count == 1:
        for task in tasks:
            payload = _run_node_task(task)
            _write_log(log_path, task["node_id"], payload["status"], payload)
            if payload["status"] == "completed":
                completed += 1
            else:
                failed += 1
                print((payload.get("stderr") or payload.get("stdout") or "").strip())
    else:
        print("Running with %d workers." % worker_count)
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [executor.submit(_run_node_task, task) for task in tasks]
            for future in as_completed(futures):
                payload = future.result()
                _write_log(log_path, payload["node_id"], payload["status"], payload)
                if payload["status"] == "completed":
                    completed += 1
                else:
                    failed += 1
                    print((payload.get("stderr") or payload.get("stdout") or "").strip())

    print(
        "Batch %d done: completed=%d skipped=%d failed=%d"
        % (args.batch_index, completed, skipped, failed)
    )


def _resolve_dataset_paths(document_keys: Sequence[str], dataset_paths: Sequence[str]) -> List[Path]:
    paths: List[Path] = []
    seen = set()
    for document_key in document_keys:
        key = normalize_document_key(document_key)
        path = Path(document_dir(key)) / "rfc2certificate" / ("%s_paragraph_node_linking_dataset.json" % key)
        if path not in seen:
            paths.append(path)
            seen.add(path)
    for dataset_path in dataset_paths:
        path = Path(dataset_path)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        if path not in seen:
            paths.append(path)
            seen.add(path)
    return paths


def _load_config_defaults(config_path: str | None) -> Dict[str, object]:
    if not config_path:
        return {}
    path = Path(config_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    data = json.loads(path.read_text(encoding="utf-8"))
    parameters = data.get("parameters", data)
    defaults: Dict[str, object] = {}
    for key, value in parameters.items():
        if key.startswith("_"):
            continue
        if isinstance(value, dict) and "value" in value:
            defaults[key] = value["value"]
        else:
            defaults[key] = value
    return defaults


def _linked_nodes(dataset_paths: Sequence[Path]) -> List[str]:
    total: Counter[str] = Counter()
    direct: Counter[str] = Counter()
    for path in dataset_paths:
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for item in data.get("items", []):
            for link in (item.get("llm_result") or {}).get("links") or []:
                node_id = link.get("node_id")
                if not node_id:
                    continue
                total[node_id] += 1
                if link.get("link_type") == "direct_constraint":
                    direct[node_id] += 1
    return sorted(total, key=lambda node: (-direct[node], -total[node], node))


def _run_node_task(task: Dict[str, object]) -> Dict[str, object]:
    ordinal = int(task["ordinal"])
    total = int(task["total"])
    node_id = str(task["node_id"])
    command = list(task["command"])  # type: ignore[arg-type]
    print("[%d/%d] running %s" % (ordinal, total, node_id))
    result = subprocess.run(
        command,
        cwd=str(PROJECT_ROOT.parent),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    status = "completed" if result.returncode == 0 else "failed"
    print("[%d/%d] %s %s" % (ordinal, total, status, node_id))
    return {
        "node_id": node_id,
        "status": status,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _node_has_final_outputs(
    node_id: str,
    document_keys: Sequence[str],
    output_root: Path,
    mode: str,
) -> bool:
    run_root = output_root / _document_slug(list(document_keys)) / _slugify(node_id)
    modes = ("semantic_impact", "editorial_low_impact", "cross_document") if mode == "all" else (mode,)
    return all((run_root / item / "final.json").exists() for item in modes)


def _write_log(path: Path, node_id: str, status: str, payload) -> None:
    record = {
        "time": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "node_id": node_id,
        "status": status,
        "payload": payload,
    }
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
