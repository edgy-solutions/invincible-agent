"""THE INTENT CATALOG IS THE FUNNEL WALL — and its walls are checkable.

The LLM routes and narrates; it never answers. A question lands on a declared
intent or takes the refusal path, and there is no third outcome. That property
is only real if the catalog itself holds three invariants, so they are pinned
here rather than trusted.

WHAT THIS SEALS:

  * NO `view` FIELD, ANYWHERE (D1 / ADR-0042 §2, HARD). An intent declares WHAT
    KIND of answer it produces and never how it draws. `mesh:PeriodCostSeries`
    may render as PERIOD_SERIES today and as something better tomorrow, on a
    frontend that registers it, with no change to this file. A `view:` here
    re-opens a closed packet.

  * EVERY `output_uri` NAMES A DEPLOYED VERB'S DECLARED OUTPUT. Read from
    Engine P's measures, not invented and not copied from the plan's §2.3 table
    — which documents ten of the twelve deployed verbs and omits `plan_diff`
    and `plan_coverage_gap` entirely. An invented output type would mint an
    ontology class in another lane's territory.

  * A BLOCKED INTENT IS EXPLICIT, NOT ABSENT. `what_blocks` and `downstream_of`
    want a dependency TRAVERSAL; the deployed violations verb takes no project
    parameter and reports only breaches. Mapping them to it would answer a
    different question AND return blank when nothing is violated — "nothing
    blocks it" when the truth is "three predecessors, all satisfied". They carry
    a `blocked:` block with a reason and the pending verb, so the gap is legible
    instead of being a silent mis-route.

Run: uv run --frozen --with pytest --with pyyaml pytest tests/planning/test_intent_catalog.py -v
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

_REPO = Path(__file__).resolve().parents[2]
_CATALOG = _REPO / "agent_fleet" / "planning_agent" / "intent_catalog.yaml"
_MEASURES = _REPO / "agent_fleet" / "planning_agent" / "measures.py"


def _catalog() -> dict:
    return yaml.safe_load(_CATALOG.read_text(encoding="utf-8"))


def _intents() -> list[dict]:
    return _catalog()["intents"]


def _deployed_output_uris() -> set[str]:
    """Read the output types Engine P's measures actually declare.

    From the SOURCE, because the plan's table is stale by two verbs — the kind
    of drift that turns into an invented ontology class if the doc is trusted.
    """
    src = _MEASURES.read_text(encoding="utf-8")
    return set(re.findall(r"->\s+(mesh:[A-Za-z]+)", src))


def _deployed_measures() -> set[str]:
    src = _MEASURES.read_text(encoding="utf-8")
    return set(re.findall(r"^def (plan_[a-z_]+)", src, re.MULTILINE))


# ── THE HARD RULE ──────────────────────────────────────────────────────────

def test_NO_intent_carries_a_view_field():
    """D1, and it re-opens a closed packet if violated."""
    offenders = [i["intent_id"] for i in _intents() if "view" in i]
    assert not offenders, f"intents declaring a view: {offenders}"


def test_the_raw_file_has_no_view_key_at_any_depth():
    """Nested slots or soft-language entries could smuggle one past a top-level
    check — the rule is about the FILE, not just the intent objects."""
    raw = _CATALOG.read_text(encoding="utf-8")
    code = [ln for ln in raw.splitlines() if not ln.lstrip().startswith("#")]
    offenders = [ln.strip() for ln in code if re.match(r"^\s*view\s*:", ln)]
    assert not offenders, f"a `view:` key exists in the catalog: {offenders}"


# ── ROUTING INTEGRITY ──────────────────────────────────────────────────────

def test_every_routed_intent_names_a_DEPLOYED_measure():
    """A catalog entry pointing at a verb that does not exist is a route to a
    500 that reads like a routing failure."""
    deployed = _deployed_measures()
    for i in _intents():
        mid = i.get("measure_id")
        if mid is None:
            continue  # mutation or blocked — covered by their own arms
        assert mid in deployed, f"{i['intent_id']} routes to undeployed verb {mid!r}"


def test_every_output_uri_is_one_a_verb_actually_DECLARES():
    """THE INVENTION ARM. Minting an output type here would create an ontology
    class in another lane's territory — the exact move that costs a session."""
    declared = _deployed_output_uris()
    for i in _intents():
        uri = i.get("output_uri")
        if uri is None:
            continue
        assert uri in declared, (
            f"{i['intent_id']} declares {uri!r}, which no deployed verb produces. "
            f"Deployed: {sorted(declared)}"
        )


def test_intent_ids_are_unique():
    ids = [i["intent_id"] for i in _intents()]
    assert len(ids) == len(set(ids)), "duplicate intent_id"


# ── BLOCKED INTENTS ARE EXPLICIT ───────────────────────────────────────────

def test_a_blocked_intent_declares_its_reason_and_its_pending_verb():
    """A gap that is merely absent is indistinguishable from an oversight."""
    blocked = [i for i in _intents() if i.get("blocked")]
    assert blocked, "expected the traversal intents to be present-and-blocked, not deleted"
    for i in blocked:
        b = i["blocked"]
        assert b.get("reason"), f"{i['intent_id']} is blocked with no reason"
        assert b.get("pending_verb"), f"{i['intent_id']} names no verb that would unblock it"


def test_a_blocked_intent_routes_NOWHERE_rather_than_to_a_near_miss():
    """THE MIS-ROUTE ARM. Pointing these at the violations verb would answer a
    different question and go BLANK when nothing is violated — a confident blank
    is worse than a refusal, because nobody knows to go looking."""
    for i in _intents():
        if i.get("blocked"):
            assert i.get("measure_id") is None, (
                f"{i['intent_id']} is blocked yet routes to {i['measure_id']!r} — "
                f"a near-miss route is how a wrong answer gets served confidently"
            )
            assert i.get("output_uri") is None


def test_the_violations_verb_is_NOT_used_for_traversal():
    """Directly pins the mis-route this arc found: plan_dependency_violations
    takes no project parameter and reports only breaches."""
    for i in _intents():
        if i["intent_id"] in {"what_blocks", "downstream_of"}:
            assert i.get("measure_id") != "plan_dependency_violations"


# ── SOFT LANGUAGE AND REFUSAL ──────────────────────────────────────────────

def test_every_soft_phrase_maps_to_a_declared_intent():
    """A synonym pointing at nothing routes a real question into a void."""
    ids = {i["intent_id"] for i in _intents()}
    for phrase, target in _catalog()["soft_language"].items():
        assert target["intent_id"] in ids, f"soft phrase {phrase!r} -> unknown intent"


def test_soft_language_slots_exist_on_their_target_intent():
    """THE DRIFT ARM. A synonym that presets a slot the intent does not have
    fails at fill time, long after the mapping looked right."""
    by_id = {i["intent_id"]: i for i in _intents()}
    for phrase, target in _catalog()["soft_language"].items():
        for slot in (target.get("slots") or {}):
            declared = by_id[target["intent_id"]].get("slots") or {}
            assert slot in declared, (
                f"soft phrase {phrase!r} presets {slot!r}, which "
                f"{target['intent_id']} does not declare"
            )


def test_out_of_model_concepts_carry_a_reason_that_says_WHAT_IS_MISSING():
    """A refusal must state what the model does not capture and be usable as an
    agenda item — "I don't know" is not a refusal, it is a shrug."""
    for c in _catalog()["out_of_model"]:
        assert c.get("phrases"), f"{c['concept']} has no phrasings to match"
        assert len(c.get("reason", "")) > 40, (
            f"{c['concept']}'s reason is too thin to be an agenda item"
        )


def test_the_three_named_out_of_model_concepts_are_present():
    """Gate 2 requires 100% refusal on these; they cannot be optional."""
    concepts = {c["concept"] for c in _catalog()["out_of_model"]}
    assert {"roi", "risk_owner", "headcount"} <= concepts


# ── GENERIC AT BIRTH ───────────────────────────────────────────────────────

def test_the_catalog_carries_no_customer_vocabulary():
    """C4. Structural names only — scrubbing later is a migration, being generic
    now is free. This is a smoke check, not a guarantee: it catches the obvious
    leak, and the review is what catches the subtle one."""
    raw = _CATALOG.read_text(encoding="utf-8").lower()
    for banned in ("boeing", "lockheed", "raytheon", "northrop", "airbus"):
        assert banned not in raw, f"customer vocabulary in the catalog: {banned!r}"
