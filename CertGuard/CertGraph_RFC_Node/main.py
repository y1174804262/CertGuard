from __future__ import annotations

import argparse
import os
import sys
from typing import Optional


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE_ROOT = os.path.dirname(PROJECT_ROOT)
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

from CertGuard.config.neo4j import load_neo4j_config
from CertGuard.project_documents.paths import DEFAULT_DOCUMENT_KEY, PROJECT_ROOT, document_file, normalize_document_key
from CertGuard.CertGraph_RFC_Node.importer import Neo4jRfcStore, document_summary
from CertGuard.CertGraph_RFC_Node.parser import parse_rfc_file

import json


def resolve_default_rfc_file(document_key: str) -> str:
    registry_path = os.path.join(PROJECT_ROOT, "data", "document_registry.json")
    normalized_key = normalize_document_key(document_key)

    try:
        with open(registry_path, "r", encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, json.JSONDecodeError):
        payload = {}

    documents = payload.get("documents") if isinstance(payload, dict) else None
    if isinstance(documents, list):
        for item in documents:
            if not isinstance(item, dict):
                continue
            if normalize_document_key(str(item.get("document_key") or "")) != normalized_key:
                continue
            cleaned = item.get("cleaned_text_file")
            if isinstance(cleaned, str) and cleaned.strip():
                candidate = cleaned
                if not os.path.isabs(candidate):
                    candidate = os.path.join(PROJECT_ROOT, candidate)
                candidate = os.path.abspath(candidate)
                if os.path.exists(candidate):
                    return candidate

    return document_file(document_key, "cleaned.txt")


DEFAULT_RFC_FILE = resolve_default_rfc_file(DEFAULT_DOCUMENT_KEY)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import an RFC txt file into Neo4j.")
    parser.add_argument("--file", default=DEFAULT_RFC_FILE, help="Path to the RFC txt file.")
    parser.add_argument("--rfc-id", default="rfc5280", help="Stable RFC id, for example rfc5280.")
    parser.add_argument(
        "--title",
        help="Document title. Defaults to the first non-empty line of the RFC txt file.",
    )
    parser.add_argument("--database", default=None, help="Neo4j database name. Defaults to NEO4J_DATABASE.")
    parser.add_argument("--neo4j-uri", default="bolt://localhost:7687", help="Neo4j URI. Defaults to NEO4J_URI or bolt://localhost:7687.")
    parser.add_argument("--neo4j-username", default="neo4j", help="Neo4j username. Defaults to NEO4J_USERNAME or neo4j.")
    parser.add_argument("--neo4j-password", default="123", help="Neo4j password. Defaults to NEO4J_PASSWORD or password.")
    parser.add_argument(
        "--clear-existing",
        action="store_true",
        help="Delete existing nodes for this RFC before import.",
    )
    parser.add_argument(
        "--clear-database",
        action="store_true",
        help="Delete all nodes and relationships in the target Neo4j database before import.",
    )
    parser.add_argument(
        "--create-next-relationships",
        action="store_true",
        help="Create Paragraph -[:NEXT]-> Paragraph relationships within each Section.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and print a summary without writing to Neo4j.",
    )
    parser.add_argument(
        "--encoding",
        default="utf-8",
        help="Input file encoding. Defaults to utf-8.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    document = parse_rfc_file(
        args.file,
        rfc_id=args.rfc_id,
        title=args.title,
        encoding=args.encoding,
    )
    summary = document_summary(document)

    if args.dry_run:
        print(
            "Parsed %s: %d sections, %d paragraphs."
            % (document.id, summary["sections"], summary["paragraphs"])
        )
        return

    config = load_neo4j_config(
        uri=args.neo4j_uri,
        username=args.neo4j_username,
        password=args.neo4j_password,
        database=args.database,
    )
    store = Neo4jRfcStore(
        uri=config.uri,
        username=config.username,
        password=config.password,
        database=config.database,
    )
    try:
        if args.clear_database:
            store.clear_database()
        store.import_document(
            document,
            clear_existing=args.clear_existing,
            create_next_relationships=args.create_next_relationships,
        )
    finally:
        store.close()

    print(
        "Imported %s: %d sections, %d paragraphs."
        % (document.id, summary["sections"], summary["paragraphs"])
    )


if __name__ == "__main__":
    main()
