"""The doc corpus is admissible BEFORE anything ingests it — ADR-0037 §1, slice 1.

WHAT THIS SEALS AND WHY IT IS WORTH A FILE. Five runbook pages carry `docs:` IRIs and `mesh:`
`explains` targets in frontmatter. None of it has been ingested yet, and that is the only reason
these checks can still be cheap: every gate here fails BY PASSING once the corpus is live.

    an undeclared class          ingest registers a DocPage, reports accepted, matches nothing
    an unregistered prefix       the IRI goes onto the wire COMPACT, misses the linker's MATCH
                                 against full-IRI :OntologyClass nodes, registers unreachable
    an audience_hint typo        display routing has NO gate, so it fails silently by design
    a page with no frontmatter   no DocPage row, and a missing row is indistinguishable from
                                 a page nobody wrote

**THE PREFIX ONE HAS SHIPPED THREE TIMES** and `agent_fleet/utils/mesh_registration.py` carries
the post-mortems in its own table: `fin:` (six rendersAs rows silently absent, a finance card
drawn as KNOWLEDGE_DOCUMENT on an answer that routed perfectly), `cost:` (added to the READ side
and not the WRITE side, so every local check passed), and the 2026-08-21 compact-vs-full bug.
`docs:` was entered in both places while the population was still ZERO, which is the only state
in which that is free.

WHAT THIS FILE CANNOT DO, STATED SO A GREEN IS NOT OVER-READ. Every check here is STRUCTURAL — it
reads files. The one that matters most is `explains` resolution, and **a grep of a TTL is not the
instrument for it**: text and graph diverge exactly when a prefix is wrong or a file never primed,
which is the whole failure class above. That arm is a SPARQL/Cypher ASK against the deployed graph
and it SKIPS without one. A skip here is not evidence; it is the absence of evidence, and the
skip reason says so.
"""
from __future__ import annotations

import os
import pathlib
import re

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNBOOKS = ROOT / "docs" / "runbooks"
TTL = ROOT / "setup" / "ontologies" / "mesh_system.ttl"
PERSONAS = ROOT / "policy" / "personas.yaml"

#: Not doc pages, and each for a different reason that matters to the refusal check below.
#: `README.md` is the index — it points AT pages and explains nothing itself. `_TEMPLATE.md` is
#: deliberately unfillable: its `REPLACE-ME` values are refused by the very checks in this file,
#: which is how an unfilled copy gets caught instead of registering a page named REPLACE-ME.
NOT_PAGES = {"README.md", "_TEMPLATE.md"}

REQUIRED_KEYS = ("iri", "explains", "doc_kind", "audience_hint")

#: `explains: none` is ADMITTED AND MARKED. A page that explains nothing yet is an honest row;
#: omitting the key instead would make it indistinguishable from a page nobody wrote.
NO_TARGETS = "none"

CURIE = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):(.+)$")


def _frontmatter(path: pathlib.Path) -> dict | None:
    """The page's frontmatter, or None if it has none at all. None is a RESULT, not an error."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    return yaml.safe_load(text[3:end]) or {}


def _expected_pages() -> list[pathlib.Path]:
    return sorted(p for p in RUNBOOKS.glob("*.md") if p.name not in NOT_PAGES)


def _canonical_personas() -> list[str]:
    """From the policy file, never restated here.

    ADR-0037's own `audience_hint` bullet once listed `reviewer` and `leader`, neither of which is
    a persona in this system. A third copy of an enum is the shape this repo has paid for
    repeatedly, so this reads the file the Topaz sync tool refuses grants against.
    """
    doc = yaml.safe_load(PERSONAS.read_text(encoding="utf-8"))
    return list(doc["personas"])


def _write_side_prefixes() -> dict[str, str]:
    from agent_fleet.utils.mesh_registration import _IRI_PREFIXES
    return dict(_IRI_PREFIXES)


# ── THE DECLARATION, AND ITS ORDERING ─────────────────────────────────────────────────────────

def test_the_doc_vocabulary_is_declared_in_a_ttl_that_actually_primes():
    """Declaration is worth nothing if the file it lives in never reaches the graph.

    ADR-0037 §1 sketched a sibling `mesh_docs.ttl`. A sibling primes only once a manifest row
    exists, and a vocabulary that never primed is the first row of this file's table: accepted
    and matching nothing. So the terms go in the file that already primes, and this asserts BOTH
    halves — the terms are declared, and the file carrying them is in the manifest.
    """
    import rdflib
    g = rdflib.Graph()
    g.parse(TTL, format="turtle")
    mesh = rdflib.Namespace("http://invincible-agent/mesh#")
    for term in ("DocPage", "explains", "audience_hint", "doc_kind"):
        assert (mesh[term], None, None) in g, (
            f"mesh:{term} is not declared in {TTL.name} — ingest would register a DocPage "
            f"against an undeclared term and report success"
        )

    from setup.prime_databases import CANONICAL_TTL_MANIFEST
    entries = [e for e in CANONICAL_TTL_MANIFEST if e.get("name") == "mesh_system"]
    assert entries, (
        "mesh_system is not in CANONICAL_TTL_MANIFEST — the vocabulary above is declared in a "
        "file that does not prime, which is the failure this test exists to make impossible"
    )
    assert entries[0]["domain"] == "MESH", (
        f"mesh_system moved to domain {entries[0]['domain']!r}; the drop set is derived per "
        f"domain, so the vocabulary would be swept with a different domain's graph"
    )


def test_the_docs_prefix_is_registered_on_the_WRITE_side():
    """The side that decides the stored form. The read side folds both forms, which is exactly
    why `cost:` passed every local check while being absent here."""
    prefixes = _write_side_prefixes()
    assert "docs:" in prefixes, (
        "`docs:` is absent from the write-side prefix table. An unknown prefix is passed through "
        "VERBATIM by design, so every page IRI would be stored compact and match nothing"
    )
    assert prefixes["docs:"] == "http://invincible-agent/docs#", (
        f"the docs: namespace disagrees with the TTL's @prefix declaration: {prefixes['docs:']}"
    )

    from agent_fleet.utils.mesh_registration import _expand_mesh_iri
    assert _expand_mesh_iri("docs:runbook-adding-an-engine") == (
        "http://invincible-agent/docs#runbook-adding-an-engine"), "expansion is not applied"

    # THE CONTROL. Pass-through on an unknown prefix is the mechanism every instance of this
    # defect rode in on, so it is asserted rather than assumed — if this ever raises or guesses
    # a namespace instead, the diagnosis in this file's docstring stops being true.
    assert _expand_mesh_iri("nope:thing") == "nope:thing", (
        "an unknown prefix is no longer passed through verbatim — the failure mode described "
        "throughout this file has changed and these comments are now misleading"
    )


# ── THE CORPUS ────────────────────────────────────────────────────────────────────────────────

def test_every_expected_page_carries_the_doc_model():
    """A page with no frontmatter is refused BY NAME. Silence here is the defect: it produces no
    DocPage row, and a missing row reads exactly like a page nobody wrote."""
    pages = _expected_pages()
    assert len(pages) >= 5, (
        f"only {len(pages)} expected doc pages found — the glob has stopped seeing the corpus, "
        f"and an empty population passes every assertion in this file"
    )
    broken = []
    for p in pages:
        fm = _frontmatter(p)
        if fm is None:
            broken.append((p.name, "NO FRONTMATTER AT ALL"))
            continue
        missing = [k for k in REQUIRED_KEYS if k not in fm]
        if missing:
            broken.append((p.name, f"missing {', '.join(missing)}"))
    if broken:
        report = "\n".join(f"  {n}: {why}" for n, why in broken)
        pytest.fail(f"{len(broken)} page(s) would not become a DocPage:\n{report}")


def test_the_refusal_can_see_a_page_that_has_none():
    """THE POSITIVE CONTROL ON THE REFUSAL, and it is the one usually missed.

    The test above passes when every page is fine AND when the detector cannot see absence. Those
    are different states and only this distinguishes them: `README.md` genuinely has no
    frontmatter, so it is a real specimen of the failure, held out of the population rather than
    invented as a fixture.
    """
    readme = RUNBOOKS / "README.md"
    assert readme.is_file(), "the index is missing; this control has no specimen"
    assert _frontmatter(readme) is None, (
        "README.md has gained frontmatter, so this control no longer exercises the absence "
        "branch — point it at another page with none, or the refusal above is unproven"
    )


def test_an_unfilled_template_copy_would_be_refused():
    """`_TEMPLATE.md` is deliberately unfillable, and this asserts that the claim is TRUE rather
    than intended: its placeholder values must be refused by the same checks the corpus passes.
    A template whose defaults happen to validate is how a page named REPLACE-ME registers."""
    fm = _frontmatter(RUNBOOKS / "_TEMPLATE.md")
    assert fm is not None, "the template lost its frontmatter; it is the shape being taught"

    prefixes = _write_side_prefixes()
    targets = fm["explains"]
    targets = [] if targets == NO_TARGETS else list(targets)
    assert targets, "the template no longer carries an explains placeholder"
    for t in targets:
        m = CURIE.match(str(t))
        assert m is None or (m.group(1) + ":") not in prefixes, (
            f"the template's placeholder {t!r} uses a REGISTERED prefix, so an unfilled copy "
            f"would pass the prefix gate and register a page explaining a placeholder"
        )
    assert str(fm["audience_hint"]).upper() not in {p.upper() for p in _canonical_personas()}, (
        "the template's audience_hint placeholder is a real persona — an unfilled copy would "
        "route to a live audience"
    )


def test_every_explains_prefix_is_one_the_wire_can_carry():
    """Structural half of the invented-IRI rule: a target whose PREFIX is unregistered cannot
    resolve no matter what the graph holds, and that is checkable without a graph."""
    prefixes = _write_side_prefixes()
    offenders = []
    for p in _expected_pages():
        fm = _frontmatter(p) or {}
        targets = fm.get("explains")
        if targets == NO_TARGETS or targets is None:
            continue
        for t in targets:
            m = CURIE.match(str(t))
            if m is None:
                offenders.append((p.name, t, "not a CURIE — no prefix to expand"))
            elif (m.group(1) + ":") not in prefixes:
                offenders.append((p.name, t, f"prefix {m.group(1)}: is not registered"))
    if offenders:
        report = "\n".join(f"  {n}: {t} — {why}" for n, t, why in offenders)
        pytest.fail(
            "explains targets that cannot reach the graph whatever it contains:\n" + report)


def test_every_audience_hint_is_a_persona_from_the_policy_file():
    """`policy/personas.yaml` is canonical and UPPERCASE (R-017). The corpus normalises TO the
    policy file, never the reverse — a ratified config outranks prose.

    Matched case-insensitively and linted to canonical case, so `architect` is a lint and
    `data-engineer` is a genuine miss: against `DATA_ENGINEER` it differs by a SEPARATOR, not by
    case, and no case-insensitive comparison will save it.
    """
    canonical = _canonical_personas()
    by_upper = {p.upper(): p for p in canonical}
    wrong, uncanonical = [], []
    for p in _expected_pages():
        fm = _frontmatter(p) or {}
        hint = str(fm.get("audience_hint", ""))
        if hint.upper() not in by_upper:
            wrong.append((p.name, hint))
        elif hint != by_upper[hint.upper()]:
            uncanonical.append((p.name, hint, by_upper[hint.upper()]))
    problems = []
    if wrong:
        problems += [f"  {n}: {h!r} is not a persona in policy/personas.yaml" for n, h in wrong]
    if uncanonical:
        problems += [f"  {n}: {h!r} should be {c!r} (canonical case)" for n, h, c in uncanonical]
    if problems:
        pytest.fail(
            "audience_hint values that display routing cannot use — and it has no gate to "
            "refuse them, so this is the only place they fail:\n" + "\n".join(problems))


def test_the_persona_check_can_say_no():
    """The control on the check above: a fabricated persona must be rejected and a real one
    accepted, so a green means the comparison discriminates rather than that it matched."""
    by_upper = {p.upper() for p in _canonical_personas()}
    assert "ARCHITECT" in by_upper, "ARCHITECT is gone from the policy file — read it again"
    assert "REVIEWER" not in by_upper, (
        "`reviewer` is now a persona, which is what ADR-0037's superseded bullet claimed. If the "
        "policy file really gained it, that correction needs revisiting rather than this test"
    )
    assert "DATA-ENGINEER" not in by_upper, (
        "a hyphenated spelling is now canonical; the separator argument in this file is stale"
    )


# ── THE ARM THAT NEEDS A GRAPH ────────────────────────────────────────────────────────────────

NEO4J_URI = os.environ.get("NEO4J_URI")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD")

needs_graph = pytest.mark.skipif(
    not (NEO4J_URI and NEO4J_PASSWORD),
    reason="set NEO4J_URI + NEO4J_PASSWORD — an explains target RESOLVING is a fact about the "
           "DEPLOYED GRAPH, and no amount of file reading substitutes. THIS SKIP IS NOT A PASS.")


@needs_graph
def test_every_explains_target_resolves_in_the_deployed_graph():
    """The invented-IRI rule, asked of the graph rather than of the text.

    OWED EXTRACTION, RECORDED RATHER THAN DONE: `tests/_mesh_verbs.py` already holds this repo's
    graph-existence probes and this is a second consumer, so the rule says lift it. It is NOT
    lifted yet because this arm has never run — the sandbox release is wedged at pending-upgrade
    and priming is blocked. Extracting an unrun probe into the file three other suites import
    would spread something unverified. Lift it the first time this goes green.

    TWO KINDS, TWO QUERIES, and conflating them is the trap: a CLASS is an `:OntologyClass` node
    holding a full IRI; a VERB is a RELATIONSHIP TYPE between such nodes. A first draft of the
    template-verb seal queried `(:Predicate)` nodes and returned a confident uniform NOT FOUND
    for five real verbs — an instrument failure wearing a finding's clothes.
    """
    from neo4j import GraphDatabase

    from agent_fleet.utils.mesh_registration import _expand_mesh_iri

    targets: list[tuple[str, str]] = []
    for p in _expected_pages():
        fm = _frontmatter(p) or {}
        declared = fm.get("explains")
        if declared == NO_TARGETS or declared is None:
            continue
        for t in declared:
            targets.append((p.name, str(t)))
    assert targets, "no explains targets collected — nothing is being checked"

    driver = GraphDatabase.driver(
        NEO4J_URI, auth=(os.environ.get("NEO4J_USER", "neo4j"), NEO4J_PASSWORD))
    try:
        with driver.session() as s:
            classes = {r["uri"] for r in s.run(
                "MATCH (c:OntologyClass) WHERE c.uri IS NOT NULL RETURN c.uri AS uri")}
            rel_types = {r["relationshipType"] for r in s.run("CALL db.relationshipTypes()")}
    finally:
        driver.close()

    # CONTROLS FIRST, because every assertion below passes vacuously against an empty read.
    assert classes, "zero OntologyClass nodes — instrument failure, not an empty graph"
    assert rel_types, "zero relationship types — instrument failure, not an empty graph"
    fabricated = "DefinitelyNotARegisteredTerm"
    assert fabricated not in rel_types and (
        "http://invincible-agent/mesh#" + fabricated) not in classes, (
        "the graph reports a fabricated term as present — the queries are not discriminating")

    dangling = []
    for page, curie in targets:
        local = curie.split(":", 1)[1] if ":" in curie else curie
        if _expand_mesh_iri(curie) in classes or local in rel_types:
            continue
        dangling.append((page, curie))
    if dangling:
        report = "\n".join(f"  {p}: {c}" for p, c in dangling)
        pytest.fail(
            f"{len(dangling)} explains target(s) do not resolve in the deployed graph. The "
            f"frontmatter is well-formed, which is why only an ASK finds this:\n{report}")
