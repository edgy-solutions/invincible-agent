"""Shared mesh-verb existence probes — the queries AND the controls that make them readable.

EXTRACTED AT THE SECOND CONSUMER, ON PURPOSE. `tests/planning/test_template_verbs_are_registered.py`
was the first; a ratified-graph-rows check is the second. This repo has already paid for
extracting at the third — `slot_declarations` forked `_type_of` because nobody lifted it at two —
and the cheapest moment to stop that is now.

── WHAT IS SHARED AND WHAT IS NOT ─────────────────────────────────────────────────────────────
Shared: HOW to ask the mesh whether a verb exists, and how to tell a broken instrument from a
real absence. Not shared: WHICH verbs a consumer cares about, and what it asserts about them.
Each consumer keeps its own population function and its own assertions, so a red still names the
consumer's data rather than dissolving into a helper.

── THE CONTROLS MOVE WITH THE QUERIES, AND THAT IS THE WHOLE DESIGN ───────────────────────────
The objection to sharing is that a shared helper makes failures harder to attribute: it breaks,
two files go red, neither owns it. That objection is real for a helper extracted WITHOUT its
controls, and it INVERTS once they come along:

    controls red  -> the INSTRUMENT is broken. The helper owns it.
    controls green, population assertions red -> the DATA is bad. The consumer owns it.

That discrimination is the attribution mechanism, and it only works if the controls exercise the
same code path the assertions do. Copied controls are worse on both counts: a copy can drift
until it stops discriminating and still passes — **drift in a control is invisible by
construction** — and then neither file can tell instrument from data.

`assert_checkers_can_say_no()` is deliberately a CALLABLE rather than a collected test. Each
consumer invokes it from its own one-line test, so there is ONE implementation (no drift) that
runs in EACH consumer's environment (skip conditions and reachability differ per context, and a
control that ran somewhere else proves nothing about here).

── THE KNOWLEDGE THIS FILE EXISTS TO STOP RE-DERIVING ─────────────────────────────────────────
**Verbs are RELATIONSHIP TYPES between `OntologyClass` nodes, not nodes.** Read off
`/find_compatible_verbs`' own walk (`MATCH (s:OntologyClass {uri})-[r]->(o)`), not guessed. The
first draft of the first consumer queried `(:Predicate)` nodes and returned a confident, uniform
`NOT FOUND` for all five verbs it was checking — an instrument failure wearing a finding's
clothes, one commit from being filed as "the template names five unregistered verbs". A second
consumer's first draft would get it wrong the same way. It cannot now.

**Eligibility is a CONJUNCTIVE read.** `principles/select-from-authorized-set.md`: a verb is
eligible only if it appears in BOTH Neo4j and Weaviate. A verb present in Neo4j alone is exactly
the row that registers, reports accepted, and never matches — so `one_sided()` reports that as
its own category rather than folding it into "missing", because it is the harder fact to
diagnose from a symptom.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request

import pytest

NEO4J_URI = os.environ.get("NEO4J_URI")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD")
WEAVIATE_URL = os.environ.get("WEAVIATE_URL")

# SKIPPING MUST NOT READ AS PASSING. Without a reachable mesh these checks skip, and a skip is
# not evidence the verbs exist. Consumers should say so where they record results.
needs_neo4j = pytest.mark.skipif(
    not (NEO4J_URI and NEO4J_PASSWORD),
    reason="set NEO4J_URI + NEO4J_PASSWORD to check verb existence against the mesh")
needs_weaviate = pytest.mark.skipif(
    not WEAVIATE_URL, reason="set WEAVIATE_URL to check the Weaviate half of eligibility")

# A verb that cannot exist, used by the controls. Deliberately shaped like a real verb so it
# tests DISCRIMINATION rather than input validation.
FABRICATED_VERB = "planDefinitelyNotARegisteredVerb"


def neo4j_relationship_types() -> set[str]:
    """Every relationship type in the graph — verbs live here, not as nodes."""
    from neo4j import GraphDatabase
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        with driver.session() as s:
            return {r["relationshipType"] for r in s.run("CALL db.relationshipTypes()")}
    finally:
        driver.close()


def weaviate_predicates() -> dict[str, dict]:
    """`verb_local` -> the Predicate row. Raises on a no-data response rather than returning {}.

    An empty dict would flow into "the verb is absent"; a Weaviate error that returned no `data`
    key is an INSTRUMENT FAILURE and must not be reported as a finding about the registry.
    """
    q = {"query": "{Get{Predicate(limit:1000){verb_iri verb_local endpoint_url "
                  "registration_complete}}}"}
    req = urllib.request.Request(f"{WEAVIATE_URL.rstrip('/')}/v1/graphql",
                                 data=json.dumps(q).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = json.load(r)
    if "data" not in body:
        raise AssertionError(f"Weaviate returned no data — instrument failure, not a finding: "
                             f"{json.dumps(body)[:400]}")
    return {(p.get("verb_local") or ""): p for p in body["data"]["Get"]["Predicate"]}


def assert_checkers_can_say_no(*, neo4j: bool = True, weaviate: bool = True) -> None:
    """THE CONTROLS. A checker that has only ever seen its expected answer has not been shown
    able to give another.

    Called from each consumer's own test so the control runs in that consumer's environment.
    Pass `neo4j=False` / `weaviate=False` when a consumer only uses one store.
    """
    if neo4j:
        types = neo4j_relationship_types()
        assert types, "zero relationship types — instrument failure, not an empty mesh"
        assert FABRICATED_VERB not in types, (
            "the mesh reports a fabricated verb as present — the query is not discriminating")
    if weaviate:
        preds = weaviate_predicates()
        assert preds, "zero Predicate rows — instrument failure, not an empty registry"
        assert FABRICATED_VERB not in preds, (
            "Weaviate reports a fabricated verb as present — the query is not discriminating")


def missing_from_neo4j(population: list[tuple[str, str, str]]) -> list[tuple[str, str]]:
    """`(owner, verb_iri)` for each population entry whose verb the graph does not serve.

    `population` is `(owner, verb_iri, verb_local)` — `owner` is whatever the consumer wants to
    name in a failure (a template id, a graph id), and it is the consumer's word, not this
    file's.
    """
    types = neo4j_relationship_types()
    assert types, "zero relationship types — instrument failure"
    return [(owner, iri) for owner, iri, local in population if local not in types]


def not_eligible_in_weaviate(population: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    """`(owner, verb_iri, why)` for each entry Weaviate would not let the selector reach."""
    preds = weaviate_predicates()
    problems = []
    for owner, iri, local in population:
        p = preds.get(local)
        if p is None:
            problems.append((owner, iri, "absent from Weaviate"))
        elif not p.get("registration_complete"):
            problems.append((owner, iri, "registration_complete is falsy"))
        elif not p.get("endpoint_url"):
            problems.append((owner, iri, "no endpoint_url — nothing would serve it"))
    return problems


def one_sided(population: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    """Entries present in ONE store and not the other — the registers-but-never-matches shape.

    Reported separately from "missing" on purpose: "in Neo4j but not Weaviate" is a different
    fact, and collapsing them hides the one that is hardest to diagnose from a symptom.
    """
    types, preds = neo4j_relationship_types(), weaviate_predicates()
    return [(owner, iri, f"neo4j={local in types} weaviate={local in preds}")
            for owner, iri, local in population
            if (local in types) != (local in preds)]


def _predicate_rows_by_verb() -> dict[str, list[dict]]:
    """Every Predicate row per `verb_local`, not just one.

    `weaviate_predicates()` keys by verb and keeps ONE row, which is right for "is this verb
    registered at all" and wrong for reachability: a verb is commonly registered against SEVERAL
    subjects (`finFundingStatus` takes both `Program` and `FundingLine`), and collapsing them
    would test one subject and report on the verb.
    """
    q = {"query": "{Get{Predicate(limit:1000){verb_local input_uri}}}"}
    req = urllib.request.Request(f"{WEAVIATE_URL.rstrip('/')}/v1/graphql",
                                 data=json.dumps(q).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = json.load(r)
    if "data" not in body:
        raise AssertionError(f"Weaviate returned no data — instrument failure, not a finding: "
                             f"{json.dumps(body)[:400]}")
    out: dict[str, list[dict]] = {}
    for p in body["data"]["Get"]["Predicate"]:
        out.setdefault(p.get("verb_local") or "", []).append(p)
    return out


def unreachable_from_subject(population: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    """`(owner, verb_iri, why)` for verbs that EXIST but no subject can walk to.

    WHY THIS IS SEPARATE FROM `missing_from_neo4j`, and why that one is not enough. Seal 1's
    property is *"a template referencing a verb no engine serves"* — and a verb whose
    relationship type exists somewhere in the graph, but hangs off nothing its registered subject
    can reach, produces the SAME empty panel as a verb that was never registered.

    `missing_from_neo4j` asks `CALL db.relationshipTypes()`, which is a GLOBAL existence question.
    On 2026-09-10 it passed for all eleven template verbs while `/resolve` excluded every one of
    their subjects with `reason: "no_verb_in_scope"`. The edges turned out to be intact, so the
    pass was correct — **by luck rather than by measurement**, which is the whole catalogue's
    subject. This closes that.

    The walk mirrors `/find_compatible_verbs` exactly (`subClassOf*0..5` then the typed edge), so
    this asks the question the router actually asks rather than a similar-looking one.
    """
    from neo4j import GraphDatabase

    rows = _predicate_rows_by_verb()
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    problems: list[tuple[str, str, str]] = []
    try:
        with driver.session() as s:
            for owner, iri, local in population:
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", local):
                    problems.append((owner, iri, f"verb name {local!r} is not a safe edge type"))
                    continue
                subjects = sorted({(p.get("input_uri") or "") for p in rows.get(local, [])} - {""})
                if not subjects:
                    problems.append((owner, iri, "no input_uri registered — no subject to walk from"))
                    continue
                reached = False
                for subj in subjects:
                    rec = s.run(
                        f"MATCH (c:OntologyClass {{uri: $u}})-[:subClassOf*0..5]->"
                        f"(a:OntologyClass)-[r:`{local}`]->(:OntologyClass) RETURN count(r) AS n",
                        u=subj).single()
                    if rec and rec["n"]:
                        reached = True
                        break
                if not reached:
                    problems.append((owner, iri,
                                     f"exists as a relationship type but unreachable from any "
                                     f"registered subject: {[x.split('#')[-1] for x in subjects]}"))
    finally:
        driver.close()
    return problems
