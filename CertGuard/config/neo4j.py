from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Neo4jConfig:
    uri: str
    username: str
    password: str
    database: Optional[str]


def load_neo4j_config(
    uri: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    database: Optional[str] = None,
) -> Neo4jConfig:
    return Neo4jConfig(
        uri=uri or os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        username=username or os.getenv("NEO4J_USERNAME", "neo4j"),
        password=password or os.getenv("NEO4J_PASSWORD", "password"),
        database=database or os.getenv("NEO4J_DATABASE"),
    )
