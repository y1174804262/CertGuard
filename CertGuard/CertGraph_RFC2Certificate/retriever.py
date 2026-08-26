from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Set

from .graph import load_rfc_document_records, load_structure_nodes
from .models import ParagraphBundle, StructureCandidate
from CertGuard.project_documents.json_store import preserve_item_results_from_existing_dataset, write_json


ROOT_TARGET_BY_DOMAIN = {
    "certificate": "certificate:Certificate",
    "crl": "crl:CertificateList",
}

GENERIC_PATH_TERMS = {
    "certificate",
    "certificate list",
    "certificatelist",
    "tbs certificate",
    "tbscertificate",
    "tbs cert list",
    "tbscertlist",
    "name",
    "value",
    "values",
    "field",
    "fields",
    "organization",
    "numbers",
    "noticenumbers",
}

NODE_ALIASES = {
    "version": ["version", "version number", "version numbers"],
    "AuthorityKeyIdentifier": ["authority key identifier", "aki"],
    "SubjectKeyIdentifier": ["subject key identifier", "ski"],
    "KeyUsage": ["key usage"],
    "CertificatePolicies": ["certificate policies", "certificate policy"],
    "PolicyMappings": ["policy mappings", "policy mapping", "policy mappings extension"],
    "SubjectAlternativeName": ["subject alternative name", "subject alt name", "san"],
    "IssuerAlternativeName": ["issuer alternative name", "issuer alt name", "ian"],
    "BasicConstraints": ["basic constraints", "basic constraints extension"],
    "NameConstraints": ["name constraints", "name constraints extension"],
    "PolicyConstraints": ["policy constraints", "policy constraints extension"],
    "ExtendedKeyUsage": ["extended key usage", "eku"],
    "CRLDistributionPoints": ["crl distribution points", "distribution point", "distribution points"],
    "FreshestCRL": ["freshest crl", "delta crl retrieval"],
    "AuthorityInformationAccess": ["authority information access", "aia"],
    "SubjectInformationAccess": ["subject information access", "sia"],
    "subjectPublicKeyInfo": ["subject public key info", "subject public key", "public key materials", "public key material", "public key"],
    "signatureAlgorithm": ["signature algorithm", "algorithm identifier"],
    "signatureValue": ["signature value", "digital signature", "digital signatures"],
    "serialNumber": ["serial number", "serialnumber"],
    "issuer": ["issuer", "crl issuer"],
    "subject": ["subject", "subject name"],
    "ReasonCode": ["reason code", "revocation reason"],
    "IssuingDistributionPoint": ["issuing distribution point"],
    "CRLNumber": ["crl number"],
    "DeltaCRLIndicator": ["delta crl indicator", "delta crl"],
    "CertificateIssuer": ["certificate issuer"],
    "InvalidityDate": ["invalidity date"],
    "revocationDate": ["revocation date"],
    "UTCTime": ["utc time", "utctime"],
    "GeneralizedTime": ["generalized time", "generalizedtime"],
}


@dataclass(frozen=True)
class RetrievedCandidate:
    target_id: str
    name: str
    path: str
    domain: str
    description: str
    depth: int
    is_leaf: bool
    score: float
    reasons: Sequence[str]


def export_linking_dataset_from_neo4j(
    uri: str,
    username: str,
    password: str,
    database: Optional[str],
    rfc_id: str,
    output_path: str,
    previous_count: int = 1,
    next_count: int = 1,
    intro_count: int = 1,
    candidate_limit: int = 10,
    preserve_existing: bool = True,
) -> Dict[str, Any]:
    records = load_rfc_document_records(
        uri=uri,
        username=username,
        password=password,
        database=database,
        rfc_id=rfc_id,
    )
    targets = load_structure_nodes(
        uri=uri,
        username=username,
        password=password,
        database=database,
    )
    dataset = build_paragraph_linking_dataset(
        rfc_id=records["rfc"]["id"],
        rfc_title=records["rfc"]["title"],
        section_records=records["sections"],
        section_edges=records["section_edges"],
        paragraph_records=records["paragraphs"],
        targets=targets,
        previous_count=previous_count,
        next_count=next_count,
        intro_count=intro_count,
        candidate_limit=candidate_limit,
    )
    if preserve_existing:
        preserve_item_results_from_existing_dataset(dataset, output_path)
    write_json(output_path, dataset)
    return dataset


def build_paragraph_linking_dataset(
    rfc_id: str,
    rfc_title: str,
    section_records: List[Dict[str, Any]],
    section_edges: List[Dict[str, str]],
    paragraph_records: List[Dict[str, Any]],
    targets: List[Dict[str, Any]],
    previous_count: int = 1,
    next_count: int = 1,
    intro_count: int = 1,
    candidate_limit: int = 10,
) -> Dict[str, Any]:
    sections_by_id = {record["id"]: record for record in section_records}
    parent_by_child = {edge["child_id"]: edge["parent_id"] for edge in section_edges}
    paragraphs_by_section: Dict[str, List[Dict[str, Any]]] = {}

    for paragraph in paragraph_records:
        paragraphs_by_section.setdefault(paragraph["section_id"], []).append(paragraph)

    for paragraphs in paragraphs_by_section.values():
        paragraphs.sort(key=lambda item: item["order"])

    items = []
    for section in sorted(section_records, key=lambda item: item["order"]):
        section_path = _section_path(section["id"], sections_by_id, parent_by_child)
        parent_section_title = None
        parent_id = parent_by_child.get(section["id"])
        if parent_id:
            parent_section_title = sections_by_id[parent_id]["title"]

        section_paragraphs = paragraphs_by_section.get(section["id"], [])
        for index, paragraph in enumerate(section_paragraphs):
            bundle = ParagraphBundle(
                rfc_id=rfc_id,
                paragraph_id=paragraph["id"],
                paragraph_order=paragraph["order"],
                section_id=section["id"],
                section_number=section["number"],
                section_title=section["title"],
                section_path=section_path,
                parent_section_title=parent_section_title,
                text=paragraph["text"],
                previous_paragraphs=[
                    _context_paragraph(item)
                    for item in section_paragraphs[max(0, index - previous_count) : index]
                ],
                next_paragraphs=[
                    _context_paragraph(item)
                    for item in section_paragraphs[index + 1 : index + 1 + next_count]
                ],
                section_intro_paragraphs=[
                    _context_paragraph(item)
                    for item in section_paragraphs[:intro_count]
                    if item["id"] != paragraph["id"]
                ],
                inferred_domain=infer_paragraph_domain(section_path, section["title"], paragraph["text"]),
            )

            candidates = retrieve_candidate_nodes(bundle, targets, candidate_limit=candidate_limit)
            item_input = bundle.to_item_input()
            item_input["candidate_nodes"] = [candidate.to_dict() for candidate in candidates]

            items.append(
                {
                    "item_id": bundle.paragraph_id,
                    "status": "pending",
                    "input": item_input,
                    "llm_result": {
                        "links": [],
                        "overall_reason": None,
                        "raw_response": None,
                        "model": None,
                        "processed_at": None,
                    },
                    "import_status": {
                        "imported": False,
                        "imported_at": None,
                        "error": None,
                        "link_count": 0,
                    },
                }
            )

    return {
        "schema_version": "paragraph-node-linking-dataset-v1",
        "created_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "document": {
            "id": rfc_id,
            "title": rfc_title,
        },
        "generation_config": {
            "previous_count": previous_count,
            "next_count": next_count,
            "intro_count": intro_count,
            "candidate_limit": candidate_limit,
        },
        "items": items,
    }


def retrieve_candidate_nodes(
    bundle: ParagraphBundle,
    targets: List[Dict[str, Any]],
    candidate_limit: int = 10,
) -> List[StructureCandidate]:
    pseudo_rule = {
        "id": bundle.paragraph_id,
        "domain": bundle.inferred_domain,
        "section_title": _section_title_for_retrieval(bundle),
        "text": _retrieval_text(bundle),
    }
    candidates = retrieve_candidate_targets(
        pseudo_rule,
        targets,
        candidate_limit=candidate_limit,
    )
    if not candidates and bundle.inferred_domain != "none":
        pseudo_rule["domain"] = "none"
        candidates = retrieve_candidate_targets(
            pseudo_rule,
            targets,
            candidate_limit=candidate_limit,
        )

    candidates = _rescore_candidates_with_title_signals(candidates, bundle)
    pruned = prune_ancestor_candidates(candidates, max_links_per_rule=candidate_limit)
    return [
        StructureCandidate(
            node_id=candidate.target_id,
            name=candidate.name,
            path=candidate.path,
            domain=candidate.domain,
            description=candidate.description,
            depth=candidate.depth,
            is_leaf=candidate.is_leaf,
            score=candidate.score,
            reason=" | ".join(candidate.reasons),
        )
        for candidate in pruned
    ]


def infer_paragraph_domain(
    section_path: List[Dict[str, str]],
    section_title: str,
    paragraph_text: str,
) -> str:
    top_level_number = section_path[0]["number"] if section_path else ""
    if top_level_number == "4":
        return "certificate"
    if top_level_number == "5":
        return "crl"
    if top_level_number in {"6", "7"}:
        return "both"

    combined = " ".join(
        part
        for part in [
            " ".join(item["title"] for item in section_path),
            section_title,
            paragraph_text,
        ]
        if part
    ).lower()

    crl_hits = sum(
        marker in combined
        for marker in (
            "certificate revocation list",
            "crl",
            "crl entry",
            "delta crl",
            "issuing distribution point",
            "revoked certificate",
        )
    )
    certificate_hits = sum(
        marker in combined
        for marker in (
            "certificate",
            "serial number",
            "subject public key",
            "subject alternative name",
            "basic constraints",
            "certificate policy",
        )
    )

    if crl_hits and not certificate_hits:
        return "crl"
    if certificate_hits and not crl_hits:
        return "certificate"
    if certificate_hits and crl_hits:
        return "both"
    return "none"


def _section_path(
    section_id: str,
    sections_by_id: Dict[str, Dict[str, Any]],
    parent_by_child: Dict[str, str],
) -> List[Dict[str, str]]:
    path = []
    current_id = section_id
    while current_id:
        section = sections_by_id[current_id]
        path.append({"number": section["number"], "title": section["title"]})
        current_id = parent_by_child.get(current_id)
    return list(reversed(path))


def _context_paragraph(paragraph: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": paragraph["id"],
        "order": paragraph["order"],
        "text": paragraph["text"],
    }


def _section_title_for_retrieval(bundle: ParagraphBundle) -> str:
    title_parts = [bundle.section_title]
    if bundle.parent_section_title:
        title_parts.append(bundle.parent_section_title)
    return " | ".join(part for part in title_parts if part)


def _retrieval_text(bundle: ParagraphBundle) -> str:
    parts = [
        bundle.text,
        " ".join(item["text"] for item in bundle.previous_paragraphs[-1:]),
        " ".join(item["text"] for item in bundle.section_intro_paragraphs[:1]),
    ]
    return " ".join(part for part in parts if part)


def _rescore_candidates_with_title_signals(
    candidates: List[RetrievedCandidate],
    bundle: ParagraphBundle,
) -> List[RetrievedCandidate]:
    current_title = normalize_text(bundle.section_title)
    parent_title = normalize_text(bundle.parent_section_title or "")
    path_titles = normalize_text(" ".join(item["title"] for item in bundle.section_path))

    rescored: List[RetrievedCandidate] = []
    for candidate in candidates:
        score = candidate.score
        reasons = list(candidate.reasons)

        current_boost, current_reasons = _title_match_score(
            candidate,
            current_title,
            label="section title",
        )
        parent_boost, parent_reasons = _title_match_score(
            candidate,
            parent_title,
            label="parent title",
        )
        path_boost, path_reasons = _title_match_score(
            candidate,
            path_titles,
            label="section path",
        )

        score += current_boost + min(parent_boost, 1.2) + min(path_boost, 0.8)
        reasons.extend(current_reasons)
        reasons.extend(parent_reasons)
        reasons.extend(path_reasons)

        rescored.append(
            RetrievedCandidate(
                target_id=candidate.target_id,
                name=candidate.name,
                path=candidate.path,
                domain=candidate.domain,
                description=candidate.description,
                depth=candidate.depth,
                is_leaf=candidate.is_leaf,
                score=score,
                reasons=reasons,
            )
        )

    rescored.sort(key=lambda item: (item.score, item.depth, int(item.is_leaf)), reverse=True)
    return rescored


def _title_match_score(
    candidate: RetrievedCandidate,
    title_text: str,
    label: str,
) -> (float, List[str]):
    if not title_text:
        return 0.0, []

    score = 0.0
    reasons: List[str] = []
    normalized_name = normalize_text(candidate.name)
    normalized_path = normalize_text(candidate.path)
    description = normalize_text(candidate.description or "")
    aliases = list(aliases_for_node(candidate.name))
    target_terms = target_search_terms(candidate.name, candidate.path, description)

    exact_heading_terms = [term for term in [normalized_name] + aliases if term and title_text == term]
    if exact_heading_terms:
        score += 4.0
        reasons.append("%s exact focus match" % label)

    matched_aliases = [alias for alias in aliases if alias and alias in title_text]
    if matched_aliases:
        score += min(3.5, 2.0 + 0.8 * len(set(matched_aliases)))
        reasons.append("%s alias match: %s" % (label, ", ".join(sorted(set(matched_aliases))[:4])))

    matched_terms = [
        term
        for term in target_terms
        if len(term) >= 4 and term in title_text and term not in {normalized_name, normalized_path}
    ]
    if matched_terms:
        score += min(2.5, 0.9 * len(set(matched_terms)))
        reasons.append("%s term match: %s" % (label, ", ".join(sorted(set(matched_terms))[:4])))

    if normalized_name and normalized_name in title_text:
        score += 1.8
        reasons.append("%s contains node name" % label)

    if normalized_path and normalized_path.endswith(title_text) and len(title_text) >= 6:
        score += 0.6
        reasons.append("%s matches path suffix" % label)

    return score, reasons


def retrieve_candidate_targets(
    rule: Dict[str, str],
    targets: Sequence[Dict[str, object]],
    candidate_limit: int = 12,
) -> List[RetrievedCandidate]:
    domain = (rule.get("domain") or "none").lower()
    text = normalize_text(rule.get("text") or "")
    section_title = normalize_text(rule.get("section_title") or "")
    allowed_domains = allowed_target_domains(domain)
    filtered_targets = [target for target in targets if target["domain"] in allowed_domains]

    scored = []
    for target in filtered_targets:
        score, reasons = score_target(rule_text=text, section_title=section_title, target=target)
        if score <= 0:
            continue
        scored.append(
            RetrievedCandidate(
                target_id=str(target["id"]),
                name=str(target["name"]),
                path=str(target["path"]),
                domain=str(target["domain"]),
                description=str(target.get("description") or ""),
                depth=int(target.get("depth") or 0),
                is_leaf=bool(target.get("is_leaf")),
                score=score,
                reasons=reasons,
            )
        )

    scored.sort(key=lambda item: (item.score, item.depth, int(item.is_leaf)), reverse=True)
    deduped = dedupe_by_target(scored)
    return deduped[:candidate_limit]


def prune_ancestor_candidates(
    candidates: Sequence[RetrievedCandidate],
    max_links_per_rule: int = 3,
) -> List[RetrievedCandidate]:
    sorted_candidates = sorted(candidates, key=lambda item: (item.score, item.depth, int(item.is_leaf)), reverse=True)
    kept: List[RetrievedCandidate] = []
    for candidate in sorted_candidates:
        replaced = False
        next_kept: List[RetrievedCandidate] = []
        skip_candidate = False
        for existing in kept:
            if is_ancestor_path(existing.path, candidate.path):
                if candidate.score >= existing.score - 0.25:
                    replaced = True
                    continue
                skip_candidate = True
            elif is_ancestor_path(candidate.path, existing.path):
                if existing.score >= candidate.score - 0.25:
                    skip_candidate = True
            next_kept.append(existing)
        if skip_candidate and not replaced:
            kept = next_kept
            continue
        next_kept.append(candidate)
        kept = sorted(next_kept, key=lambda item: (item.score, item.depth, int(item.is_leaf)), reverse=True)[:max_links_per_rule]
    return kept


def score_target(rule_text: str, section_title: str, target: Dict[str, object]) -> (float, List[str]):
    score = 0.0
    reasons: List[str] = []
    target_name = str(target["name"])
    target_path = str(target["path"])
    target_description = normalize_text(str(target.get("description") or ""))
    target_terms = target_search_terms(target_name, target_path, target_description)

    matched_aliases = [alias for alias in aliases_for_node(target_name) if alias in rule_text or alias in section_title]
    if matched_aliases:
        score += 4.0
        reasons.append("alias match: %s" % ", ".join(sorted(set(matched_aliases))))

    matched_terms = [
        term
        for term in target_terms
        if len(term) >= 4 and term not in GENERIC_PATH_TERMS and (term in rule_text or term in section_title)
    ]
    if matched_terms:
        score += min(3.0, 0.8 * len(set(matched_terms)))
        reasons.append("term match: %s" % ", ".join(sorted(set(matched_terms))[:6]))

    normalized_name = normalize_text(target_name)
    if len(normalized_name) >= 4 and normalized_name in rule_text:
        score += 1.5
        reasons.append("name appears in rule text")

    if target_description:
        description_terms = {term for term in target_description.split() if len(term) >= 5}
        overlap = sorted(description_terms.intersection(set(rule_text.split())))
        if overlap:
            score += min(1.5, 0.3 * len(overlap))
            reasons.append("description overlap: %s" % ", ".join(overlap[:6]))

    if target.get("is_leaf") and score > 0:
        score += 0.25
        reasons.append("leaf bonus")

    if "extension" in rule_text and target_name.endswith("s"):
        score += 0.1

    role_or_process = is_role_or_process_rule(rule_text)

    if role_or_process:
        if normalized_name in {"issuer", "subject", "certificate", "certificatelist"}:
            score -= 1.5
            reasons.append("role/process penalty")
        if target_path in {"Certificate", "CertificateList"}:
            score -= 2.0
            reasons.append("root penalty for role/process rule")

    if role_or_process and path_contains_role_like_fragment(target_path) and not has_explicit_structure_constraint(rule_text):
        return 0.0, []

    if "serial number" in rule_text and "serial number" not in matched_terms and normalized_name != "serial number":
        score -= 1.2
        reasons.append("serial-number mismatch penalty")

    if "extension" in rule_text and "extension" not in matched_terms and "extension" not in normalized_name:
        score -= 0.8
        reasons.append("extension mismatch penalty")

    if score < 0.5:
        return 0.0, []

    return score, reasons


def target_search_terms(name: str, path: str, description: str) -> Set[str]:
    terms = set()
    terms.add(normalize_text(name))
    terms.update(
        term
        for term in (normalize_text(part) for part in path.split(".") if part)
        if term and term not in GENERIC_PATH_TERMS
    )
    terms.update(alias for alias in aliases_for_node(name))
    if description:
        terms.update(term for term in description.split() if len(term) >= 5)
    return {term for term in terms if term}


def aliases_for_node(name: str) -> Sequence[str]:
    return NODE_ALIASES.get(name, ())


def allowed_target_domains(domain: str) -> List[str]:
    if domain == "certificate":
        return ["certificate"]
    if domain == "crl":
        return ["crl"]
    if domain == "both":
        return ["certificate", "crl"]
    return ["certificate", "crl"]


def dedupe_by_target(candidates: Sequence[RetrievedCandidate]) -> List[RetrievedCandidate]:
    seen = set()
    deduped = []
    for candidate in candidates:
        if candidate.target_id in seen:
            continue
        seen.add(candidate.target_id)
        deduped.append(candidate)
    return deduped


def normalize_text(value: str) -> str:
    value = split_identifier(value)
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def is_role_or_process_rule(rule_text: str) -> bool:
    markers = (
        "delegate",
        "delegation",
        "publication",
        "publish",
        "distribution",
        "distributing",
        "responsible for",
        "review",
        "process",
        "validation",
        "procedure",
        "procedures",
        "support",
        "operate securely",
    )
    return any(marker in rule_text for marker in markers)


def has_explicit_structure_constraint(rule_text: str) -> bool:
    field_markers = (
        "field",
        "fields",
        "extension",
        "extensions",
        "bit",
        "bits",
        "value",
        "values",
        "serial number",
        "key identifier",
        "subject public key",
        "signature",
        "signature algorithm",
        "public key",
        "critical",
        "name constraints",
        "policy mappings",
        "distribution point",
        "reason code",
        "revocation date",
        "not before",
        "not after",
        "validity",
        "generalizedtime",
        "utctime",
        "must be included",
        "must be omitted",
        "must contain",
        "must not contain",
        "encoded",
        "encoding",
    )
    return any(marker in rule_text for marker in field_markers)


def path_contains_role_like_fragment(path: str) -> bool:
    normalized_path = normalize_text(path)
    fragments = (
        " issuer ",
        " subject ",
        " certificate ",
        " certificate list ",
    )
    padded = " %s " % normalized_path
    return any(fragment in padded for fragment in fragments)


def split_identifier(value: str) -> str:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    return value.replace("_", " ").replace("-", " ")


def is_ancestor_path(ancestor: str, descendant: str) -> bool:
    if ancestor == descendant:
        return False
    return descendant.startswith(ancestor + ".")
