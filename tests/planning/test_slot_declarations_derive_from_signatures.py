"""Slot declarations must be DERIVED, and the two hand-written parts must not drift.

A registration declares what a verb is ABOUT and what it PRODUCES, and has never declared what it
TAKES — which is why the router cannot know a slot is missing and why a spoken parameter is dropped
in silence. `slots.py` closes that by reading `inspect.signature`.

Almost all of it is derived, so almost none of it can rot. **Two things are written by hand and
this file exists for those two:**

  1. `HANDLE_SLOTS` — which parameters the ROUTE injects. Invisible to a type system:
     `baseline_state: str` and `site_id: str` are the same shape with opposite provenance.
  2. The enum vocabularies that live in BOTH an annotation and a module constant.

Deriving (1) by pattern-matching `run_measure`'s body was considered and refused: an instrument
that reads prose is the species that already cost this repo a near-miss (a comment quoting a bad
value poisoned a regex-derived list, and a nine-class ontology reparent was nearly primed in
response). So the list is explicit and this test fails when it disagrees with the route.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from agent_fleet.planning_agent import measures, slots
from agent_fleet.planning_agent.main import VERBS

_MAIN = Path(__file__).resolve().parents[2] / "agent_fleet" / "planning_agent" / "main.py"


def test_the_inputs_are_readable():
    """Positive control — an empty derivation would pass every assertion below over nothing."""
    assert len(VERBS) >= 12, "the VERBS table did not load"
    declared = {v["fn"]: slots.slots_for(v["fn"]) for v in VERBS}
    assert sum(len(s) for s in declared.values()) >= 20, "derivation produced almost no slots"


def test_every_registered_verb_derives_its_slots():
    for v in VERBS:
        assert hasattr(measures, v["fn"]), f"{v['fn']} is registered but has no measure"
        for s in slots.slots_for(v["fn"]):
            assert s["kind"] in slots.SLOT_KINDS, f"{v['fn']}.{s['name']}: bad kind {s['kind']}"
            assert s["name"] and s["type"], f"{v['fn']}: incomplete slot {s}"


def test_enum_values_are_READ_from_the_annotation_never_restated():
    """The whole point of deriving. If `group_by` ever reports values that are not the annotation's
    `Literal` args, something has started remembering instead of reading."""
    for fn_name, param, expected in [
        ("plan_funding_gap", "group_by", ["org", "initiative"]),
        ("plan_schedule", "group_by", ["initiative", "capability", "target"]),
        ("plan_schedule", "color_by", ["funding_risk", "status", "confidence"]),
    ]:
        slot = next(s for s in slots.slots_for(fn_name) if s["name"] == param)
        assert slot["type"] == "enum", f"{fn_name}.{param} lost its Literal — annotation went bare?"
        assert slot["values"] == expected


def test_the_annotation_and_the_runtime_constant_AGREE():
    """`plan_schedule` validates against `_GROUP_BY`/`_COLOR_BY` at runtime AND declares a Literal.
    Two expressions of one vocabulary: the Literal is what derives, the constant is what refuses.
    They must not drift — a Literal that has quietly lost a value would declare an ask-menu that
    the verb still accepts, or offer one it now rejects."""
    sig = inspect.signature(measures.plan_schedule, eval_str=True)
    import typing
    for param, constant in [("group_by", measures._GROUP_BY), ("color_by", measures._COLOR_BY)]:
        ann = sig.parameters[param].annotation
        args = [a for a in typing.get_args(ann) if a is not type(None)]
        lit = args[0] if args and typing.get_origin(args[0]) is typing.Literal else ann
        assert sorted(typing.get_args(lit)) == sorted(constant), (
            f"plan_schedule.{param}: Literal and the runtime constant disagree — "
            f"{typing.get_args(lit)} vs {constant}"
        )


def test_slot_handles_match_the_routes_injection_sites():
    """THE DRIFT SEAL for the one hand-written list.

    `HANDLE_SLOTS` mirrors the `params[...] = ...` / `params.setdefault(...)` sites in
    `run_measure`. If the route starts injecting a parameter and nobody updates the list, that
    parameter is declared **spoken** — and the router would ask a user for a value the route was
    always going to supply. That is the clippy failure ADR-0033 #4 names: *a system that asks when
    it knows is worse than one that guesses when it doesn't.*
    """
    src = _MAIN.read_text(encoding="utf-8")
    body = src[src.index("def run_measure"):src.index("rows = func")]
    # `if fn == "x":` blocks, and the params keys assigned inside each.
    found: dict[str, set] = {}
    for m in re.finditer(r'if fn == "(\w+)"', body):
        fn = m.group(1)
        seg = body[m.end():]
        nxt = re.search(r'\n    if fn == "', seg)
        seg = seg[:nxt.start()] if nxt else seg
        keys = set(re.findall(r'params(?:\.setdefault\(|\[)"(\w+)"', seg))
        if keys:
            found.setdefault(fn, set()).update(keys)

    assert found, "parsed no injection sites — the route's shape moved, and this seal went quiet"
    assert found == {k: v for k, v in slots.HANDLE_SLOTS.items()}, (
        "HANDLE_SLOTS disagrees with run_measure's injection sites.\n"
        f"  route injects : {found}\n"
        f"  declared      : {dict(slots.HANDLE_SLOTS)}\n"
        "A parameter the route supplies must be declared `handle`, or the router will ask a user "
        "for a value it was always going to fill in."
    )


def test_the_census_numbers_still_hold():
    """The population this work was scoped against, pinned so a signature change is visible.

    12 of 14 verbs take parameters; four are spoken-mandatory (the known-unreachable set); the
    silent-drop population is the spoken-optional one.
    """
    per_verb = {v["fn"]: slots.slots_for(v["fn"]) for v in VERBS}
    takes_params = [f for f, s in per_verb.items() if s]
    spoken_mandatory = [f for f, s in per_verb.items()
                        if any(x["kind"] == "spoken-mandatory" for x in s)]
    assert len(takes_params) == 12, f"expected 12 verbs with parameters, got {len(takes_params)}"
    assert sorted(spoken_mandatory) == sorted([
        "plan_dependency_neighborhood", "plan_capability_path",
        "plan_process_evolution", "plan_tech_footprint",
    ]), f"the spoken-mandatory set moved: {sorted(spoken_mandatory)}"
