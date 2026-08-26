from __future__ import annotations

from typing import Dict, Optional

from neo4j import GraphDatabase

from .models import RfcDocument, Section
from .parser import iter_sections


class Neo4jRfcStore:
    def __init__(self, uri: str, username: str, password: str, database: Optional[str] = None):
        self._driver = GraphDatabase.driver(uri, auth=(username, password))
        self._database = database

    def close(self) -> None:
        self._driver.close()

    def import_document(
        self,
        document: RfcDocument,
        clear_existing: bool = False,
        create_next_relationships: bool = False,
    ) -> None:
        with self._driver.session(database=self._database) as session:
            session.execute_write(
                self._replace_document,
                document,
                clear_existing,
                create_next_relationships,
            )

    def clear_database(self) -> None:
        with self._driver.session(database=self._database) as session:
            session.execute_write(self._clear_database)

    def clear_document(self, document_id: str) -> None:
        with self._driver.session(database=self._database) as session:
            session.execute_write(self._clear_rfc, document_id)

    @staticmethod
    def _clear_database(tx) -> None:
        tx.run("MATCH (n) DETACH DELETE n")

    @staticmethod
    def _clear_rfc(tx, rfc_id: str) -> None:
        tx.run(
            """
            MATCH (r:RFC {id: $rfc_id})
            OPTIONAL MATCH (r)-[:HAS_SECTION|HAS_SUBSECTION*0..]->(s:Section)
            OPTIONAL MATCH (s)-[:HAS_PARAGRAPH]->(p:Paragraph)
            OPTIONAL MATCH (p)-[:HAS_RULE]->(rule:Rule)
            WITH collect(DISTINCT r) + collect(DISTINCT s) + collect(DISTINCT p) + collect(DISTINCT rule) AS nodes
            UNWIND nodes AS n
            WITH n WHERE n IS NOT NULL
            DETACH DELETE n
            """,
            rfc_id=rfc_id,
        )

    @staticmethod
    def _write_document(tx, document: RfcDocument, create_next_relationships: bool) -> None:
        tx.run(
            """
            MERGE (r:RFC {id: $id})
            SET r:Document,
                r.title = $title,
                r.document_id = $id,
                r.source_type = coalesce(r.source_type, 'RFC')
            """,
            id=document.id,
            title=document.title,
        )

        for section in document.sections:
            _write_section(tx, document.id, None, section, create_next_relationships)

    @staticmethod
    def _replace_document(
        tx,
        document: RfcDocument,
        clear_existing: bool,
        create_next_relationships: bool,
    ) -> None:
        if clear_existing:
            Neo4jRfcStore._clear_rfc(tx, document.id)
        Neo4jRfcStore._write_document(tx, document, create_next_relationships)


def _write_section(
    tx,
    rfc_id: str,
    parent_section_id: Optional[str],
    section: Section,
    create_next_relationships: bool,
) -> None:
    tx.run(
        """
        MERGE (s:Section {id: $id})
        SET s.number = $number,
            s.title = $title,
            s.order = $order,
            s.rfc_id = $rfc_id,
            s.document_id = $rfc_id
        """,
        id=section.id,
        number=section.number,
        title=section.title,
        order=section.order,
        rfc_id=rfc_id,
    )

    if parent_section_id is None:
        tx.run(
            """
            MATCH (r:RFC {id: $rfc_id})
            MATCH (s:Section {id: $section_id})
            MERGE (r)-[:HAS_SECTION]->(s)
            """,
            rfc_id=rfc_id,
            section_id=section.id,
        )
    else:
        tx.run(
            """
            MATCH (parent:Section {id: $parent_section_id})
            MATCH (child:Section {id: $section_id})
            MERGE (parent)-[:HAS_SUBSECTION]->(child)
            """,
            parent_section_id=parent_section_id,
            section_id=section.id,
        )

    previous_paragraph_id: Optional[str] = None
    for paragraph in section.paragraphs:
        tx.run(
            """
            MERGE (p:Paragraph {id: $id})
            SET p.text = $text,
                p.order = $order,
                p.rfc_id = $rfc_id,
                p.document_id = $rfc_id,
                p.section_id = $section_id
            WITH p
            MATCH (s:Section {id: $section_id})
            MERGE (s)-[rel:HAS_PARAGRAPH]->(p)
            SET rel.order = $order
            """,
            id=paragraph.id,
            text=paragraph.text,
            order=paragraph.order,
            rfc_id=rfc_id,
            section_id=section.id,
        )

        if create_next_relationships and previous_paragraph_id is not None:
            tx.run(
                """
                MATCH (previous:Paragraph {id: $previous_id})
                MATCH (current:Paragraph {id: $current_id})
                MERGE (previous)-[:NEXT]->(current)
                """,
                previous_id=previous_paragraph_id,
                current_id=paragraph.id,
            )
        previous_paragraph_id = paragraph.id

    for subsection in section.subsections:
        _write_section(tx, rfc_id, section.id, subsection, create_next_relationships)


def document_summary(document: RfcDocument) -> Dict[str, int]:
    sections = iter_sections(document)
    return {
        "sections": len(sections),
        "paragraphs": sum(len(section.paragraphs) for section in sections),
    }
