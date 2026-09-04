"""Every class the PRIME makes groundable must lead to a verb, or say why it does not.

⛔ THIS IS A WIDER FINDABLE SET THAN THE BOOT GUARD USES, AND THAT GAP IS THE FINDING.

`assert_subject_coverage` (agent_fleet/utils/subject_coverage.py) asks whether every class in
the engine's `_RESOLVABLE` set leads to a verb. That is what the ENGINE can resolve.

**The router's findable set is the DOMAIN POOL** — every class the prime seeds under this
engine's semantic domain — and it is strictly larger. A class in the pool and absent from
`_RESOLVABLE` is INVISIBLE TO THE BOOT GUARD AND REACHABLE BY THE ROUTER, which is exactly the
failure the guard was written to prevent.

Measured 2026-09-04, on the engine that has the guard: `fin:EarnedValueTechnique` is seeded,
groundable, served by no verb, and absent from every declaration. It is not theoretical — it
won a `/resolve` draw for "show me SPI over time", recorded in
`[[the-winner-is-a-sample-the-set-is-the-answer]]`. The boot guard returned `[]` throughout.

So the guard is a useful in-engine approximation and NOT sufficient on its own, and anyone
adopting it should know that before they rely on it. This test is the other half, and it lives
at the pool level because that is where the seeded TTLs can be read.

THE SAME QUERY OVER OTHER NAMESPACES, same run, reported and not asserted here — those engines
are other lanes' and their declarations are theirs to write:

    cost#   2 unserved   (CostCategory, Supplier — the defect that prompted the extraction)
    idp#    4 unserved   (Dashboard, Job, Pipeline, Table)

Whether this seal should be widened to fail for them is a decision with an owner, and it is not
this lane's to take: exemptions authored on another lane's behalf, with reasons invented here,
would be the stale-exemption defect created rather than caught.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

rdflib = pytest.importorskip("rdflib", reason="ontology parsing needs rdflib")
from rdflib.namespace import OWL, RDF, RDFS  # noqa: E402

_FIN = "http://invincible-agent/fin#"
_MESH = rdflib.Namespace("http://invincible-agent/mesh#")


def _seeded_graph():
    """Every TTL the prime actually seeds — derived from the manifest, never listed."""
    manifest = (_ROOT / "setup" / "prime_databases.py").read_text(encoding="utf-8")
    rels = re.findall(r'"path":\s*"(ontologies/[^"]+\.ttl)"', manifest)
    assert rels, "prime_databases.py's ONTOLOGIES manifest parsed to nothing — regex is stale"
    g = rdflib.Graph()
    for rel in rels:
        p = _ROOT / "setup" / rel
        if p.exists():
            g.parse(str(p), format="turtle")
    return g


def _groundable_fin_classes() -> set[str]:
    """Seeded `fin:` classes MINUS the two kinds the resolver never offers as a subject.

    Response shapes are filtered from the candidate pool at the write site, and archetypes are
    reached through a rendersAs binding rather than through recall — so neither is a class a
    question can ground to, and counting them would manufacture false gaps.
    """
    g = _seeded_graph()
    shapes = {str(s) for s in g.subjects(RDFS.subClassOf, _MESH.Response)}
    archetypes = {str(s) for s in g.subjects(RDFS.subClassOf, _MESH.Archetype)}
    return {
        str(s) for s in g.subjects(RDF.type, OWL.Class)
        if str(s).startswith(_FIN)
    } - shapes - archetypes


def test_the_population_is_non_empty():
    """Positive control. Every derived assertion in this repo has to rule this out first."""
    assert len(_groundable_fin_classes()) >= 5


def test_every_groundable_fin_class_is_served_or_declared():
    """THE SEAL. A groundable class with no verb and no declaration is a question that grounds
    at high confidence and is answered by the generalist, wearing the caller's persona."""
    from agent_fleet.finance_agent.main import (
        _NO_VERB_BY_DESIGN, _UNSERVED_KNOWN_GAP, _all_subjects,
    )
    undeclared = sorted(
        _groundable_fin_classes() - _all_subjects() - _NO_VERB_BY_DESIGN - _UNSERVED_KNOWN_GAP
    )
    assert not undeclared, (
        f"{len(undeclared)} groundable fin: class(es) that no verb serves and nothing "
        f"declares: {[c.rsplit('#', 1)[-1] for c in undeclared]}.\n"
        "The router can ground a question to these and nothing answers it — the question "
        "falls through to the generalist and comes back as the caller's persona. Register a "
        "verb, add it to _NO_VERB_BY_DESIGN if a question will never target it, or to "
        "_UNSERVED_KNOWN_GAP if one will and there is no answer yet."
    )


def test_the_two_declarations_are_kept_APART():
    """A gap must not be able to hide inside a design statement.

    `_NO_VERB_BY_DESIGN` claims a question will never target the class. `_UNSERVED_KNOWN_GAP`
    admits one will and there is no answer. Merging them would turn a confession into a
    decision, which is the plausible-negative defect: an omission that reads as considered.
    """
    from agent_fleet.finance_agent.main import _NO_VERB_BY_DESIGN, _UNSERVED_KNOWN_GAP
    overlap = _NO_VERB_BY_DESIGN & _UNSERVED_KNOWN_GAP
    assert not overlap, f"a class is declared both by-design and a known gap: {sorted(overlap)}"
    assert _UNSERVED_KNOWN_GAP, (
        "the known-gap set is empty — if the gap was closed, DELETE the constant and this "
        "assertion rather than leaving an empty set that suggests one is tracked"
    )


def test_the_boot_guard_alone_does_NOT_catch_this():
    """⛔ PINNED, because it is the reason this file exists and it is counter-intuitive.

    The engine's boot guard returns `[]` while a groundable class goes unserved. Anyone
    adopting `assert_subject_coverage` and believing it sufficient is relying on a check with a
    narrower findable set than the router's. If this assertion ever fails, the guard has been
    widened to read the pool and this file's premise should be re-examined — not deleted
    silently.
    """
    from agent_fleet.finance_agent.main import _dead_end_classes, _RESOLVABLE, _UNSERVED_KNOWN_GAP
    assert _dead_end_classes() == [], "the boot guard now reports gaps — premise changed"
    invisible = _UNSERVED_KNOWN_GAP - set(_RESOLVABLE)
    assert invisible, (
        "every known gap is now inside _RESOLVABLE, so the boot guard would have caught it "
        "and this file no longer demonstrates the difference it was written to show"
    )
