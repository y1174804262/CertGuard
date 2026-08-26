from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE_ROOT = os.path.dirname(PROJECT_ROOT)
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

from CertGuard.config.neo4j import load_neo4j_config

from CertGuard.CertGraph_PKI_Node.importer import import_structure_graphs_to_neo4j
from CertGuard.CertGraph_PKI_Node.normalize import normalize_structure_files


DEFAULT_X509_INPUT = os.path.join(PROJECT_ROOT, "data", "Certificate_json", "X509_KG_Nodes.json")
DEFAULT_CRL_INPUT = os.path.join(PROJECT_ROOT, "data", "Certificate_json", "CRL_KG_Nodes.json")
DEFAULT_X509_OUTPUT = os.path.join(PROJECT_ROOT, "data", "Certificate_json", "X509_KG_Nodes.normalized.json")
DEFAULT_CRL_OUTPUT = os.path.join(PROJECT_ROOT, "data", "Certificate_json", "CRL_KG_Nodes.normalized.json")


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description="Normalize certificate/CRL node JSON files and upload them to Neo4j."
    )
    parser.add_argument("--x509-input", default=DEFAULT_X509_INPUT, help="Path to the source X509 node JSON file.")
    parser.add_argument("--crl-input", default=DEFAULT_CRL_INPUT, help="Path to the source CRL node JSON file.")
    parser.add_argument("--x509-output", default=DEFAULT_X509_OUTPUT, help="Path to the normalized X509 node JSON file.")
    parser.add_argument("--crl-output", default=DEFAULT_CRL_OUTPUT, help="Path to the normalized CRL node JSON file.")
    parser.add_argument("--skip-normalize", action="store_true", help="Import the given input files directly without writing normalized outputs first.")
    parser.add_argument("--neo4j-uri", default="bolt://localhost:7687", help="Neo4j URI. Defaults to NEO4J_URI or bolt://localhost:7687.")
    parser.add_argument("--neo4j-username", default="neo4j", help="Neo4j username. Defaults to NEO4J_USERNAME or neo4j.")
    parser.add_argument("--neo4j-password", default="123", help="Neo4j password. Defaults to NEO4J_PASSWORD or password.")
    parser.add_argument("--database", default=None, help="Neo4j database name. Defaults to NEO4J_DATABASE.")
    parser.add_argument("--clear-existing", action="store_true", help="Delete existing StructureNode nodes before import.")
    args = parser.parse_args(argv)

    x509_input = resolve_project_path(args.x509_input)
    crl_input = resolve_project_path(args.crl_input)
    x509_output = resolve_project_path(args.x509_output)
    crl_output = resolve_project_path(args.crl_output)

    if args.skip_normalize:
        certificate_json = x509_input
        crl_json = crl_input
    else:
        outputs = normalize_structure_files(
            x509_input=x509_input,
            crl_input=crl_input,
            x509_output=x509_output,
            crl_output=crl_output,
        )
        certificate_json = outputs["x509_output"]
        crl_json = outputs["crl_output"]
        print("Wrote normalized files:")
        print(certificate_json)
        print(crl_json)

    config = load_neo4j_config(
        uri=args.neo4j_uri,
        username=args.neo4j_username,
        password=args.neo4j_password,
        database=args.database,
    )

    summary = import_structure_graphs_to_neo4j(
        uri=config.uri,
        username=config.username,
        password=config.password,
        database=config.database,
        graph_specs=[
            (certificate_json, "certificate"),
            (crl_json, "crl"),
        ],
        clear_existing=args.clear_existing,
    )
    print("Imported %(nodes)d structure nodes and %(relationships)d relationships." % summary)


def resolve_project_path(path: str) -> str:
    if os.path.isabs(path):
        return path
    return os.path.abspath(os.path.join(PROJECT_ROOT, path))


if __name__ == "__main__":
    main()
