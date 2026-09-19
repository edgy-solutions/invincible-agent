"""The site-4 row — engine-lg's output class binds to SOURCE_LEDGER, and the bindings agree.

MEASURED 2026-09-16: ``mesh#StatefulSupportResponse`` carried **zero** ``rendersAs`` bindings
against 3-5 on every fin sibling, so the NP-MERIDIAN brief fell through to the payload-only
Knowledge Document. That archetype is the UNIVERSAL fallback — it accepts any string and
publishes an empty refusal vocabulary — so falling to it is indistinguishable from having no
binding at all, which is why the absence went unnoticed while everything reported healthy.

The row is this lane's because the output class is; the archetype id was ruled.

── WHY THE NAME IS STRUCTURAL, AND WHY THAT NEEDS A SEAL RATHER THAN A COMMENT ─────────────
Everyone called this ``BRIEF``, including the ADR — but that named the WORK ITEM. The structure
is N declared sources, every one accounted for, each row a finding or a named absence with its
disposition, each linking its own evidence. None of that is specific to finance, and the second
consumer is a cost lot review. ``ContributionRanking``'s own contract states the rule:
*"nothing here knows the word."*

The placeholder class name carried through the design conversation was ``mesh:Brief``, which
would have been **the only archetype class in the file whose name did not match its archetype
id** — and a mismatched pair reads, later, as two different archetypes. The convention is
derived below rather than asserted, so the next one is caught the same way.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_ONTOLOGIES = _ROOT / "setup" / "ontologies"
_ROW = _ROOT / "policy" / "graphs" / "fin_program_brief.yaml"


def _caps():
    from agent_fleet.presentation_agent.capabilities import PRESENTATION_CAPABILITIES

    return PRESENTATION_CAPABILITIES


def _expand(iri: str) -> str:
    from agent_fleet.presentation_agent.capabilities import canonical_iri_for_lookup

    return canonical_iri_for_lookup(iri)


def _declared_classes() -> set[str]:
    """Every ``X a owl:Class`` subject across the seeded ontologies, as a compact token."""
    out: set[str] = set()
    for ttl in _ONTOLOGIES.glob("*.ttl"):
        for m in re.finditer(r"^([A-Za-z][\w.-]*:[A-Za-z][\w.-]*)\s+a\s+owl:Class",
                             ttl.read_text(encoding="utf-8"), re.M):
            out.add(m.group(1))
    return out


# -- the row itself -------------------------------------------------------------------------

def test_the_graphs_output_class_IS_BOUND_to_an_archetype():
    """THE SITE-4 CLAIM. Without a binding the brief renders as the universal fallback, which
    looks exactly like a card that has no binding — the absence with no symptom."""
    bound = {c["subject_uri"] for c in _caps()}
    assert "mesh:StatefulSupportResponse" in bound, (
        "engine-lg's output class carries no rendersAs binding, so its brief falls through to "
        "KNOWLEDGE_DOCUMENT — indistinguishable from having no binding at all."
    )


def test_the_bound_class_IS_THE_ONE_THE_RATIFIED_ROW_DECLARES():
    """THE JOIN, read from the ratified row rather than typed here.

    The capability carries a COMPACT IRI and the graph row a FULL one. Both ends were correct
    in this repo before and the relation was asserted nowhere — and the compact-versus-expanded
    spelling is the exact mismatch that got six fin rows refused by Contract D. A prefix that
    stops expanding fails SILENTLY: the row registers, reports accepted, and never matches.
    """
    declared = yaml.safe_load(_ROW.read_text(encoding="utf-8"))["output_uri"]
    cap = next(c for c in _caps() if c["archetype"] == "SOURCE_LEDGER")
    assert _expand(cap["subject_uri"]) == declared, (
        f"the capability binds {_expand(cap['subject_uri'])!r} and the ratified row declares "
        f"{declared!r}. A binding on a class the graph does not emit matches nothing, and says "
        f"nothing while doing it."
    )


def test_the_expected_fields_are_what_the_GRAPH_ACTUALLY_EMITS():
    """A card told to expect a field the producer never sends renders an empty slot and blames
    the payload. `rows` and `summary` are asserted against the graph's own state keys."""
    from agent_fleet.graph_host.graphs import fin_program_brief as b

    cap = next(c for c in _caps() if c["archetype"] == "SOURCE_LEDGER")
    emitted = set(b.BriefState.__annotations__)
    missing = [f for f in cap["expected_fields"] if f not in emitted]
    assert not missing, f"{missing} are expected by the card and not in the graph's state"


def test_holes_is_NOT_an_expected_field():
    """`holes` is a PROJECTION of `rows`. A card reading both would hold one fact in two places,
    and the derived copy is the one that goes on passing after someone edits the source."""
    cap = next(c for c in _caps() if c["archetype"] == "SOURCE_LEDGER")
    assert "holes" not in cap["expected_fields"], (
        "the card is told to read `holes`, which is derivable from `rows` by filtering on the "
        "hole dispositions. Two readings of one fact drift the moment a disposition is added."
    )


# -- the conventions, derived over EVERY row so the next one is caught too -------------------

def test_EVERY_archetype_class_NAME_MATCHES_its_archetype_id():
    """THE SEAL THAT WOULD HAVE CAUGHT `mesh:Brief`.

    Derived across all bindings, not asserted for the new one: every ``object_uri`` local name
    is the CamelCase of its ``archetype``. Held for all 13 before this row was added, which is
    what made it a convention rather than a coincidence worth pinning.
    """
    bad = []
    for cap in _caps():
        local = cap["object_uri"].split(":")[-1].split("#")[-1]
        expected = re.sub(r"(?<!^)(?=[A-Z])", "_", local).upper()
        if expected != cap["archetype"]:
            bad.append((cap["object_uri"], cap["archetype"], expected))
    assert not bad, (
        f"archetype class and id disagree: {bad}. A mismatched pair reads later as TWO "
        f"archetypes, and the one nobody registered is the one that silently never matches."
    )


def test_EVERY_archetype_CLASS_EXISTS_in_the_seeded_ontologies():
    """The object end of a rendersAs triple must be declared so it can exist. A binding to an
    undeclared class is the Contract D refusal arriving at seed time instead of registration
    time — or not arriving at all, which is worse."""
    declared = _declared_classes()
    missing = sorted({c["object_uri"] for c in _caps()} - declared)
    assert not missing, (
        f"{missing} are bound as archetypes and declared in no ontology under "
        f"{_ONTOLOGIES.name}/."
    )


def test_the_new_archetype_NAMES_NO_DOMAIN(monkeypatch):
    """THE RULE ITSELF, applied to the term that was ruled. `brief`, `program` and `finance` are
    the words this archetype exists NOT to contain — it is bound to a finance graph first and a
    cost graph second, and a domain name in the id would make the second binding read wrong."""
    cap = next(c for c in _caps() if c["archetype"] == "SOURCE_LEDGER")
    blob = f"{cap['object_uri']} {cap['archetype']}".lower()
    for word in ("brief", "program", "finance", "fin", "cost"):
        assert word not in blob, (
            f"the archetype names a domain ({word!r}): {blob!r}. It is bound to a finance graph "
            f"first and a cost one second; the structure is neither."
        )
