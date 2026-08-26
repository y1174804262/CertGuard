from __future__ import annotations

import argparse
import os
import re
import sys
from typing import Optional

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE_ROOT = os.path.dirname(PROJECT_ROOT)
sys.path.insert(0, WORKSPACE_ROOT)

from CertGuard.CertGraph_RFC2Certificate.graph import import_paragraph_structure_links_from_dataset
from CertGuard.CertGraph_RFC2Certificate.llm_linker import process_linking_dataset_with_llm
from CertGuard.CertGraph_RFC2Certificate.retriever import export_linking_dataset_from_neo4j
from CertGuard.config.neo4j import load_neo4j_config
from CertGuard.project_documents.paths import DEFAULT_DOCUMENT_KEY, document_dir, normalize_document_key

RFC2CERT_DEFAULT_LLM_BASE_URL = "https://api.siliconflow.cn/v1"
RFC2CERT_DEFAULT_LLM_API_KEY = "sk-vcbgcrxpzuffndhwvopcwjmamizfxknqygmfajeoqxraidcw"
RFC2CERT_DEFAULT_LLM_MODEL = "deepseek-ai/DeepSeek-R1-0528-Qwen3-8B"
RFC2CERT_DEFAULT_LLM_TIMEOUT = 120.0
RFC2CERT_DEFAULT_LLM_TEMPERATURE = 0.0
RFC2CERT_DEFAULT_MAX_USER_PROMPT_TOKENS = 120000


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Link RFC paragraphs to certificate or CRL structure nodes."
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=("export", "run-llm", "import", "all"),
        default="all",
        help="Pipeline step to execute.",
    )
    parser.add_argument(
        "--document-key",
        default=DEFAULT_DOCUMENT_KEY,
        help="Document key used for default dataset and artifact paths.",
    )
    parser.add_argument(
        "--rfc-id",
        default=None,
        help="RFC node id in Neo4j. Defaults to an inferred value such as rfc5280.",
    )
    parser.add_argument("--dataset", default=None, help="Dataset JSON path.")
    parser.add_argument("--neo4j-uri", default="bolt://localhost:7687")
    parser.add_argument("--neo4j-username", default="neo4j")
    parser.add_argument("--neo4j-password", default="123")
    parser.add_argument("--database", default=None)
    parser.add_argument("--previous-count", type=int, default=1)
    parser.add_argument("--next-count", type=int, default=1)
    parser.add_argument("--intro-count", type=int, default=1)
    parser.add_argument("--candidate-limit", type=int, default=10)
    parser.add_argument("--clear-existing", action="store_true")
    parser.add_argument("--reset-existing", action="store_true")
    parser.add_argument("--llm-base-url", default=RFC2CERT_DEFAULT_LLM_BASE_URL)
    parser.add_argument("--llm-api-key", default=RFC2CERT_DEFAULT_LLM_API_KEY)
    parser.add_argument("--llm-model", default=RFC2CERT_DEFAULT_LLM_MODEL)
    parser.add_argument("--llm-timeout", type=float, default=RFC2CERT_DEFAULT_LLM_TIMEOUT)
    parser.add_argument("--llm-temperature", type=float, default=RFC2CERT_DEFAULT_LLM_TEMPERATURE)
    parser.add_argument("--llm-backend", choices=("openai", "genai"), default="openai")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--max-user-prompt-tokens",
        type=int,
        default=RFC2CERT_DEFAULT_MAX_USER_PROMPT_TOKENS,
        help="Maximum token budget for the LLM user prompt.",
    )
    args = parser.parse_args()

    config = load_neo4j_config(
        uri=args.neo4j_uri,
        username=args.neo4j_username,
        password=args.neo4j_password,
        database=args.database,
    )
    rfc_id = args.rfc_id or infer_rfc_id(args.document_key)
    dataset_path = resolve_dataset_path(args.document_key, args.dataset)
    responses_dir = os.path.join(os.path.dirname(dataset_path), "responses")
    errors_dir = os.path.join(os.path.dirname(dataset_path), "errors")

    if args.command in {"export", "all"}:
        dataset = export_linking_dataset_from_neo4j(
            uri=config.uri,
            username=config.username,
            password=config.password,
            database=config.database,
            rfc_id=rfc_id,
            output_path=dataset_path,
            previous_count=args.previous_count,
            next_count=args.next_count,
            intro_count=args.intro_count,
            candidate_limit=args.candidate_limit,
            preserve_existing=not args.reset_existing,
        )
        print(
            "Exported %d paragraph linking items to %s."
            % (len(dataset.get("items", [])), dataset_path)
        )

    if args.command in {"run-llm", "all"}:
        summary = process_linking_dataset_with_llm(
            dataset_path=dataset_path,
            base_url=args.llm_base_url,
            api_key=args.llm_api_key,
            model=args.llm_model,
            backend=args.llm_backend,
            limit=args.limit,
            force=args.force,
            timeout=args.llm_timeout,
            temperature=args.llm_temperature,
            response_dir=responses_dir,
            error_dir=errors_dir,
            max_user_prompt_tokens=args.max_user_prompt_tokens,
        )
        print(
            "LLM processed %(processed)d items (attempted=%(attempted)d, skipped=%(skipped)d, "
            "auto_completed=%(auto_completed)d, errors=%(errors)d)."
            % summary
        )

    if args.command in {"import", "all"}:
        summary = import_paragraph_structure_links_from_dataset(
            uri=config.uri,
            username=config.username,
            password=config.password,
            database=config.database,
            dataset_path=dataset_path,
            clear_existing=args.clear_existing,
            write_back=True,
        )
        print(
            "Imported %(imported_links)d paragraph-to-structure links from %(imported_items)d items."
            % summary
        )


def infer_rfc_id(document_key: str) -> str:
    match = re.search(r"(\d+)", document_key)
    if match:
        return "rfc%s" % match.group(1)
    raise ValueError("Unable to infer --rfc-id from document key: %s" % document_key)


def resolve_dataset_path(document_key: str, dataset_path: Optional[str]) -> str:
    if dataset_path:
        if os.path.isabs(dataset_path):
            return dataset_path
        return os.path.abspath(os.path.join(PROJECT_ROOT, dataset_path))

    key = normalize_document_key(document_key)
    base_dir = os.path.join(document_dir(key), "rfc2certificate")
    os.makedirs(base_dir, exist_ok=True)
    return os.path.join(base_dir, "%s_paragraph_node_linking_dataset.json" % key)


if __name__ == "__main__":
    main()
