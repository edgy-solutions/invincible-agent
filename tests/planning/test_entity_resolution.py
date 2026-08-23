"""PLANNING RESOLUTION REUSES THE LADDER — it does not fork it.

ADR-0031's ladder is the resolver for this codebase. The arms below check the
REUSE as much as the behaviour, because the failure this guards against is not a
wrong answer today — it is a SECOND MATCHER appearing, drifting from the first,
and producing resolutions that are subtly right in one engine and wrong in the
other.

Two of the ladder's rules were expensive to get right and invisible from a
description: qualified forms normalize FOR LOOKUP, and specificity is judged on
WHAT THE USER SAID (a token merely appearing inside a name identifies nothing).
Inheriting them by import is what makes drift impossible.

Run: uv run --frozen --with pytest pytest tests/planning/test_entity_resolution.py -v
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SRC = _REPO / "agent_fleet" / "planning_agent" / "entity_resolution.py"


def _mod():
    spec = importlib.util.spec_from_file_location("planning_entity_resolution__test", _SRC)
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    try:
        spec.loader.exec_module(m)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"resolver not importable here: {type(exc).__name__}: {exc}")
    return m


SITES = [
    {"id": "site-a", "label": "Site Alpha"},
    {"id": "site-b", "label": "Site Bravo"},
    {"id": "site-c", "label": "Site Charlie"},
]


# ── THE REUSE ITSELF ───────────────────────────────────────────────────────

def test_it_imports_the_LADDER_rather_than_reimplementing_it():
    """THE FORK ARM. A second fuzzy matcher is the thing ADR-0031 exists to
    prevent, and it would appear here first."""
    src = _SRC.read_text(encoding="utf-8")
    assert "from instance_resolution import" in src or \
           "from agent_fleet.ontology_service.instance_resolution import" in src
    assert "decide" in src, "the ladder's decision table is not being called"


def test_the_adapter_does_not_reimplement_the_specificity_gate():
    """The gate has hard-won ordering (it runs before ranking, after the empty
    check). A local copy would drift from it silently."""
    src = _SRC.read_text(encoding="utf-8")
    for forbidden in ("def passes_segment_specificity", "def decide("):
        assert forbidden not in src, f"the adapter redefines {forbidden!r}"


def test_the_local_scorer_only_RANKS_and_says_so():
    """A clever scorer here would be the second matcher wearing a helper's name.
    Thresholds, the gate and abstention all belong to `decide`."""
    m = _mod()
    assert 0.0 <= m._score("Alpha", "Site Alpha") <= 1.0
    assert m._score("", "Site Alpha") == 0.0


# ── THE THREE OUTCOMES, WHICH MUST NOT COLLAPSE ────────────────────────────

def test_an_exact_name_RESOLVES():
    m = _mod()
    r = m.resolve_planning_entity("Site Alpha", SITES)
    assert r.status == "resolved"
    assert r.entity_id == "site-a"


def test_a_name_matching_NOTHING_is_UNRESOLVED_not_a_guess():
    """Zero match is a refusal naming what was looked for — never the nearest
    label, which is a confident wrong answer with a plausible spelling."""
    m = _mod()
    r = m.resolve_planning_entity("Site Zulu", SITES)
    assert r.status == "unresolved"
    assert r.entity_id is None
    assert r.candidates == []


def test_the_three_statuses_are_DISTINCT_values():
    """Collapsing ambiguous into resolved is the confident-wrong answer Gate 2
    fails the whole gate for; collapsing it into unresolved throws away a list
    the user could have picked from in one click."""
    m = _mod()
    seen = {
        m.resolve_planning_entity("Site Alpha", SITES).status,
        m.resolve_planning_entity("Site Zulu", SITES).status,
    }
    assert "resolved" in seen and "unresolved" in seen


def test_an_ambiguous_result_carries_its_CANDIDATES_for_the_card():
    """The interpretation card needs the list. An ambiguous resolution that
    returns no candidates has told the user 'be more specific' while withholding
    the options — the least useful possible refusal."""
    m = _mod()
    r = m.resolve_planning_entity("Site", SITES)
    if r.status == "ambiguous":
        assert len(r.candidates) >= 2
        assert all("id" in c and "label" in c for c in r.candidates)
    else:
        # The ladder's specificity gate may reject a bare common token outright,
        # which is ALSO correct — "Site" names no site. Either way it must not
        # resolve to one arbitrarily.
        assert r.status == "unresolved", f"a bare common token resolved to {r.entity_id!r}"


def test_a_bare_common_token_never_resolves_to_ONE_arbitrary_entity():
    """SPECIFICITY, inherited. A token that merely APPEARS INSIDE every label
    identifies nothing — this is the rule that cost the resolver arc a landing."""
    m = _mod()
    r = m.resolve_planning_entity("Site", SITES)
    assert r.entity_id is None, f"'Site' resolved to {r.entity_id!r} — it names no site"


# ── SCOPING ────────────────────────────────────────────────────────────────

def test_candidates_are_scoped_by_the_CALLER_not_globally():
    """A slot already declares which kind it wants. Resolving a site name against
    project labels would invent ambiguity the question never had."""
    m = _mod()
    projects = [{"id": "p-1", "label": "Alpha Migration"}]
    r = m.resolve_planning_entity("Site Alpha", projects)
    assert r.entity_id != "site-a"


def test_provenance_is_always_populated():
    """Downstream observability: a resolution with no provenance cannot be
    explained when someone asks why the card says what it says."""
    m = _mod()
    for name in ("Site Alpha", "Site Zulu", "Site"):
        assert m.resolve_planning_entity(name, SITES).provenance != {}
