from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from neo4j import GraphDatabase

from .models import RELATES_TO_STRUCTURE
from CertGuard.project_documents.json_store import read_json, write_json


STRUCTURE_REL_TYPES = ("HAS_FIELD", "HAS_VALUE", "HAS_TYPE", "HAS_ABS_FIELD")


def load_rfc_document_records(
    uri: str,
    username: str,
    password: str,
    database: Optional[str],
    rfc_id: str,
) -> Dict[str, Any]:
    driver = GraphDatabase.driver(uri, auth=(username, password))
    try:
        rfc_record = _run_single(
            driver,
            database,
            "MATCH (r:RFC {id: $rfc_id}) RETURN r.id AS id, r.title AS title",
            rfc_id=rfc_id,
        )
        if rfc_record is None:
            raise ValueError("RFC not found in Neo4j: %s" % rfc_id)

        section_records = _run_data(
            driver,
            database,
            """
            MATCH (s:Section {rfc_id: $rfc_id})
            RETURN s.id AS id, s.number AS number, s.title AS title, s.order AS order
            ORDER BY s.order
            """,
            rfc_id=rfc_id,
        )
        section_edges = _run_data(
            driver,
            database,
            """
            MATCH (parent:Section)-[:HAS_SUBSECTION]->(child:Section)
            WHERE parent.rfc_id = $rfc_id AND child.rfc_id = $rfc_id
            RETURN parent.id AS parent_id, child.id AS child_id
            """,
            rfc_id=rfc_id,
        )
        paragraph_records = _run_data(
            driver,
            database,
            """
            MATCH (s:Section {rfc_id: $rfc_id})-[rel:HAS_PARAGRAPH]->(p:Paragraph)
            RETURN s.id AS section_id,
                   p.id AS id,
                   p.text AS text,
                   coalesce(rel.order, p.order) AS order
            ORDER BY s.order, order
            """,
            rfc_id=rfc_id,
        )
    finally:
        driver.close()

    return {
        "rfc": dict(rfc_record),
        "sections": section_records,
        "section_edges": section_edges,
        "paragraphs": paragraph_records,
    }


def load_structure_nodes(
    uri: str,
    username: str,
    password: str,
    database: Optional[str],
    domains: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    domain_values = list(domains or [])
    driver = GraphDatabase.driver(uri, auth=(username, password))
    try:
        rows = _run_data(
            driver,
            database,
            """
            MATCH (n:StructureNode)
            WHERE $domain_count = 0 OR n.domain IN $domains
            OPTIONAL MATCH (n)-[rel]->(:StructureNode)
            WHERE type(rel) IN $relationship_types
            RETURN n.id AS id,
                   n.name AS name,
                   n.path AS path,
                   n.domain AS domain,
                   coalesce(n.description, '') AS description,
                   count(rel) AS child_count
            ORDER BY n.id
            """,
            domains=domain_values,
            domain_count=len(domain_values),
            relationship_types=list(STRUCTURE_REL_TYPES),
        )
    finally:
        driver.close()

    targets = []
    for row in rows:
        path = str(row.get("path") or "")
        depth = len([part for part in path.split(".") if part]) or 1
        targets.append(
            {
                "id": row["id"],
                "name": row["name"],
                "path": path,
                "domain": row.get("domain") or "none",
                "description": row.get("description") or "",
                "depth": depth,
                "is_leaf": int(row.get("child_count") or 0) == 0,
            }
        )
    return targets


def clear_paragraph_structure_links(
    uri: str,
    username: str,
    password: str,
    database: Optional[str],
    rfc_id: Optional[str] = None,
) -> None:
    driver = GraphDatabase.driver(uri, auth=(username, password))
    try:
        with driver.session(database=database) as session:
            session.execute_write(_clear_paragraph_structure_links_tx, rfc_id)
    finally:
        driver.close()


def import_paragraph_structure_links_from_dataset(
    uri: str,
    username: str,
    password: str,
    database: Optional[str],
    dataset_path: str,
    clear_existing: bool = False,
    write_back: bool = True,
) -> Dict[str, int]:
    dataset = read_json(dataset_path)
    document = dataset.get("document") or dataset.get("rfc") or {}
    rfc_id = document.get("id")
    if not isinstance(rfc_id, str) or not rfc_id.strip():
        raise ValueError("Dataset is missing document.id / rfc.id.")

    rows: List[Dict[str, Any]] = []
    imported_items = 0
    imported_links = 0

    for item in dataset.get("items", []):
        if item.get("status") not in {"llm_completed", "imported"}:
            continue

        item_id = item.get("item_id")
        paragraph_id = item.get("input", {}).get("metadata", {}).get("paragraph_id")
        candidate_nodes = item.get("input", {}).get("candidate_nodes") or []
        candidate_by_id = {
            candidate["id"]: candidate
            for candidate in candidate_nodes
            if isinstance(candidate, dict) and candidate.get("id")
        }
        llm_result = item.get("llm_result") or {}
        links = llm_result.get("links") or []
        processed_at = llm_result.get("processed_at") or _utc_now()
        model = llm_result.get("model")

        item_link_count = 0
        for link in links:
            if not isinstance(link, dict):
                continue
            node_id = link.get("node_id")
            if not isinstance(paragraph_id, str) or not isinstance(node_id, str):
                continue
            candidate = candidate_by_id.get(node_id, {})
            rows.append(
                {
                    "paragraph_id": paragraph_id,
                    "node_id": node_id,
                    "method": "llm_selected",
                    "score": candidate.get("score"),
                    "reason": link.get("reason") or llm_result.get("overall_reason"),
                    "link_type": link.get("link_type"),
                    "model": model,
                    "created_at": processed_at,
                    "dataset_item_id": item_id,
                }
            )
            item_link_count += 1

        item["status"] = "imported"
        item["import_status"] = {
            "imported": True,
            "imported_at": _utc_now(),
            "error": None,
            "link_count": item_link_count,
        }
        imported_items += 1
        imported_links += item_link_count

    driver = GraphDatabase.driver(uri, auth=(username, password))
    try:
        with driver.session(database=database) as session:
            session.execute_write(
                _replace_paragraph_structure_links_tx,
                rfc_id,
                rows,
                clear_existing,
            )
    finally:
        driver.close()

    if write_back:
        write_json(dataset_path, dataset)

    return {
        "imported_items": imported_items,
        "imported_links": imported_links,
    }


def _clear_paragraph_structure_links_tx(tx, rfc_id: Optional[str]) -> None:
    if rfc_id:
        tx.run(
            """
            MATCH (p:Paragraph {rfc_id: $rfc_id})-[rel:RELATES_TO_STRUCTURE]->(:StructureNode)
            DELETE rel
            """,
            rfc_id=rfc_id,
        )
        return
    tx.run("MATCH (:Paragraph)-[rel:RELATES_TO_STRUCTURE]->(:StructureNode) DELETE rel")


def _replace_paragraph_structure_links_tx(
    tx,
    rfc_id: str,
    rows: List[Dict[str, Any]],
    clear_existing: bool,
) -> None:
    if clear_existing:
        _clear_paragraph_structure_links_tx(tx, rfc_id)

    for row in rows:
        tx.run(
            """
            MATCH (p:Paragraph {id: $paragraph_id})
            MATCH (s:StructureNode {id: $node_id})
            MERGE (p)-[rel:RELATES_TO_STRUCTURE]->(s)
            SET rel.method = $method,
                rel.score = $score,
                rel.reason = $reason,
                rel.link_type = $link_type,
                rel.model = $model,
                rel.created_at = $created_at,
                rel.dataset_item_id = $dataset_item_id
            """.replace("RELATES_TO_STRUCTURE", RELATES_TO_STRUCTURE),
            paragraph_id=row["paragraph_id"],
            node_id=row["node_id"],
            method=row.get("method"),
            score=row.get("score"),
            reason=row.get("reason"),
            link_type=row.get("link_type"),
            model=row.get("model"),
            created_at=row.get("created_at"),
            dataset_item_id=row.get("dataset_item_id"),
        )


def _run_single(driver, database: Optional[str], query: str, **params):
    with driver.session(database=database) as session:
        return session.run(query, **params).single()


def _run_data(driver, database: Optional[str], query: str, **params) -> List[Dict[str, Any]]:
    with driver.session(database=database) as session:
        return session.run(query, **params).data()


def _utc_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
