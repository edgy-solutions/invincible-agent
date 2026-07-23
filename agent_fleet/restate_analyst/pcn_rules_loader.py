"""Load the pcn disposition ruleset from RDF into the runtime structure the proposer consumes.

This is the TTL→runtime boundary the arch review flagged as the NEXT discard-pattern instance — a
consumer that hand-enumerates producer fields. So the block rule is applied from the start: a rule's
conditions pass through as a BLOCK (every ``pcn:`` predicate carried, keyed by local name), not a
hand-maintained allowlist. A condition the schema grows tomorrow is CARRIED, not silently dropped;
the loudness lives one layer over, in ``validate_ruleset`` (unknown condition → rejected at ingest),
so schema drift fails at ingest rather than being silently ignored at evaluation.

It also stamps the ``ruleset_ref`` — the policy-artifact identity (label + content hash) — so every
proposal made under this ruleset can be traced in an ``audit_record`` after a newer ruleset lands.

Takes an ``rdflib.Graph`` (the driver populates it from the SUSTAINMENT graph via SPARQL, or by
parsing the TTL). rdflib lives at this boundary only; the pure evaluator stays dep-free.
"""
from __future__ import annotations

import hashlib

_PCN = "http://internal/sustainment/pcn#"
_DISPOSITION_RULE = _PCN + "DispositionRule"
_CHANGE_CLASS = _PCN + "changeClass"
# Predicates that are NOT rule conditions — carried through the block but not treated as conditions.
_NON_CONDITION_LOCALS = {"proposesDisposition"}


def _local(uri: str) -> str:
    """Local name of an IRI (after '#' or last '/')."""
    return str(uri).rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def load_disposition_rules(graph) -> tuple[list[dict], dict, str]:
    """(ruleset, category_classes, ruleset_ref) from a graph of disposition-rule triples.

    * ruleset — one dict per ``pcn:DispositionRule``, carrying EVERY ``pcn:`` predicate as
      ``{local_name: value}`` (block pass), plus ``id`` (the rule's local name). Booleans/strings
      are Python-native.
    * category_classes — ``{category_local: change_class_string}`` from ``pcn:changeClass`` triples.
    * ruleset_ref — ``<ontology_local_or_'pcn_disposition_rules'>@<12-hex content hash>``: stable for
      identical content, changes the moment any rule/classification triple changes.
    """
    import rdflib

    rules: list[dict] = []
    for r in graph.subjects(rdflib.RDF.type, rdflib.URIRef(_DISPOSITION_RULE)):
        rule: dict = {"id": _local(r)}
        for p, o in graph.predicate_objects(r):
            if not str(p).startswith(_PCN):
                continue  # skip rdfs:label/comment etc. — carry only the pcn: block
            key = _local(p)
            val = o.toPython() if isinstance(o, rdflib.Literal) else _local(o)
            rule[key] = val
        rules.append(rule)
    rules.sort(key=lambda d: d["id"])  # deterministic order

    category_classes: dict = {}
    for c, o in graph.subject_objects(rdflib.URIRef(_CHANGE_CLASS)):
        category_classes[_local(c)] = str(o)

    # ruleset_ref: human-readable label + content hash over the canonical triple set.
    onto = next(graph.subjects(rdflib.RDF.type, rdflib.URIRef("http://www.w3.org/2002/07/owl#Ontology")), None)
    label = _local(onto) if onto is not None else "pcn_disposition_rules"
    canon = "\n".join(sorted(f"{s} {p} {o}" for s, p, o in graph))
    digest = hashlib.sha256(canon.encode("utf-8")).hexdigest()[:12]
    ruleset_ref = f"{label}@{digest}"

    return rules, category_classes, ruleset_ref
