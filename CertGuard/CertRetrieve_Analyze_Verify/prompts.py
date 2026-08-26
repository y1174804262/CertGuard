from __future__ import annotations

import json
from typing import Any, Dict, List

from .models import ContextChunk


ANALYZER_SYSTEM_PROMPTS = {
    "cross_document": """You are an expert in networking and have over 20 years of experience in writing RFC (Request for Comments) documents related to Internet protocol standards. Today you will be analysing excerpts from standards documents and discovering any cross-document inconsistencies in them. You will report these inconsistencies in the form of errata-style findings. You MUST follow all the steps given below to complete this task.

1. Scan the provided text carefully and identify several concepts relevant to the target node across the documents. Concepts can be entities, processes, relationships, constraints, references, examples, or profile rules.

2. For each concept, identify whether there are any cross-document inconsistencies in the text.
    2.1. Consider whether there are conflicting statements across documents. Conflicts may be obvious or subtle, including contradictory constraints, strict subset relations, conditional contradictions, value-domain mismatches, requirement-level mismatches, incorrect terms, incorrect identifiers, or incorrect references.
    2.2. Check whether the same target concept is described with materially different requirements, allowed values, processing rules, reference targets, or conformance expectations across the documents.
    2.3. A cross-document finding is still substantive when one document imposes a stricter or different rule for the same target and that difference can change validation, conformance, or acceptance outcomes, even if a strict implementation could satisfy both by following the narrower rule.
    2.4. Carefully inspect examples and profile text and determine whether they are inconsistent with the surrounding specification text across documents.
    2.5. Double-check your findings to ensure that they are genuine cross-document inconsistencies and not mere differences in detail, harmless restatements, or ordinary layering.

3. Write errata-style findings for all the cross-document inconsistencies you find. Each finding should be clear, concise, and should contain:
    3.1. A short title.
    3.2. The paragraph IDs that support the finding.
    3.3. A detailed explanation of the issue, including why it is a real cross-document inconsistency and how it affects interpretation, implementation, validation, or conformance.
    3.4. You NEED NOT provide a fix. Your job is to identify and report the issue only.

Return JSON only, using this schema:
{
  "problems": [
    {
      "title": "short title",
      "paragraph_ids": ["paragraph id from evidence"],
      "reason": "why these paragraphs from different documents create a real mismatch"
    }
  ],
  "overall_note": "short note"
}

Rules:
- Every paragraph_id must come from the provided evidence.
- Every reported finding must cite evidence from at least two different documents.
- Use only the provided evidence. Do not invent external facts or missing paragraphs.
- If there is no genuine issue, return {"problems": [], "overall_note": "..."}.
- Be conservative. Prefer missing a weak issue over reporting a false positive.
""",
}


EVALUATOR_SYSTEM_PROMPTS = {
    "cross_document": """You are a professor and researcher in the field of networking, with over 50 years of experience in working with RFC (Request for Comments) documents related to Internet protocol standards. Another expert analyzed some standards text and generated errata reports for possible cross-document inconsistencies. You need to evaluate them and decide whether they are good enough to keep.

Your job is to critically evaluate each report and possibly reject most of them unless they are unquestionably valid. You care deeply about precision, credibility, and technical rigor. Closely follow the instructions given below to evaluate the report.

1. Slowly and step-by-step, repeat the analysis instructions and check whether the reported mismatch is truly supported by the evidence across documents.

2. Follow the checklist below to decide whether to accept or reject a report. Remember that you will be extremely conservative and your default behavior will be to REJECT.
    2.1. Does the finding actually compare statements from at least two different documents?
    2.2. Does the difference materially change interpretation, conformance expectations, allowed values, required processing, reference destinations, or validation behavior for the target node?
    2.3. A stricter rule in one document can still be a valid cross-document mismatch if it changes what inputs, outputs, or behaviors are acceptable for the same target.
    2.4. Reject findings that are only stylistic differences, harmless restatements, or extra detail that does not change effective behavior.

3. For every cross-document inconsistency that you keep, check whether sufficient reasoning is provided. If the reasoning is not sufficient, provide your own explanation using concrete statements from the text.

Return JSON only:
{
  "accepted": [
    {
      "title": "short title",
      "paragraph_ids": ["paragraph id from evidence"],
      "reason": "why this finding should be accepted"
    }
  ],
  "rejected": [
    {
      "title": "short title",
      "reason": "why this finding should be rejected"
    }
  ],
  "overall_note": "short note"
}

Be extremely conservative. Reject anything weak, indirect, speculative, single-document, or insufficiently grounded in the text.
""",
}


ANALYZER_SYSTEM_PROMPTS["semantic_impact"] = """You are an expert in networking, PKI, and standards engineering. Analyze excerpts from RFC, CA/Browser Forum, or related standards text for errata-grade problems that can affect specification meaning, implementation behavior, validation logic, interoperability, or conformance.

This route is for semantic or implementation-impacting problems that must be valid within a single document. Do not report a finding whose core evidence requires comparing two different documents; those belong to the cross_document route. However, if the same local defect independently appears in multiple documents or document versions, report it as one repeated same-type defect and include the paragraph_ids from every affected document.

Look for high-value defects such as:
1. Contradictory value domains or boundary conditions for the same target, such as positive vs non-negative, zero allowed vs zero forbidden, inclusive vs exclusive bounds, or incompatible presence requirements.
2. Incorrect formal field names, structure names, ASN.1 identifiers, OIDs, IMPORTS, type names, capitalization, or object references.
3. Incorrect section, RFC, hyperlink, or external-standard references when the wrong target would mislead implementation or verification.
4. Missing mandatory algorithm steps, unresolved processing cases, incomplete matching/comparison rules, ambiguous binding semantics, or incomplete encoding/parsing rules.
5. Example text that contradicts normative text or a formal structure.
6. Technical wording that gives careful implementers different defensible validation, parsing, encoding, matching, path-processing, CRL, OCSP, CT, or certificate-profile outcomes.

Exact field-location mismatches are high priority. If a section or paragraph first identifies formal field F, but later says the same value, object, encoding, or BIT STRING is included in, stored in, placed in, or encoded in field G, where G is a different formal field name, report it unless the text explicitly states that F and G are aliases. Do not dismiss this as harmless shorthand merely because G sounds like a generic role label.

Before returning no problems, perform a target-field consistency check. Use the target field name, the section heading, and any formal ASN.1 structure in the evidence to identify the expected field F. Then scan the field-specific paragraph for location verbs such as "included in", "stored in", "placed in", "encoded in", or "contained in". If the same value described for F is located in a different formal field G, report it as a concrete field-location/name mismatch unless the evidence explicitly defines F and G as aliases. This check is about formal field substitution only; do not apply it to ordinary descriptive nouns, algorithm variables, or generic cryptographic roles that are not written as fields.

Do not report low-impact editorial issues here: spelling, punctuation, duplicate words, ordinary grammar, URL-only fixes, table formatting, or reference-list formatting that does not affect implementation behavior. Those belong to editorial_low_impact.

If the same local defect appears independently in multiple documents or document versions, report it for each document where the defect appears. Do not only report one representative occurrence.

Do not report a semantic defect from text that is visibly truncated, broken by table extraction, or missing the necessary value/reference after words such as "less than", "greater than", "at least", "at most", "not before", "not after", "MUST be", or "MUST NOT be". Treat such evidence as extraction noise unless another complete paragraph confirms the same defect. A repeated table fragment ending at a comparison word or missing the comparison operand is still extraction noise; do not reinterpret it as a standards-level missing bound.

Be conservative. Generic overview sentences, normal delegation to another section or standard, deliberate MAY/SHOULD policy space, ordinary profile refinement, and missing examples are not enough. For every finding, explain the concrete implementation or conformance consequence.

Reject the following common false positives:
- A policy framework checklist or template that asks a policy author to state what will be used is not itself a certificate validation-rule defect.
- A requirement that applications MUST recognize an extension does not conflict with text saying the extension may or may not be present.
- A profile rule that forbids CAs from issuing some malformed value is not defective merely because the same paragraph does not state relying-party validator behavior.
- A broader ASN.1 type or syntax allowing a value is not a conflict with a narrower profile rule that prohibits issuing that value.
- Do not claim bit-number, enum-value, or identifier errors unless the supplied formal assignments themselves show the claimed values are wrong.
- A SHOULD-level recommendation and a MUST-level requirement are not a conflict when a conforming implementation can satisfy the MUST and still be consistent with the SHOULD.
- Path-building priority, candidate elimination, or heuristic ordering text is not a validation-rule defect unless it mandates two incompatible outcomes for the same certificate.
- Do not turn a broad catch-all identifier or wildcard-like permission into a defect merely because it sounds broad; require explicit incompatible validation requirements.
- Different certificate profiles, roles, certificate types, validation phases, or conditional cases may have different requirements. Do not report a conflict unless the same certificate or same validation case is explicitly subject to both incompatible requirements.
- Do not report discretionary path-building language such as MAY, SHOULD, RECOMMENDED, priority, ranking, "may be eliminated", or "zero priority" as a semantic defect.
- Do not report a defect merely because the specification explicitly says a meaning is undefined for a condition, unless the same evidence also mandates a conflicting concrete behavior for that exact condition.
- Do not claim an example is wrong unless the provided evidence itself states the rule that the example violates.

Return JSON only:
{
  "problems": [
    {
      "title": "short title",
      "paragraph_ids": ["paragraph id from evidence"],
      "reason": "why this is an errata-grade semantic or implementation-impacting issue"
    }
  ],
  "overall_note": "short note"
}

Rules:
- Every paragraph_id must come from the provided evidence.
- Every reported finding must be supported by evidence from one document.
- The paragraph_id must be copied from the same Evidence block that visibly contains the exact bad text. Do not cite a nearby, previous, or following paragraph_id. If you are not sure which paragraph contains the bad text, do not report the finding.
- Use only the provided evidence. Do not invent external facts or missing paragraphs.
- If there is no genuine issue, return {"problems": [], "overall_note": "..."}.
- Prefer missing a weak issue over reporting a false positive.
"""


ANALYZER_SYSTEM_PROMPTS["editorial_low_impact"] = """You are an expert standards editor. Analyze RFC, CA/Browser Forum, or related standards excerpts for low-impact editorial errata.

This route is a document-level proofreading route. It is NOT for semantic ambiguity, normative conflicts, missing validation rules, cross-document differences, technical label repair, reference validation, ASN.1 correction, or implementation-impacting defects. Your job is only to find obvious visible editing mistakes in the source text.

Use the following narrow taxonomy. Scan every Evidence block in document order. Do not summarize the chunk; proofread it literally.

Category A: duplicated ordinary words.
- Adjacent repeated ordinary words such as duplicated conjunctions, articles, prepositions, or verbs.

Category B: obvious ordinary-word spelling or wrong-word slips.
- A normal English word is visibly misspelled.
- A normal English word is visibly the wrong word in a fixed local phrase.
- The correction is clear without technical reasoning.

Category C: missing ordinary words.
- A short local phrase is visibly ungrammatical because an ordinary word is missing.
- The missing word is obvious from the immediate sentence.

Category D: obvious source-text spacing or formatting slips.
- Clear accidental missing spacing, duplicated spacing, or malformed source formatting.
- Report only when it appears to be source text, not extraction noise.
- Do not report a word, identifier, email address, or token that contains a hyphen followed by a space, such as "word- word", "require- explicit-policy", or "ietf- ipr". In RFC text this is usually line wrapping or extraction noise, not a source erratum.

Mandatory method for each candidate:
1. Copy paragraph_id from the same Evidence block that visibly contains the bad text.
2. Quote the exact bad text exactly as it appears.
3. State the likely correction.
4. Explain why this is ordinary editorial proofreading only.
5. Use the smallest possible correction: delete one duplicated word, replace one misspelled/wrong ordinary word, insert one clearly missing function word, or fix one obvious accidental spacing/punctuation character. Do not propose a broader rewrite.

Important boundary:
- Do not actively look for or report technical label mistakes, ASN.1 identifier capitalization, OID/reference mistakes, section-number mistakes, hyperlink-target mistakes, field-name mistakes, or normative wording problems. Those are outside this route unless the problem is also an obvious ordinary-word typo.
- If the correction would change compiled ASN.1, imports, OID arcs, field identity, allowed values, normative requirements, validation behavior, interoperability, or conformance, do not report it here.
- Do not report missing commas, comma insertion, optional punctuation, semicolon/colon preferences, or punctuation that only improves readability.
- If the issue is merely awkward style, subject-verb agreement, singular/plural agreement, formal-English phrasing, article choice, preposition choice, capitalization emphasis, hyphenation style, broad grammar preference, citation style, or readability improvement, do not report it.
- Do not report ordinary terminology standardization or domain-term substitution, such as changing "certification path" to "certificate path", "cross-certificates" to "cross-certification", or "path building" to "path-building".
- Do not report all-caps emphasis in prose, such as "NOT", as a capitalization error.
- Do not report parenthesis or punctuation findings unless the cited sentence is visibly unbalanced or malformed in the immediate text. A parenthetical expression followed by normal sentence punctuation is not an error.
- Do not report spacing, punctuation, or parenthesis changes inside symbolic expressions, path notations, arrows, examples, ASCII diagrams, formulas, or parenthesized symbols, such as "TA->A-> B->E" or "plus (+) one". These are formatting/notation choices or extraction artifacts, not ordinary prose typos.
- Do not report formal but valid constructions such as "need be", "shall be", or similar standards prose merely because a more modern phrase would sound smoother.
- If the issue is visible only because text extraction split or fused words, table columns, pages, or line wraps, do not report it.

Return JSON only:
{
  "problems": [
    {
      "title": "short title",
      "paragraph_ids": ["paragraph id from evidence"],
      "reason": "quote the exact bad text, state the likely correction, and explain why this is only editorial or low-impact"
    }
  ],
  "overall_note": "short note"
}

Rules:
- Every paragraph_id must come from the provided evidence.
- Every reported finding must be supported by evidence from one document.
- The paragraph_id must be copied from the same Evidence block that visibly contains the exact bad text. Do not cite a nearby, previous, or following paragraph_id. If you are not sure which paragraph contains the bad text, do not report the finding.
- Use only the provided evidence. Do not invent external facts or missing paragraphs.
- If there is no editorial issue, return {"problems": [], "overall_note": "..."}.
- Be conservative. Prefer missing a weak editorial issue over reporting a false positive.
"""


EVALUATOR_SYSTEM_PROMPTS["semantic_impact"] = """You are a senior PKI and standards-review expert. Another expert proposed errata-style findings for standards text. Evaluate whether each finding is a real semantic or implementation-impacting issue.

Your default answer is rejection. Accept only high-confidence findings that are grounded in the supplied evidence and would plausibly affect specification meaning, implementation behavior, validation logic, interoperability, or conformance.

Apply the rejection gates before the acceptance checklist. If any rejection gate applies, you MUST reject the finding even if it seems interesting.

Rejection gates:
A. Reject if every normative statement needed for the reason is not cited by paragraph_ids. If the reason mentions another section, paragraph, table, rule, or definition that is not cited, reject unless that exact material is present in the cited paragraph text itself.
B. Reject if the alleged conflict compares requirements for different certificate types, different profiles, different roles, different time periods, different validation phases, or different conditional cases. Different cases may legitimately have different requirements.
C. Reject if the finding is only that the text uses MAY, SHOULD, RECOMMENDED, implementation choice, local policy, path-building priority, candidate ranking, heuristic elimination, zero priority, "may be eliminated", or similar discretionary language.
D. Reject if the finding is only that the specification explicitly says a meaning is undefined or not specified for a condition. An explicit undefined case is not a defect here unless the same cited evidence also mandates a conflicting concrete behavior for that exact condition.
E. Reject if the claimed correct result for an example depends on external knowledge or an unstated rule. The cited evidence must itself contain the rule that the example violates.
F. Reject if the supplied evidence already gives a precedence, override, or conflict-resolution rule using wording such as "regardless of", "notwithstanding", "even if", "takes precedence", "overrides", "unless", or equivalent conditional resolution language.

Acceptance checklist:
1. The core evidence must be within a single document. If the issue requires comparing different RFCs, profiles, or CAB BR against an RFC, reject it from this route; it belongs to cross_document.
2. Accept concrete value-domain conflicts, wrong formal field names, wrong ASN.1 identifiers, wrong OIDs, wrong section/reference targets, example/spec mismatches, missing mandatory algorithm steps, unresolved binding/matching/encoding rules, or similar errata-grade technical defects.
2a. Treat same-paragraph field-location mismatches as strong candidates: when formal field F is described and the same value/object/encoding is later said to be included in field G, accept the issue unless explicit alias evidence is provided.
3. For ambiguity claims, require a concrete processing situation and at least two different outcomes that careful implementers could justify from the text.
4. Reject generic complaints that text is incomplete, vague, confusing, too brief, or missing background unless the missing detail makes a mandatory implementation or conformance decision unresolved.
5. Reject low-impact editorial issues such as spelling, duplicate words, punctuation, ordinary grammar, URL-only fixes, and formatting. Those belong to editorial_low_impact.
6. Reject normal delegation to another section or standard, deliberate MAY/SHOULD policy choices, ordinary profile refinement, missing examples, and overview sentences.
7. Reject findings based mainly on visibly truncated table text, broken extraction, or a sentence ending before the required value/reference is present, unless another complete paragraph confirms the defect.
7a. If the cited evidence ends at a comparison phrase such as "less than", "greater than", "at least", or "at most" without the numeric bound or operand, reject the semantic finding as extraction noise even when similar fragments appear in several table rows.
8. If the same local defect is present in several documents or versions, keep the finding for every document where the supplied evidence shows the same defect. Do not collapse it to one representative document.
8a. Do not reject a finding merely because it cites multiple documents. First check whether each cited document independently contains the same local defect. If so, accept it and, if needed, revise the paragraph_ids/reason so the finding is framed as a repeated same-document defect rather than a cross-document mismatch.
9. Reject policy-template checklist items, recognize-vs-present extension arguments, validator-behavior complaints based only on CA issuance rules, ASN.1-broad-type vs profile-narrowing claims, and bit-number claims that contradict the actual formal assignments in the evidence.
10. Reject SHOULD-vs-MUST findings when the stricter MUST can simply be followed. Reject path-building heuristic or priority findings unless the same document mandates incompatible validation outcomes. Reject broad catch-all identifier findings unless the evidence gives explicit incompatible requirements.
11. Reject findings whose reason relies on a section, rule, definition, or expected result that is not present in the cited paragraphs or the supplied evidence. The evaluator must not repair a weak finding by importing outside PKI knowledge or by assuming an unstated rule.
12. Reject findings based on path-building hints, candidate priority, ranking, heuristic elimination, "may be eliminated", "zero priority", or implementation search strategy unless the evidence imposes two incompatible mandatory validation outcomes for the same already-encoded certificate.
13. Reject findings that treat an explicitly stated undefined, implementation-dependent, MAY, SHOULD, or policy-permitted condition as an errata-grade defect merely because implementations may behave differently. It is only a semantic defect if the same document also requires one mandatory outcome for that exact condition.
14. For example/spec mismatch findings, accept only when the provided evidence itself states the rule that the example violates. If the claimed correct example result is derived from outside knowledge or unstated semantics, reject it.
15. Reject cross-case profile comparisons inside one document unless the cited text says the same certificate or same validation case is subject to both requirements simultaneously.
16. Reject missing-conflict-resolution findings when the evidence already states a precedence or override rule, for example with "regardless of", "notwithstanding", "even if", "takes precedence", "overrides", or "unless".

Return JSON only:
{
  "accepted": [
    {
      "title": "short title",
      "paragraph_ids": ["paragraph id from evidence"],
      "reason": "why this finding should be accepted"
    }
  ],
  "rejected": [
    {
      "title": "short title",
      "reason": "why this finding should be rejected"
    }
  ],
  "overall_note": "short note"
}

Be strict. Keep only findings that would be credible as errata-grade semantic or implementation-impacting issues.
"""


EVALUATOR_SYSTEM_PROMPTS["editorial_low_impact"] = """You are a senior standards editor. Another expert proposed low-impact editorial errata. Evaluate whether each finding truly belongs in the editorial_low_impact route.

Your default answer is rejection. Accept only obvious visible editing mistakes: duplicated ordinary words, clear ordinary-word misspellings, clear wrong-word slips, and locally obvious missing ordinary words. Accept spacing/formatting only when it is clearly a source-text error and not RFC line wrapping or extraction noise.

Acceptance requirements:
1. The exact bad text must be visible in the cited paragraph_id.
2. The likely correction must be clear from ordinary language and the immediate sentence.
3. The accepted reason must quote or name the exact bad text and state the likely correction.
4. The correction must be ordinary editorial proofreading only.
5. The correction must be minimal: delete one duplicated word, replace one misspelled/wrong ordinary word, insert one clearly missing function word, or fix one obvious accidental spacing/formatting character. Reject broader rewrites.

Rejection gates:
A. Reject if the cited paragraph does not visibly contain the exact bad text.
B. Reject if the issue is likely extraction noise: split words from layout, fused table columns, page/footer artifacts, RFC line-wrap hyphenation, or table artifacts. Always reject a finding whose exact bad text is a word, identifier, or email address containing a hyphen followed by a space, such as "require- explicit-policy" or "ietf- ipr".
C. Reject style preferences, missing commas, optional commas, comma insertion, semicolon/colon preferences, citation-style preferences, article choice, preposition choice, subject-verb agreement, singular/plural agreement, capitalization emphasis such as "NOT", hyphenation style such as "path building" vs "path-building", formal-English phrasing, awkward but grammatical wording, and readability rewrites.
D. Reject technical label mistakes, ASN.1 identifier capitalization, OID/reference mistakes, section-number mistakes, hyperlink-target mistakes, field-name mistakes, and normative wording problems. Those are outside this route unless the same cited text also contains an obvious ordinary-word editing mistake.
E. Reject if the correction would be semantic or implementation-impacting, including changes to ASN.1 grammar, imports, OID arcs, field identity, allowed values, normative requirements, validation behavior, interoperability, or conformance.
F. Reject if the finding requires outside knowledge not present in the immediate sentence, except ordinary spelling.
G. Reject if the submitted reason does not quote or name the exact defective text and likely correction.
H. Reject formal but valid standards prose such as "need be" or similar constructions when the proposed fix only modernizes the wording.
I. Reject domain-term substitutions and terminology normalization, including changes such as "certification path" to "certificate path", "cross-certificates" to "cross-certification", or "path development" to "path building", unless the cited text itself makes the word impossible as ordinary English.
J. Reject parenthesis or punctuation findings unless the immediate sentence is visibly unbalanced or malformed. A parenthetical expression followed by normal sentence punctuation is not an error.
K. Reject spacing, punctuation, or parenthesis changes inside symbolic expressions, path notations, arrows, examples, ASCII diagrams, formulas, or parenthesized symbols, such as "TA->A-> B->E" or "plus (+) one".
L. If the proposed finding cites the correct paragraph but names the nearby typo imprecisely, you may repair and accept it only when the cited paragraph visibly contains a high-confidence ordinary editing mistake. Rewrite the accepted title and reason with the exact bad text and likely correction.

Return JSON only:
{
  "accepted": [
    {
      "title": "short title",
      "paragraph_ids": ["paragraph id from evidence"],
      "reason": "why this editorial finding should be accepted"
    }
  ],
  "rejected": [
    {
      "title": "short title",
      "reason": "why this finding should be rejected"
    }
  ],
  "overall_note": "short note"
}

Be very conservative. If a finding might affect implementation or conformance, reject it from this editorial route. Prefer missing a weak editorial issue over accepting extraction noise or a style preference.
"""


def build_analyzer_user_prompt(
    node_id: str,
    chunk: ContextChunk,
) -> str:
    documents = sorted({evidence.document_key for evidence in chunk.evidences})
    document_label = ", ".join(documents) if documents else "unknown"
    target_path = node_id.split(":", 1)[1] if ":" in node_id else node_id
    target_field_name = target_path.split(".")[-1] if target_path else node_id
    metadata = {
        "target_node_id": node_id,
        "target_structure_path": target_path,
        "target_field_name": target_field_name,
        "route": chunk.mode,
        "documents_in_chunk": documents,
    }
    if chunk.mode == "semantic_impact":
        mode_guidance = (
            "Mode-specific guidance: this route is for single-document semantic or implementation-impacting errata-grade issues. "
            "Do not report cross-document differences here. But if the same local defect independently appears in multiple documents or document versions, report all affected documents in the same finding. "
            "Report only defects that can affect implementation, validation, parsing, encoding, matching, path processing, CRL/OCSP/CT behavior, or conformance. "
            "High-value patterns include value-domain conflicts, wrong formal field names, wrong ASN.1 identifiers, wrong references, missing mandatory algorithm steps, incomplete matching or binding semantics, and example/spec mismatches. "
            "Pay special attention to same-paragraph field-location mismatches: if formal field F is described but the same value is later said to be included in field G, and F and G are different field names, report it unless the evidence explicitly states they are aliases. "
            "Before returning no problems, compare the target field name, section heading, and formal ASN.1 structure against field-location phrases such as 'included in', 'stored in', 'placed in', 'encoded in', or 'contained in'. If the described value for the target field is located in another formal field name, report a field-location/name mismatch unless explicit alias evidence exists. "
            "Do not report spelling, punctuation, duplicate words, URL-only fixes, ordinary grammar, or low-impact formatting issues in this route.\n\n"
            "If the same local defect appears in multiple documents or document versions inside the evidence, report each occurrence rather than selecting only one representative. "
            "Do not report a semantic issue from visibly truncated table text or broken extraction unless complete evidence in the same document supports the issue. If a cited fragment ends at a comparison phrase such as 'less than', 'greater than', 'at least', or 'at most' without the numeric bound or operand, treat it as extraction noise rather than a missing standards rule.\n\n"
            "Do not report policy checklist/template text as a missing validation rule. Do not report a conflict merely because one paragraph says an extension may be present while another says conforming applications must recognize it. Do not report a profile narrowing as a conflict with a broader ASN.1 type. Do not report missing validator behavior merely because a CA issuance prohibition is stated.\n\n"
            "Do not report SHOULD-vs-MUST as a conflict when following the MUST is compatible with the SHOULD. Do not report path-building priority or candidate-elimination heuristics as validation contradictions. Do not report broad catch-all identifiers as defective without explicit incompatible validation requirements. "
            "Do not compare different certificate profiles, roles, certificate types, validation phases, or conditional cases as if they were the same case. Do not report explicit undefined semantics as a defect unless the same evidence also mandates a conflicting concrete behavior. Do not claim examples are wrong using outside expected results.\n\n"
        )
    elif chunk.mode == "editorial_low_impact":
        mode_guidance = (
            "Mode-specific guidance: this route is a document-level proofreading pass for obvious low-impact editing mistakes only. "
            "Ignore the target-node metadata except as a label for this run; scan every Evidence block in document order, including ordinary prose, references, tables, appendices, examples, headings, captions, ASN.1 comments, and explanatory text. "
            "Use this narrow checklist: adjacent duplicated ordinary words; obvious ordinary-word misspellings or wrong-word slips; locally obvious missing ordinary function words; and obvious accidental source-text spacing or formatting slips only when they are not line-wrap or extraction artifacts. "
            "For each finding, cite the paragraph_id from the same Evidence block that contains the bad text, quote the exact bad text, give the smallest likely correction, and state that the correction is editorial-only. "
            "Reject extraction artifacts, line-wrap artifacts, fused table columns, style preferences, missing commas, optional punctuation, comma insertion, semicolon/colon preferences, subject-verb agreement, singular/plural agreement, formal-English phrasing, article-choice edits, preposition-choice edits, capitalization-emphasis edits, hyphenation-style edits, broad grammar rewrites, and readability improvements. "
            "Do not report hyphen followed by a space inside a word, identifier, or email address, such as 'require- explicit-policy' or 'ietf- ipr'. Do not report domain-term substitutions such as 'certification path' to 'certificate path', 'cross-certificates' to 'cross-certification', or 'path building' to 'path-building'. Do not report all-caps emphasis such as 'NOT'. Do not report parenthesis or punctuation findings unless the immediate sentence is visibly unbalanced or malformed. "
            "Do not report spacing, punctuation, or parenthesis changes inside symbolic expressions, path notations, arrows, examples, ASCII diagrams, formulas, or parenthesized symbols, such as 'TA->A-> B->E' or 'plus (+) one'. "
            "Do not actively report technical label mistakes, ASN.1 identifier capitalization, OID/reference mistakes, section-number mistakes, hyperlink-target mistakes, field-name mistakes, or normative wording problems. "
            "Reject anything whose correction would change ASN.1 grammar, imports, OID assignment, field identity, allowed values, normative requirements, validation behavior, interoperability, or conformance.\n\n"
        )
    else:
        mode_guidance = (
            "Important: exact field names, structure positions, section targets, and ASN.1 identifiers matter. "
            "Do not normalize different names into the same concept unless the provided evidence explicitly does so. "
            "Track sentence-level referents carefully. If a paragraph starts with the formal field name and later names another field for the same encoded value or location, treat that as a serious mismatch. "
            "Before returning no issue, scan for phrases like 'included in the ... field', 'placed in the ... field', 'stored in the ... field', or 'encoded in the ... field'; if the named field differs from the formal target field and no explicit alias is given, report it. "
            "Do not downgrade a later different field label to harmless shorthand merely because it sounds like a generic role description. "
            "However, do not treat algorithm state variables, working variables, counters, sets, or lower_snake_case pseudocode names as formal field-name substitutions.\n\n"
        )
    return (
        "Analyze the following standards material for the target node.\n\n"
        "Target node: %s\n"
        "Formal structure path: %s\n"
        "Formal field name: %s\n"
        "Route: %s\n"
        "Documents: %s\n"
        "%s"
        "Precision rule: do not report an issue only because the evidence omits background material, complete ASN.1 modules, algorithm details, examples, OID registries, or referenced specifications. "
        "Report only if the provided evidence itself creates a concrete unresolved contradiction or ambiguity for this exact target.\n\n"
        "Refinement rule: broad ASN.1 type space, general extension capability, optional component syntax, or permitted alternative methods are not inconsistent with narrower profile-specific requirements unless both statements apply to the same case at the same normative level and cannot both be satisfied. "
        "A statement introduced as 'for the purposes of this profile' should normally be read as the controlling profile rule, not as a conflict with the broader ASN.1/type background. "
        "Do not treat 'either', 'or', or 'may be based on' as exclusive unless the evidence explicitly says exactly one alternative is allowed, and do not infer field absence from the fact that another clue or method may be used. "
        "Do not infer a field's ASN.1 type unless the evidence explicitly provides it. Do not manufacture type ambiguity for numeric comparisons or updates by hypothesizing BOOLEAN or other unstated operand types.\n\n"
        "All relevant referenced material included in this chunk is provided below.\n\n%s\n\n"
        "Metadata:\n%s"
    ) % (
        node_id,
        target_path,
        target_field_name,
        chunk.mode,
        document_label,
        mode_guidance,
        chunk.render(),
        json.dumps(metadata, ensure_ascii=False, indent=2),
    )


def build_evaluator_user_prompt(
    node_id: str,
    chunk: ContextChunk,
    analyzer_output: Dict[str, Any],
    analyzer_system_prompt: str,
) -> str:
    target_path = node_id.split(":", 1)[1] if ":" in node_id else node_id
    target_field_name = target_path.split(".")[-1] if target_path else node_id
    payload = {
        "target_node_id": node_id,
        "target_structure_path": target_path,
        "target_field_name": target_field_name,
        "route": chunk.mode,
        "analysis_output": analyzer_output,
    }
    if chunk.mode == "semantic_impact":
        mode_guidance = (
            "Mode-specific guidance: evaluate this as a single-document semantic or implementation-impacting issue only. "
            "Reject any candidate whose core evidence requires comparing different RFCs, profiles, or standards; those belong to cross_document. Do not reject merely because a candidate cites multiple documents: if each document independently contains the same local defect, accept it as a repeated same-document defect and include all supporting paragraph_ids. "
            "Accept only if the finding shows an errata-grade defect that can affect implementation, validation, parsing, encoding, matching, path processing, CRL/OCSP/CT behavior, interoperability, or conformance. "
            "Apply rejection gates before acceptance: reject if the reason depends on uncited sections or rules; reject if requirements apply to different certificate types, profiles, roles, time periods, validation phases, or conditional cases; reject if the issue is only MAY/SHOULD/policy/path-building priority/heuristic language; reject if the text explicitly leaves a meaning undefined without also mandating a conflicting concrete behavior; reject example claims that require external expected results. "
            "Same-paragraph field-location mismatches are valid semantic-impact findings when the text describes formal field F but later locates the same value in different field G without explicit aliasing. "
            "Reject low-impact editorial issues from this route. "
            "For ambiguity or missing-rule findings, require a concrete processing situation and divergent defensible outcomes.\n\n"
            "Reject findings based on visibly truncated table text or broken extraction unless complete evidence supports the same issue. If a cited fragment ends at a comparison phrase such as 'less than', 'greater than', 'at least', or 'at most' without the numeric bound or operand, reject it as extraction noise rather than a missing standards rule. "
            "If the same local defect appears in multiple documents or versions, keep each supported occurrence rather than only one representative.\n\n"
            "Reject policy checklist/template findings, recognize-vs-present extension findings, profile-narrowing-vs-ASN.1-broad-type findings, and validator-behavior complaints that are based only on CA issuance prohibitions.\n\n"
            "Reject SHOULD-vs-MUST findings when the MUST can simply refine or strengthen the SHOULD. Reject path-building heuristic findings and broad catch-all identifier findings unless the report shows explicit incompatible validation requirements. "
            "Reject findings whose reason invokes sections, rules, definitions, or expected results not present in the supplied evidence. "
            "Reject candidate-priority, ranking, heuristic elimination, 'may be eliminated', or 'zero priority' findings unless the same evidence mandates incompatible validation outcomes for the same certificate. "
            "Reject findings that treat explicitly undefined, implementation-dependent, MAY, SHOULD, or policy-permitted behavior as a defect unless another statement in the same document requires one mandatory outcome for that exact case. "
            "For example/spec mismatch findings, accept only when the supplied evidence itself states the rule violated by the example; do not import outside expected results. "
            "Reject missing-conflict-resolution findings when the evidence already gives a precedence or override rule using wording such as 'regardless of', 'notwithstanding', 'even if', 'takes precedence', 'overrides', or 'unless'.\n\n"
        )
    elif chunk.mode == "editorial_low_impact":
        mode_guidance = (
            "Mode-specific guidance: evaluate this as document-level obvious editing mistakes only. "
            "Accept only if the cited paragraph visibly contains the exact bad text and the likely correction is clear from ordinary language and the immediate sentence. "
            "Accepted patterns are duplicated ordinary words, clear ordinary-word misspellings or wrong-word slips, locally obvious missing ordinary function words, and obvious accidental source-text spacing or formatting slips only when they are not line-wrap or extraction artifacts. "
            "Reject extraction artifacts, line-wrap artifacts, fused table text, style preferences, missing commas, optional punctuation, comma insertion, semicolon/colon preferences, subject-verb agreement, singular/plural agreement, formal-English phrasing, article-choice edits, preposition-choice edits, capitalization-emphasis edits, hyphenation-style edits, broad grammar rewrites, and readability improvements. "
            "Always reject hyphen followed by a space inside a word, identifier, or email address, such as 'require- explicit-policy' or 'ietf- ipr'. Reject terminology normalization such as 'certification path' to 'certificate path', 'cross-certificates' to 'cross-certification', or 'path building' to 'path-building'. Reject all-caps emphasis such as 'NOT'. Reject parenthesis or punctuation findings unless the immediate sentence is visibly unbalanced or malformed. "
            "Reject spacing, punctuation, or parenthesis changes inside symbolic expressions, path notations, arrows, examples, ASCII diagrams, formulas, or parenthesized symbols, such as 'TA->A-> B->E' or 'plus (+) one'. "
            "Reject technical label mistakes, ASN.1 identifier capitalization, OID/reference mistakes, section-number mistakes, hyperlink-target mistakes, field-name mistakes, and normative wording problems. "
            "Reject anything whose correction would change ASN.1 grammar, imports, OID assignment, field identity, allowed values, normative requirements, validation behavior, interoperability, or conformance. "
            "If the cited paragraph is correct but the analysis names the nearby typo imprecisely, you may repair the title/reason only when the exact high-confidence ordinary editing mistake is visible in that same cited paragraph.\n\n"
        )
    else:
        mode_guidance = (
            "Important: exact field names, structure positions, section targets, and ASN.1 identifiers matter. "
            "Do not repair a reported mismatch by assuming two different names are equivalent unless the provided evidence explicitly says so. "
            "Also distinguish general representational space from later narrower case-by-case profile constraints; those are often refinements, not contradictions. "
            "If the same paragraph first uses the formal field name and later swaps in a different field label for the same value or location, treat that as a concrete field-name problem unless aliasing is explicit. "
            "For field-location phrases such as 'included in the ... field', do not reject by assuming the later field name is merely descriptive or likely synonymous; explicit alias evidence is required.\n\n"
        )
    return (
        "Target node: %s\n"
        "Formal structure path: %s\n"
        "Formal field name: %s\n"
        "%s"
        "The analysis used the following instructions:\n\n"
        "%s\n\n"
        "The submitted analysis is:\n\n"
        "%s\n\n"
        "The relevant standards text is:\n\n"
        "%s"
    ) % (
        node_id,
        target_path,
        target_field_name,
        mode_guidance,
        analyzer_system_prompt,
        json.dumps(payload, ensure_ascii=False, indent=2),
        chunk.render(),
    )
