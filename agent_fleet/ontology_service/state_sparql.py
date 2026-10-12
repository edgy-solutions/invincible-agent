"""SPARQL builders for the pcn disposition-state write + step-5 query — PURE + rdflib-validatable.

Extracted from main.py's route handlers so the SPARQL is unit-tested (parse-validated) BEFORE it meets
Fuseki — the same rdflib discipline the TTLs already get. The f-string/plain-string brace bug that
cost a build/roll cycle (four literal braces → Fuseki 400) is exactly what a parse test catches in
milliseconds. Any new SPARQL template (the driver will mint more) belongs here, with a validating test.
"""
from __future__ import annotations

_PCN_NS = "http://internal/sustainment/pcn#"
_INSTANCES_GRAPH = "http://internal/SUSTAINMENT_INSTANCES"


def sparql_lit(v: str) -> str:
    """Escape a string for a SPARQL string literal (quotes / backslashes / newlines)."""
    return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "")


# Steward-correction provenance (optional, stored BESIDE the item's identity -- never as a re-key).
# payload key -> predicate local name. Absent means unchanged: a caller that sends none of these
# gets byte-identical SPARQL to before this existed.
PROVENANCE_PREDICATES = {
    "obtained_via": "obtainedVia",
    "corrected_by": "correctedBy",
    "extracted_value": "extractedValue",
    "corrected_value": "correctedValue",
    "evidence": "evidence",
}


def build_item_state_update(
    subject_iri: str, disposition_state: str, disposition_ref: str, proposed_by_ruleset: str = "",
    provenance: "dict | None" = None,
) -> str:
    """Idempotent state stamp: delete any prior disposition triples for the subject, then insert.
    Re-stamping is a no-op-equivalent, which the two-write convergence relies on. Values escaped.

    ``provenance`` (optional): steward-correction facts stamped on the SAME node, beside the
    disposition. Only keys in PROVENANCE_PREDICATES are honoured; a None value is skipped (an added
    row has no extracted value). The subject IRI is never altered by it."""
    g, ns, s = _INSTANCES_GRAPH, _PCN_NS, subject_iri
    ins = [
        f'<{s}> <{ns}dispositionState> "{sparql_lit(disposition_state)}" .',
        f'<{s}> <{ns}dispositionRef> "{sparql_lit(disposition_ref)}" .',
    ]
    if proposed_by_ruleset:
        ins.append(f'<{s}> <{ns}proposedByRuleset> "{sparql_lit(proposed_by_ruleset)}" .')
    dels = [
        f'DELETE WHERE {{ GRAPH <{g}> {{ <{s}> <{ns}dispositionState> ?a }} }} ;\n'
        f'DELETE WHERE {{ GRAPH <{g}> {{ <{s}> <{ns}dispositionRef> ?b }} }} ;\n'
        f'DELETE WHERE {{ GRAPH <{g}> {{ <{s}> <{ns}proposedByRuleset> ?c }} }} ;\n'
    ]
    for key, pred in PROVENANCE_PREDICATES.items():
        if provenance and key in provenance:
            dels.append(f'DELETE WHERE {{ GRAPH <{g}> {{ <{s}> <{ns}{pred}> ?p_{pred} }} }} ;\n')
            if provenance[key] is not None:
                ins.append(f'<{s}> <{ns}{pred}> "{sparql_lit(provenance[key])}" .')
    ins_block = " ".join(ins)
    return "".join(dels) + f'INSERT DATA {{ GRAPH <{g}> {{ {ins_block} }} }}'


def build_instances_by_property_query(disposition_state: str) -> str:
    """Step-5: all parts in a disposition state. Runs through engine-o's execute_sparql read-union
    (which spans SUSTAINMENT_INSTANCES), so it needs no GRAPH clause of its own."""
    ns = _PCN_NS
    return (
        f'SELECT ?part ?ref ?ruleset WHERE {{ ?part <{ns}dispositionState> "{sparql_lit(disposition_state)}" . '
        f'OPTIONAL {{ ?part <{ns}dispositionRef> ?ref }} OPTIONAL {{ ?part <{ns}proposedByRuleset> ?ruleset }} }} '
        f'ORDER BY ?part'
    )
