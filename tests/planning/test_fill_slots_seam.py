"""The last join: /fill_slots, and the supervisor's call to it.

WHAT IS TESTED WITHOUT A MODEL, AND WHY THAT IS MOST OF IT. The model's job is one step —
turning a phrase into `{"group_by": "initiative"}`. Everything around it is deterministic,
and it is where the defects have actually been: which slots are OFFERED to the model
(route-supplied ones must never be), what happens to a name it invents, what happens when it
returns junk, and whether a failure degrades to the old behaviour or breaks routing.

The model's own behaviour is pre-registered in the acceptance table (`test_slot_carry.py`)
and measured live against the cluster — not simulated here. A stub that returns what I expect
would only prove I can write a stub.
"""
from __future__ import annotations

import asyncio
import ast
import json
import pathlib

import pytest

from agent_fleet.planning_agent.slots import slots_for

SUPERVISOR = (pathlib.Path(__file__).resolve().parents[2]
              / "src/iagent/defs/dynamic_supervisor.py")


def _eo():
    """Engine O's module, or skip — it imports rdflib at module scope."""
    pytest.importorskip("rdflib")
    from agent_fleet.ontology_service import main as eo
    return eo


# ── what the model is OFFERED ────────────────────────────────────────────────

def test_route_supplied_slots_are_NEVER_shown_to_the_model():
    """THE BOUNDARY, moved one layer earlier. The guard refuses a spoken `baseline_state`
    anyway; not offering it means it cannot be offered back. Defence in depth rather than a
    substitute for the guard — a declaration can be wrong, and `_type_of` already was."""
    eo = _eo()
    spec, by_name = eo._slot_spec(slots_for("plan_cost_curve"))
    assert "baseline_state" not in spec, "a route-supplied slot was described to the model"
    assert "baseline_state" not in by_name
    assert "window" in spec and "scope_initiative_id" in spec, "the spoken slots vanished too"


def test_a_verb_whose_every_slot_is_route_supplied_offers_nothing():
    """`plan_diff` declares only `baseline_state`. Nothing a speaker could fill, so the
    endpoint must not spend a model call to be told so."""
    eo = _eo()
    spec, by_name = eo._slot_spec(slots_for("plan_diff"))
    assert by_name == {}
    assert "no parameters" in spec


def test_the_spec_carries_the_verbs_OWN_vocabulary():
    """The enum values are read out of the signature's `Literal`, so the model chooses from
    what the code accepts rather than from what it can imagine."""
    eo = _eo()
    spec, _ = eo._slot_spec(slots_for("plan_funding_gap"))
    assert "group_by" in spec
    assert "org" in spec and "initiative" in spec, "the closed vocabulary was not offered"
    assert "defaults to" in spec, "the default was not disclosed, so silence looks like a gap"


# ── what happens to what comes BACK ──────────────────────────────────────────

def _ask(eo, monkeypatch, slots_json, confidence=0.9):
    """Drive the endpoint with a fixed model reply. The stub stands in for BAML ONLY —
    every layer under test after it is the real one."""
    class _Filled:
        def __init__(self):
            self.slots_json = slots_json
            self.confidence = confidence
            self.reasoning = "stub"

    async def _fake(**kw):
        return _Filled()

    monkeypatch.setattr(eo.b, "FillVerbSlots", _fake)
    req = eo.FillSlotsRequest(query="q", verb_iri="mesh:planFundingGap",
                              declarations=json.dumps(slots_for("plan_funding_gap")))
    return asyncio.run(eo.fill_slots(req))


def test_a_declared_slot_is_accepted(monkeypatch):
    eo = _eo()
    r = _ask(eo, monkeypatch, '{"group_by": "initiative"}')
    assert r.slots == {"group_by": "initiative"} and not r.refused


def test_an_invented_name_is_refused_and_SAID(monkeypatch):
    """Not merely dropped. This layer is the only one that can name which parameter the
    model invented, and saying so is the point — the finding this closes was a parameter
    vanishing without a word anywhere."""
    eo = _eo()
    r = _ask(eo, monkeypatch, '{"group_by": "org", "sort_order": "desc"}')
    assert r.slots == {"group_by": "org"}
    assert any("sort_order" in x for x in r.refused)


def test_a_value_outside_the_declared_enum_is_refused(monkeypatch):
    eo = _eo()
    r = _ask(eo, monkeypatch, '{"group_by": "by_vibes"}')
    assert r.slots == {} and any("by_vibes" in x for x in r.refused)


def test_a_bare_string_for_a_list_slot_is_refused_not_coerced(monkeypatch):
    """Wrapping as [value] is the router guessing, and the guess is wrong the moment a
    speaker names two periods. `window` is `list[str]` — the slot whose mis-declaration
    produced `422 unknown fiscal period(s): F, Y, 2, 6, -, Q, 4`."""
    eo = _eo()
    r = _ask(eo, monkeypatch, '{"window": "FY26-Q4"}')
    assert r.slots == {} and any("window" in x for x in r.refused)


def test_a_correctly_shaped_list_IS_accepted(monkeypatch):
    """Non-vacuity for the refusal above — the shape check must not be a blanket refusal."""
    eo = _eo()
    r = _ask(eo, monkeypatch, '{"window": ["FY26-Q4"]}')
    assert r.slots == {"window": ["FY26-Q4"]} and not r.refused


# ── failure must degrade to the OLD behaviour, never break routing ───────────

@pytest.mark.parametrize("bad", ["not json at all", '"a string"', "[1,2]", "", None])
def test_a_malformed_model_reply_yields_NO_SLOTS_rather_than_an_error(monkeypatch, bad):
    """Honest-empty. `{}` is exactly the pre-slot behaviour: the verb runs on its defaults.
    This endpoint must not be able to make routing worse than before it existed."""
    eo = _eo()
    assert _ask(eo, monkeypatch, bad).slots == {}


def test_a_model_EXCEPTION_yields_no_slots_rather_than_a_500(monkeypatch):
    eo = _eo()

    async def _boom(**kw):
        raise RuntimeError("provider down")

    monkeypatch.setattr(eo.b, "FillVerbSlots", _boom)
    r = asyncio.run(eo.fill_slots(eo.FillSlotsRequest(
        query="q", verb_iri="mesh:planFundingGap",
        declarations=json.dumps(slots_for("plan_funding_gap")))))
    assert r.slots == {} and "unavailable" in r.reasoning


def test_declarations_as_a_JSON_STRING_are_decoded():
    """The graph hands these over as a string — `list()` on it yields one entry per
    CHARACTER. Asserted through the outcome: the real slot names come back."""
    eo = _eo()
    decoded = eo._decode_declarations(json.dumps(slots_for("plan_funding_gap")))
    assert [d["name"] for d in decoded] == ["group_by", "window"]
    assert eo._decode_declarations("[not json") == []
    assert eo._decode_declarations(None) == []


# ── the supervisor's side ────────────────────────────────────────────────────

def test_the_supervisor_degrades_to_defaults_on_every_failure_path():
    """The call is optional by construction: a slot REFINES a question that will still be
    answered without it. Unreachable, non-200 and a malformed body must all mean "run on
    defaults", which is what the system did before this join existed.

    Read from source: exercising these branches needs a live Engine O, and the property
    being pinned is structural — that no failure path raises."""
    tree = ast.parse(SUPERVISOR.read_text(encoding="utf-8"))
    fn = next(f for f in ast.walk(tree)
              if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
              and f.name == "_fill_slots_from_query")

    # UPDATED 2026-08-29 WHEN THE RETURN TYPE WIDENED, and deliberately not weakened. The
    # helper used to `return {}`; it now returns `_FillResult(slots, resolution)` so the
    # disposition can see WHY a referent slot is missing rather than only THAT it is. The
    # property being sealed is unchanged — every failure path degrades to "run on defaults"
    # — so the instrument follows the type instead of the literal.
    #
    # An empty `_FillResult({}, {})` is the honest-empty of the new shape: no slots, and no
    # claim about resolution either. A failure that returned `_FillResult({}, something)`
    # would be asserting knowledge it does not have, so BOTH args must be empty.
    def _is_honest_empty(node):
        if not isinstance(node, ast.Return):
            return False
        v = node.value
        if isinstance(v, ast.Dict) and not v.keys:
            return True          # the pre-widening form, still accepted
        return (
            isinstance(v, ast.Call)
            and getattr(v.func, "id", "") == "_FillResult"
            and len(v.args) == 2
            and all(isinstance(a, ast.Dict) and not a.keys for a in v.args)
        )

    empties = [r for r in ast.walk(fn) if _is_honest_empty(r)]
    assert len(empties) >= 3, (
        "fewer than three honest-empty return paths — a failure mode raises instead of "
        "degrading, and a slot extractor must never be able to break routing"
    )
    assert any(isinstance(n, ast.Try) for n in ast.walk(fn)), "the network call is unguarded"
    assert not [n for n in ast.walk(fn) if isinstance(n, ast.Raise)], (
        "the helper raises — routing would fail because a refinement was unavailable"
    )


def test_an_explicitly_supplied_slot_is_not_overridden_by_the_model():
    """`config.slots` wins. Extraction fills the gap; it does not take the wheel — a caller
    that named a parameter has already answered the question the model would be asked."""
    src = SUPERVISOR.read_text(encoding="utf-8")
    assert "if not spoken and declared:" in src, (
        "the filler is no longer gated on the caller having supplied nothing"
    )


def test_the_filler_runs_BEFORE_the_acceptance_guard():
    """Order matters and is easy to invert. The guard must see what the model produced, or
    a fabricated `baseline_state` would reach `req.params` unchecked."""
    src = SUPERVISOR.read_text(encoding="utf-8")
    fill = src.index("_fill_slots_from_query(\n")
    guard = src.index("accepted = accept_slots(")
    assert fill < guard, "the acceptance guard runs before the filler — it would check nothing"
