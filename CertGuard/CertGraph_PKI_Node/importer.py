from __future__ import annotations

import json
from typing import Dict, Iterable, List, Optional, Tuple

from neo4j import GraphDatabase

from .graph import StructureGraph, load_structure_graph


def import_structure_graphs_to_neo4j(
    uri: str,
    username: str,
    password: str,
    database: Optional[str],
    graph_specs: Iterable[Tuple[str, str]],
    clear_existing: bool = False,
) -> Dict[str, int]:
    graphs = [load_structure_graph(path, domain) for path, domain in graph_specs]
    driver = GraphDatabase.driver(uri, auth=(username, password))
    try:
        with driver.session(database=database) as session:
            session.execute_write(_merge_structure_graphs, graphs, clear_existing)
    finally:
        driver.close()

    return {
        "nodes": sum(len(graph.nodes) for graph in graphs),
        "relationships": sum(len(graph.relationships) for graph in graphs),
    }


def _merge_structure_graphs(tx, graphs: List[StructureGraph], clear_existing: bool) -> None:
    if clear_existing:
        tx.run("MATCH (n:StructureNode) DETACH DELETE n")
    for graph in graphs:
        _merge_structure_graph(tx, graph)


def _merge_structure_graph(tx, graph: StructureGraph) -> None:
    for node in graph.nodes:
        tx.run(
            """
            MERGE (n:StructureNode {id: $id})
            SET n.domain = $domain,
                n.name = $name,
                n.path = $path,
                n.source_labels = $labels,
                n.description = $description,
                n.asn1_type = $asn1_type,
                n.presence = $presence,
                n.attributes_json = $attributes_json
            """,
            id=node.id,
            domain=node.domain,
            name=node.name,
            path=node.path,
            labels=node.labels,
            description=node.attributes.get("description"),
            asn1_type=node.attributes.get("asn1_type"),
            presence=node.attributes.get("presence"),
            attributes_json=json.dumps(node.attributes, ensure_ascii=False, sort_keys=True),
        )

    for relationship in graph.relationships:
        query = """
            MATCH (start:StructureNode {id: $start_id})
            MATCH (end:StructureNode {id: $end_id})
            MERGE (start)-[:%s]->(end)
            """ % relationship.type
        tx.run(query, start_id=relationship.start_id, end_id=relationship.end_id)
