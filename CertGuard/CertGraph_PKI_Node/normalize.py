from __future__ import annotations

import json
from collections import Counter, defaultdict
from copy import deepcopy
from typing import Dict, List


def normalize_structure_files(
    x509_input: str,
    crl_input: str,
    x509_output: str,
    crl_output: str,
) -> Dict[str, str]:
    x509 = read_json(x509_input)
    crl = read_json(crl_input)

    write_json(x509_output, normalize_x509_structure(x509))
    write_json(crl_output, normalize_crl_structure(crl))

    return {
        "x509_input": x509_input,
        "crl_input": crl_input,
        "x509_output": x509_output,
        "crl_output": crl_output,
    }


def normalize_x509_structure(data: Dict) -> Dict:
    normalized = deepcopy(data)
    nodes = normalized.get("nodes", [])
    by_name = {node["name"]: node for node in nodes}

    _set_path(
        by_name,
        "authorityCertIssuer",
        "Certificate.tbsCertificate.extensions.StandardExtensions.AuthorityKeyIdentifier.authorityCertIssuer",
    )
    _set_path(
        by_name,
        "authorityCertSerialNumber",
        "Certificate.tbsCertificate.extensions.StandardExtensions.AuthorityKeyIdentifier.authorityCertSerialNumber",
    )
    _set_path(
        by_name,
        "accessMethod",
        "Certificate.tbsCertificate.extensions.PrivateInternetExtensions.AuthorityInformationAccess.accessMethod",
    )
    _set_path(
        by_name,
        "accessLocation",
        "Certificate.tbsCertificate.extensions.PrivateInternetExtensions.AuthorityInformationAccess.accessLocation",
    )
    _set_path(
        by_name,
        "SubjectInformationAccess",
        "Certificate.tbsCertificate.extensions.PrivateInternetExtensions.SubjectInformationAccess",
    )

    _add_or_replace_relationship(
        normalized["relationships"],
        {"start": "PrivateInternetExtensions", "end": "SubjectInformationAccess", "type": "HAS_FIELD"},
    )
    _remove_relationship(
        normalized["relationships"],
        {"start": "extensions", "end": "SubjectInformationAccess", "type": "HAS_FIELD"},
    )

    return normalized


def normalize_crl_structure(data: Dict) -> Dict:
    normalized = deepcopy(data)
    nodes = normalized.get("nodes", [])
    relationships = normalized.get("relationships", [])
    names = [node["name"] for node in nodes]
    duplicate_counts = Counter(names)
    name_occurrences = defaultdict(int)

    parent_paths = _build_parent_paths(relationships, root_name="CertificateList")
    explicit_paths = _crl_explicit_paths()

    for node in nodes:
        name = node["name"]
        attrs = node.setdefault("attributes", {})
        name_occurrences[name] += 1
        occurrence_index = name_occurrences[name]

        explicit_key = (name, occurrence_index) if duplicate_counts[name] > 1 else name
        path = explicit_paths.get(explicit_key)
        if path is None:
            parent_path = parent_paths.get(explicit_key) or parent_paths.get(name)
            if parent_path:
                path = "%s.%s" % (parent_path, name)
            else:
                path = "CertificateList.%s" % name if name != "CertificateList" else "CertificateList"
        attrs["path_address"] = path

    return normalized


def read_json(path: str) -> Dict:
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: str, data: Dict) -> None:
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")


def _build_parent_paths(relationships: List[Dict], root_name: str) -> Dict:
    parent_paths: Dict = {root_name: "CertificateList"}
    child_counts = Counter(rel["end"] for rel in relationships)
    child_seen = Counter()
    parent_seen = Counter()
    indexed_relationships = []

    for rel in relationships:
        parent = rel["start"]
        child = rel["end"]
        parent_seen[parent] += 1
        child_seen[child] += 1
        parent_key = (parent, parent_seen[parent]) if _is_duplicate_name(parent, relationships, role="start") else parent
        child_key = (child, child_seen[child]) if child_counts[child] > 1 else child
        indexed_relationships.append((parent_key, child_key, parent, child))

    changed = True
    while changed:
        changed = False
        for parent_key, child_key, parent, child in indexed_relationships:
            if parent_key in parent_paths and child_key not in parent_paths:
                parent_paths[child_key] = "%s.%s" % (parent_paths[parent_key], child)
                changed = True
            elif isinstance(parent_key, str) and parent in parent_paths and child_key not in parent_paths:
                parent_paths[child_key] = "%s.%s" % (parent_paths[parent], child)
                changed = True

    return parent_paths


def _is_duplicate_name(name: str, relationships: List[Dict], role: str) -> bool:
    values = [rel[role] for rel in relationships]
    return Counter(values)[name] > 1


def _crl_explicit_paths() -> Dict:
    return {
        "CertificateList": "CertificateList",
        "tbsCertList": "CertificateList.tbsCertList",
        "version": "CertificateList.tbsCertList.version",
        "signature": "CertificateList.tbsCertList.signature",
        "issuer": "CertificateList.tbsCertList.issuer",
        "thisUpdate": "CertificateList.tbsCertList.thisUpdate",
        "nextUpdate": "CertificateList.tbsCertList.nextUpdate",
        "revokedCertificates": "CertificateList.tbsCertList.revokedCertificates",
        "crlExtensions": "CertificateList.tbsCertList.crlExtensions",
        "userCertificate": "CertificateList.tbsCertList.revokedCertificates.userCertificate",
        ("revocationDate", 1): "CertificateList.tbsCertList.revokedCertificates.revocationDate",
        ("revocationDate", 2): "CertificateList.tbsCertList.revokedCertificates.crlEntryExtensions.revocationDate",
        "Name": "CertificateList.tbsCertList.issuer.Name",
        "RelativeDistinguishedName": "CertificateList.tbsCertList.issuer.Name.RelativeDistinguishedName",
        "AttributeTypeAndValue": "CertificateList.tbsCertList.issuer.Name.RelativeDistinguishedName.AttributeTypeAndValue",
        "AttributeType": "CertificateList.tbsCertList.issuer.Name.RelativeDistinguishedName.AttributeTypeAndValue.AttributeType",
        "AttributeValue": "CertificateList.tbsCertList.issuer.Name.RelativeDistinguishedName.AttributeTypeAndValue.AttributeValue",
        "DirectoryString": "CertificateList.tbsCertList.issuer.Name.RelativeDistinguishedName.AttributeTypeAndValue.AttributeType.DirectoryString",
        "teletexString": "CertificateList.tbsCertList.issuer.Name.RelativeDistinguishedName.AttributeTypeAndValue.AttributeType.DirectoryString.teletexString",
        "printableString": "CertificateList.tbsCertList.issuer.Name.RelativeDistinguishedName.AttributeTypeAndValue.AttributeType.DirectoryString.printableString",
        "universalString": "CertificateList.tbsCertList.issuer.Name.RelativeDistinguishedName.AttributeTypeAndValue.AttributeType.DirectoryString.universalString",
        "utf8String": "CertificateList.tbsCertList.issuer.Name.RelativeDistinguishedName.AttributeTypeAndValue.AttributeType.DirectoryString.utf8String",
        "bmpString": "CertificateList.tbsCertList.issuer.Name.RelativeDistinguishedName.AttributeTypeAndValue.AttributeType.DirectoryString.bmpString",
        "UTCTime": "CertificateList.tbsCertList.thisUpdate.UTCTime",
        "GeneralizedTime": "CertificateList.tbsCertList.thisUpdate.GeneralizedTime",
        "AuthorityKeyIdentifier": "CertificateList.tbsCertList.crlExtensions.AuthorityKeyIdentifier",
        "IssuerAlternativeName": "CertificateList.tbsCertList.crlExtensions.IssuerAlternativeName",
        "GeneralNames": "CertificateList.tbsCertList.crlExtensions.GeneralNames",
        "otherName": "CertificateList.tbsCertList.crlExtensions.GeneralNames.otherName",
        "rfc822Name": "CertificateList.tbsCertList.crlExtensions.GeneralNames.rfc822Name",
        "dNSName": "CertificateList.tbsCertList.crlExtensions.GeneralNames.dNSName",
        "x400Address": "CertificateList.tbsCertList.crlExtensions.GeneralNames.x400Address",
        "directoryName": "CertificateList.tbsCertList.crlExtensions.GeneralNames.directoryName",
        "ediPartyName": "CertificateList.tbsCertList.crlExtensions.GeneralNames.ediPartyName",
        "uniformResourceIdentifier": "CertificateList.tbsCertList.crlExtensions.GeneralNames.uniformResourceIdentifier",
        "iPAddress": "CertificateList.tbsCertList.crlExtensions.GeneralNames.iPAddress",
        "registeredID": "CertificateList.tbsCertList.crlExtensions.GeneralNames.registeredID",
        "type-id": "CertificateList.tbsCertList.crlExtensions.GeneralNames.otherName.type-id",
        "value": "CertificateList.tbsCertList.crlExtensions.GeneralNames.otherName.value",
        "nameAssigner": "CertificateList.tbsCertList.crlExtensions.GeneralNames.ediPartyName.nameAssigner",
        "partyName": "CertificateList.tbsCertList.crlExtensions.GeneralNames.ediPartyName.partyName",
        "CRLNumber": "CertificateList.tbsCertList.crlExtensions.CRLNumber",
        "DeltaCRLIndicator": "CertificateList.tbsCertList.crlExtensions.DeltaCRLIndicator",
        "BaseCRLNumber": "CertificateList.tbsCertList.crlExtensions.DeltaCRLIndicator.BaseCRLNumber",
        "IssuingDistributionPoint": "CertificateList.tbsCertList.crlExtensions.IssuingDistributionPoint",
        ("distributionPoint", 1): "CertificateList.tbsCertList.crlExtensions.IssuingDistributionPoint.distributionPoint",
        "onlyContainsUserCerts": "CertificateList.tbsCertList.crlExtensions.IssuingDistributionPoint.onlyContainsUserCerts",
        "onlyContainsCACerts": "CertificateList.tbsCertList.crlExtensions.IssuingDistributionPoint.onlyContainsCACerts",
        "onlySomeReasons": "CertificateList.tbsCertList.crlExtensions.IssuingDistributionPoint.onlySomeReasons",
        "indirectCRL": "CertificateList.tbsCertList.crlExtensions.IssuingDistributionPoint.indirectCRL",
        "onlyContainsAttributeCerts": "CertificateList.tbsCertList.crlExtensions.IssuingDistributionPoint.onlyContainsAttributeCerts",
        "CRLDistributionPoints": "CertificateList.tbsCertList.crlExtensions.FreshestCRL.CRLDistributionPoints",
        ("distributionPoint", 2): "CertificateList.tbsCertList.crlExtensions.FreshestCRL.CRLDistributionPoints.distributionPoint",
        "fullName": "CertificateList.tbsCertList.crlExtensions.FreshestCRL.CRLDistributionPoints.distributionPoint.fullName",
        "nameRelativeToCRLIssuer": "CertificateList.tbsCertList.crlExtensions.FreshestCRL.CRLDistributionPoints.distributionPoint.nameRelativeToCRLIssuer",
        "reasons": "CertificateList.tbsCertList.crlExtensions.FreshestCRL.CRLDistributionPoints.distributionPoint.reasons",
        ("keyCompromise", 1): "CertificateList.tbsCertList.crlExtensions.FreshestCRL.CRLDistributionPoints.distributionPoint.reasons.keyCompromise",
        ("cACompromise", 1): "CertificateList.tbsCertList.crlExtensions.FreshestCRL.CRLDistributionPoints.distributionPoint.reasons.cACompromise",
        ("affiliationChanged", 1): "CertificateList.tbsCertList.crlExtensions.FreshestCRL.CRLDistributionPoints.distributionPoint.reasons.affiliationChanged",
        ("superseded", 1): "CertificateList.tbsCertList.crlExtensions.FreshestCRL.CRLDistributionPoints.distributionPoint.reasons.superseded",
        ("cessationOfOperation", 1): "CertificateList.tbsCertList.crlExtensions.FreshestCRL.CRLDistributionPoints.distributionPoint.reasons.cessationOfOperation",
        ("certificateHold", 1): "CertificateList.tbsCertList.crlExtensions.FreshestCRL.CRLDistributionPoints.distributionPoint.reasons.certificateHold",
        ("privilegeWithdrawn", 1): "CertificateList.tbsCertList.crlExtensions.FreshestCRL.CRLDistributionPoints.distributionPoint.reasons.privilegeWithdrawn",
        ("aACompromise", 1): "CertificateList.tbsCertList.crlExtensions.FreshestCRL.CRLDistributionPoints.distributionPoint.reasons.aACompromise",
        "unused": "CertificateList.tbsCertList.crlExtensions.FreshestCRL.CRLDistributionPoints.distributionPoint.reasons.unused",
        "cRLIssuer": "CertificateList.tbsCertList.crlExtensions.FreshestCRL.CRLDistributionPoints.distributionPoint.cRLIssuer",
        "FreshestCRL": "CertificateList.tbsCertList.crlExtensions.FreshestCRL",
        "AuthorityInformationAccess": "CertificateList.tbsCertList.crlExtensions.AuthorityInformationAccess",
        "CRLEntryExtensions": "CertificateList.tbsCertList.revokedCertificates.crlEntryExtensions",
        "ReasonCode": "CertificateList.tbsCertList.revokedCertificates.crlEntryExtensions.ReasonCode",
        "unspecified": "CertificateList.tbsCertList.revokedCertificates.crlEntryExtensions.ReasonCode.unspecified",
        ("keyCompromise", 2): "CertificateList.tbsCertList.revokedCertificates.crlEntryExtensions.ReasonCode.keyCompromise",
        ("cACompromise", 2): "CertificateList.tbsCertList.revokedCertificates.crlEntryExtensions.ReasonCode.cACompromise",
        ("affiliationChanged", 2): "CertificateList.tbsCertList.revokedCertificates.crlEntryExtensions.ReasonCode.affiliationChanged",
        ("superseded", 2): "CertificateList.tbsCertList.revokedCertificates.crlEntryExtensions.ReasonCode.superseded",
        ("cessationOfOperation", 2): "CertificateList.tbsCertList.revokedCertificates.crlEntryExtensions.ReasonCode.cessationOfOperation",
        ("certificateHold", 2): "CertificateList.tbsCertList.revokedCertificates.crlEntryExtensions.ReasonCode.certificateHold",
        "removeFromCRL": "CertificateList.tbsCertList.revokedCertificates.crlEntryExtensions.ReasonCode.removeFromCRL",
        ("privilegeWithdrawn", 2): "CertificateList.tbsCertList.revokedCertificates.crlEntryExtensions.ReasonCode.privilegeWithdrawn",
        ("aACompromise", 2): "CertificateList.tbsCertList.revokedCertificates.crlEntryExtensions.ReasonCode.aACompromise",
        "InvalidityDate": "CertificateList.tbsCertList.revokedCertificates.crlEntryExtensions.InvalidityDate",
        "CertificateIssuer": "CertificateList.tbsCertList.revokedCertificates.crlEntryExtensions.CertificateIssuer",
        "signatureAlgorithm": "CertificateList.signatureAlgorithm",
        "signatureValue": "CertificateList.signatureValue",
    }


def _set_path(by_name: Dict[str, Dict], name: str, path: str) -> None:
    if name in by_name:
        by_name[name].setdefault("attributes", {})["path_address"] = path


def _add_or_replace_relationship(relationships: List[Dict], relationship: Dict) -> None:
    _remove_relationship(relationships, relationship)
    relationships.append(relationship)


def _remove_relationship(relationships: List[Dict], relationship: Dict) -> None:
    relationships[:] = [rel for rel in relationships if rel != relationship]
