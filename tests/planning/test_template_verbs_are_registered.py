"""SEAL 1's OTHER HALF — a template's verbs must be REGISTERED, read from the mesh, not the file.

ADR-0050 acceptance 1 is *"a template referencing an undeclared verb FAILS AT MERGE"*. What the
CI job delivers is the **shape** gate: `verb: "not a verb iri"` is refused by the schema. That is
not the whole seal, and the gap is the expensive half — a template naming a well-formed verb that
**no engine serves** passes a file-only check, merges, and produces an empty panel at seed time.
That is this system's recurring shape: the row registers, reports accepted, and never matches.

WHY THIS CANNOT BE THE CI JOB. Verb existence is a fact about the running mesh, and the merge-time
job is hermetic by design (seconds, no cluster, no network — which is what earns it its
`pull_request` trigger). So seal 1 is honestly TWO checks in two places, and saying so is better
than pretending one covers both:

    shape      — schema, at merge, hermetic          .github/workflows/validate-canvas-templates.yml
    existence  — the mesh, where the mesh is reachable   THIS FILE

ELIGIBILITY IS A CONJUNCTIVE READ, AND CHECKING ONE SIDE IS THE DEFECT ITSELF. `principles/
select-from-authorized-set.md` states the mechanical form: *a verb is eligible only if it appears
in BOTH Neo4j and Weaviate.* A verb present in Neo4j alone is exactly the "registers, reports
accepted, never matches" failure — so this file asserts BOTH, and a one-sided pass is a failure
here rather than a green.

── THE NEGATIVE CONTROL IS NOT OPTIONAL ────────────────────────────────────────────────────────
A check that has only ever seen its expected answer has not been shown able to give another.
`test_the_checker_can_say_no` runs a verb that cannot exist through the SAME code path and
requires it to come back absent. Without it, a query with a wrong label — which is precisely how
this file's first draft failed, returning a confident uniform NOT FOUND for all five verbs
because it matched `:Predicate` nodes in a graph whose verbs are RELATIONSHIP TYPES — reads as a
finding instead of a broken instrument.

── SKIPPING MUST NOT READ AS PASSING ───────────────────────────────────────────────────────────
Without a reachable mesh these tests SKIP. A skip is not a pass, and the CI job does not run
them, so nothing here should be cited as evidence the verbs exist unless it actually ran. The
recorded run is in `docs/plans/canvas-templates-slice-1.md`.
"""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_CANVAS_DIR = _ROOT / "policy" / "canvases"

# Sandbox coordinates come from the environment. Defaults are deliberately absent: a test that
# silently points at a default substrate is a test whose subject you cannot name in its output.
NEO4J_URI = os.environ.get("NEO4J_URI")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD")
WEAVIATE_URL = os.environ.get("WEAVIATE_URL")

_needs_neo4j = pytest.mark.skipif(
    not (NEO4J_URI and NEO4J_PASSWORD),
    reason="set NEO4J_URI + NEO4J_PASSWORD to check verb existence against the mesh")
_needs_weaviate = pytest.mark.skipif(
    not WEAVIATE_URL, reason="set WEAVIATE_URL to check the Weaviate half of eligibility")


def template_verbs() -> list[tuple[str, str, str]]:
    """`(template_id, verb_iri, verb_local)` for every ratified template."""
    yaml = pytest.importorskip("yaml")
    out = []
    files = sorted(_CANVAS_DIR.glob("*.yaml"))
    assert files, "no ratified templates found — the glob or the directory moved"
    for path in files:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for panel in doc["panels"]:
            iri = panel["verb"]
            out.append((doc["template_id"], iri, iri.split(":", 1)[1]))
    return out


def _neo4j_relationship_types() -> set[str]:
    """Verbs are RELATIONSHIP TYPES between OntologyClass nodes, not nodes.

    Read off `/find_compatible_verbs`'s own walk (`MATCH (s:OntologyClass {uri})-[r]->(o)`),
    because guessing this schema is what produced the first draft's false negative.
    """
    from neo4j import GraphDatabase
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        with driver.session() as s:
            return {r["relationshipType"] for r in s.run("CALL db.relationshipTypes()")}
    finally:
        driver.close()


def _weaviate_predicates() -> dict[str, dict]:
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


# ── THE NEGATIVE CONTROLS ───────────────────────────────────────────────────────────────────
@_needs_neo4j
def test_the_neo4j_checker_can_say_no():
    """The same code path must report a verb that cannot exist as ABSENT."""
    types = _neo4j_relationship_types()
    assert types, "zero relationship types — instrument failure, not an empty mesh"
    assert "planDefinitelyNotARegisteredVerb" not in types, (
        "the mesh reports a fabricated verb as present — the query is not discriminating")


@_needs_weaviate
def test_the_weaviate_checker_can_say_no():
    preds = _weaviate_predicates()
    assert preds, "zero Predicate rows — instrument failure, not an empty registry"
    assert "planDefinitelyNotARegisteredVerb" not in preds, (
        "Weaviate reports a fabricated verb as present — the query is not discriminating")


# ── THE SEAL ────────────────────────────────────────────────────────────────────────────────
@_needs_neo4j
def test_every_template_verb_exists_in_neo4j():
    types = _neo4j_relationship_types()
    assert types, "zero relationship types — instrument failure"
    missing = [(t, iri) for t, iri, local in template_verbs() if local not in types]
    assert not missing, (
        "a ratified template names a verb the mesh does not serve. It would merge, seed, and "
        f"render an EMPTY panel: {missing}")


@_needs_weaviate
def test_every_template_verb_is_registration_complete_in_weaviate():
    preds = _weaviate_predicates()
    problems = []
    for t, iri, local in template_verbs():
        p = preds.get(local)
        if p is None:
            problems.append((t, iri, "absent from Weaviate"))
        elif not p.get("registration_complete"):
            problems.append((t, iri, "registration_complete is falsy"))
        elif not p.get("endpoint_url"):
            problems.append((t, iri, "no endpoint_url — nothing would serve it"))
    assert not problems, f"template verbs are not eligible on the Weaviate side: {problems}"


@_needs_neo4j
@_needs_weaviate
def test_eligibility_is_conjunctive():
    """BOTH stores, per select-from-authorized-set. A one-sided presence is the defect.

    Reported as its own failure rather than folded into the two above, because "in Neo4j but not
    Weaviate" is a DIFFERENT fact from "missing" — it is the registered-but-never-matches shape,
    and collapsing them would hide the one that is hardest to diagnose from a symptom.
    """
    types, preds = _neo4j_relationship_types(), _weaviate_predicates()
    one_sided = [
        (t, iri, f"neo4j={local in types} weaviate={local in preds}")
        for t, iri, local in template_verbs()
        if (local in types) != (local in preds)
    ]
    assert not one_sided, (
        "a template verb is present in one store and not the other — it will register, report "
        f"accepted, and never match: {one_sided}")
