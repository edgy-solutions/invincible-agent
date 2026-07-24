"""SPARQL builders for the GENERIC policy-rules reader — PURE + rdflib parse-validatable.

Born generic per the generic-at-birth rule (AGENTS.md): the route ``/policy_rules`` and these builders
know nothing about any one domain. The rule VOCABULARY (the rule-type IRI, the change-class predicate)
is a PARAMETER, not baked in; the caller's domain arrives as the ``domain`` graph name + the vocab
config. engine-o is a thin typed-triples reader — it CONSTRUCTs the rule subgraph and returns Turtle;
the loading/validation lives with the loader (restate_analyst), so there is no second copy of the
ingest-gate validator.

Any new SPARQL template belongs in a pure module with a parse-validating test (the brace-bug lesson,
[[project_pcn_driver_arc]] preconditions). CONSTRUCT/ASK forms parse-validate the same way SELECT does.
"""
from __future__ import annotations

_OWL_ONTOLOGY = "http://www.w3.org/2002/07/owl#Ontology"


def _san(domain: str) -> str:
    """Graph names are internal + controlled; keep only alnum/underscore (no injection surface)."""
    return "".join(c for c in (domain or "") if c.isalnum() or c == "_") or "MAINTENANCE"


def _scope(domain: str) -> tuple[str, str]:
    """The read-union a domain's triples live in: vocabulary graph + instances graph (mirrors
    engine-o's execute_sparql scoping so this reader sees the same content any consumer would)."""
    vocab = f"http://internal/{_san(domain)}"
    return vocab, f"{vocab}_INSTANCES"


def build_rules_construct(
    domain: str,
    *,
    rule_type_iri: str,
    change_class_pred: str,
    ontology_type_iri: str = _OWL_ONTOLOGY,
) -> str:
    """CONSTRUCT every triple ABOUT a rule individual, the ruleset ontology, or a change-class subject
    within the named graph (+ its instances union). Returns Turtle the loader parses with types intact
    — CONSTRUCT preserves Literal-vs-IRI (a SELECT through execute_sparql stringifies both, which would
    make ``bool("false")`` truthy and silently break boolean rule conditions). The rule vocabulary is a
    parameter: nothing here is domain-specific."""
    vocab, inst = _scope(domain)
    return (
        "CONSTRUCT { ?s ?p ?o } WHERE { "
        f"VALUES ?__g {{ <{vocab}> <{inst}> }} GRAPH ?__g {{ "
        "?s ?p ?o . "
        f"{{ ?s a <{rule_type_iri}> }} "
        f"UNION {{ ?s a <{ontology_type_iri}> }} "
        f"UNION {{ ?s <{change_class_pred}> ?__cc }} "
        "} }"
    )


def build_graph_probe_ask(domain: str) -> str:
    """ASK whether the named graph (or its instances) holds ANY triple — the honest distinction between
    ``not_found`` (graph absent/empty entirely — likely a bad graph name) and ``empty`` (graph present
    but no rules of this kind — the abstain-everything case the caller decides how to read)."""
    vocab, inst = _scope(domain)
    return f"ASK {{ VALUES ?__g {{ <{vocab}> <{inst}> }} GRAPH ?__g {{ ?s ?p ?o }} }}"
