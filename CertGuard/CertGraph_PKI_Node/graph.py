from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple


STRUCTURE_REL_TYPES = {"HAS_FIELD", "HAS_VALUE", "HAS_TYPE", "HAS_ABS_FIELD"}


@dataclass
class StructureNode:
    id: str
    domain: str
    name: str
    labels: List[str]
    path: str
    attributes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StructureRelationship:
    start_id: str
    end_id: str
    type: str


@dataclass
class StructureGraph:
    nodes: List[StructureNode]
    relationships: List[StructureRelationship]


def load_structure_graph(path: str, domain: str) -> StructureGraph:
    with open(path, "r", encoding="utf-8") as file:
        raw_graph = json.load(file)

    raw_nodes = raw_graph.get("nodes", [])
    raw_relationships = raw_graph.get("relationships", [])
    inferred_paths = _infer_paths(raw_nodes, raw_relationships)

    used_ids: Set[str] = set()
    nodes_by_name: Dict[str, List[StructureNode]] = {}
    nodes: List[StructureNode] = []

    for raw_node in raw_nodes:
        attributes = dict(raw_node.get("attributes") or {})
        name = raw_node["name"]
        path_value = attributes.get("path_address") or inferred_paths.get(name) or name
        node_id = _unique_id("%s:%s" % (domain, path_value), used_ids)
        labels = list(raw_node.get("label") or [])
        node = StructureNode(
            id=node_id,
            domain=domain,
            name=name,
            labels=labels,
            path=path_value,
            attributes=attributes,
        )
        nodes.append(node)
        nodes_by_name.setdefault(name, []).append(node)

    relationships: List[StructureRelationship] = []
    for raw_relationship in raw_relationships:
        for start_id, end_id in _resolve_relationship_pairs(
            raw_relationship["start"],
            raw_relationship["end"],
            nodes_by_name,
        ):
            relationships.append(
                StructureRelationship(
                    start_id=start_id,
                    end_id=end_id,
                    type=_safe_relationship_type(raw_relationship.get("type")),
                )
            )

    relationships.extend(_infer_missing_path_relationships(nodes, relationships))

    return StructureGraph(nodes=nodes, relationships=relationships)


def _infer_paths(raw_nodes: List[Dict[str, Any]], raw_relationships: List[Dict[str, Any]]) -> Dict[str, str]:
    names = [node["name"] for node in raw_nodes]
    children_by_parent: Dict[str, List[str]] = {}
    child_names = set()
    for relationship in raw_relationships:
        parent = relationship["start"]
        child = relationship["end"]
        children_by_parent.setdefault(parent, []).append(child)
        child_names.add(child)

    roots = [name for name in names if name not in child_names]
    if not roots and names:
        roots = [names[0]]

    paths: Dict[str, str] = {}
    queue = [(root, root) for root in roots]
    while queue:
        name, path = queue.pop(0)
        paths.setdefault(name, path)
        for child in children_by_parent.get(name, []):
            queue.append((child, "%s.%s" % (path, child)))
    return paths


def _resolve_relationship_pairs(
    start_name: str,
    end_name: str,
    nodes_by_name: Dict[str, List[StructureNode]],
) -> List[Tuple[str, str]]:
    start_nodes = nodes_by_name.get(start_name) or []
    end_nodes = nodes_by_name.get(end_name) or []
    if not start_nodes or not end_nodes:
        return []

    if len(start_nodes) == 1 and len(end_nodes) == 1:
        return [(start_nodes[0].id, end_nodes[0].id)]

    pairs: List[Tuple[str, str]] = []
    for start_node in start_nodes:
        matched_children = [
            end_node
            for end_node in end_nodes
            if _path_implies_direct_child(start_node.path, end_node.path, end_node.name)
        ]
        if matched_children:
            pairs.extend((start_node.id, end_node.id) for end_node in matched_children)

    if pairs:
        return _dedupe_pairs(pairs)

    if len(start_nodes) == 1:
        return [(start_nodes[0].id, end_node.id) for end_node in end_nodes]
    if len(end_nodes) == 1:
        return [(start_node.id, end_nodes[0].id) for start_node in start_nodes]

    return [(start_nodes[0].id, end_nodes[0].id)]


def _path_implies_direct_child(parent_path: str, child_path: str, child_name: str) -> bool:
    direct_prefix = "%s.%s" % (parent_path, child_name)
    return child_path == direct_prefix or child_path.startswith(direct_prefix + ".")


def _dedupe_pairs(pairs: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    seen: Set[Tuple[str, str]] = set()
    deduped = []
    for pair in pairs:
        if pair in seen:
            continue
        seen.add(pair)
        deduped.append(pair)
    return deduped


def _infer_missing_path_relationships(
    nodes: List[StructureNode],
    relationships: List[StructureRelationship],
) -> List[StructureRelationship]:
    node_by_path = {node.path: node for node in nodes}
    incoming_ids = {relationship.end_id for relationship in relationships}
    existing_pairs = {(relationship.start_id, relationship.end_id) for relationship in relationships}
    inferred: List[StructureRelationship] = []

    for node in nodes:
        if node.id in incoming_ids:
            continue
        parent_path = _parent_path(node.path)
        if not parent_path:
            continue
        parent = node_by_path.get(parent_path)
        if parent is None:
            continue
        pair = (parent.id, node.id)
        if pair in existing_pairs:
            continue
        inferred.append(StructureRelationship(start_id=parent.id, end_id=node.id, type="HAS_FIELD"))
        existing_pairs.add(pair)

    return inferred


def _parent_path(path: str) -> Optional[str]:
    if "." not in path:
        return None
    return path.rsplit(".", 1)[0]


def _safe_relationship_type(value: Any) -> str:
    if isinstance(value, str) and value in STRUCTURE_REL_TYPES:
        return value
    return "HAS_FIELD"


def _unique_id(candidate: str, used_ids: Set[str]) -> str:
    safe_candidate = _normalize_id(candidate)
    if safe_candidate not in used_ids:
        used_ids.add(safe_candidate)
        return safe_candidate
    suffix = 2
    while "%s#%d" % (safe_candidate, suffix) in used_ids:
        suffix += 1
    unique = "%s#%d" % (safe_candidate, suffix)
    used_ids.add(unique)
    return unique


def _normalize_id(value: str) -> str:
    return re.sub(r"\s+", "_", value.strip())
