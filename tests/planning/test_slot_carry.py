"""THE ACCEPTANCE TABLE, EXECUTED — does the answer match the question that was asked?

`docs/plans/slots-are-extracted-then-dropped-at-dispatch.md` pre-registered four certified
phrasings, three of which delivered the wrong scope and the fourth of which passed by
coincidence of default. This file is that table inverted into assertions.

WHY IT RUNS WITHOUT A MODEL. Every join in the slot pipeline except the last is
deterministic: declare (signatures), project (a graph edge), carry (a dict), honour (a
splat). Only the fill is a model. Driving the deterministic joins from FIXTURES — a
hand-written `{"group_by": "initiative"}` standing in for what an extraction would produce —
means a red test names the join that broke instead of naming the weather, and it means the
whole chain is provable tonight with the last join still unbuilt.

THE METHOD THE FINDING DEMANDED. Certification checked that an answer came back; the claim
being certified was that the answer matched the question. Every row here therefore compares
DELIVERED against SPOKEN, and every row carries a control that fails if the parameter were
silently dropped. Row 4 is the reason: `plan_schedule.group_by` defaults to `initiative`, so
the certified phrasing "broken out by initiative" passes whether or not anything arrived, and
only a value that DISAGREES with the default can tell the two apart.
"""
from __future__ import annotations

import ast
import pathlib

import pytest
from fastapi.testclient import TestClient

from agent_fleet.planning_agent import main as engine
from agent_fleet.planning_agent.seed import build_seed
from agent_fleet.planning_agent.slots import slots_for
from agent_fleet.planning_agent.state import PlanStore
from iagent_pure.slot_acceptance import WRONG_SHAPE, accept_slots

REPO = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture
def client(monkeypatch):
    """A fresh store per test, for the reason the engine's own route suite gives: the
    module-level STORE is process-wide and order-coupling is a defect class this repo has
    already paid for once."""
    monkeypatch.setattr(engine, "STORE", PlanStore(build_seed()))
    with TestClient(engine.app) as c:
        yield c


def ask(client, fn: str, spoken: dict):
    """The chain a spoken parameter actually travels: filtered against the verb's OWN
    declarations, then splatted into the measure. Fixture-fed at the front, real from there.

    Returns (rows, refusals) so a test can assert on both what arrived and what did not."""
    accepted = accept_slots(spoken, slots_for(fn))
    r = client.post(f"/measure/{fn}", json={"params": accepted.params})
    assert r.status_code == 200, f"{fn} {accepted.params} -> {r.status_code} {r.text[:200]}"
    return r.json()["rows"], accepted.refusals


# ─────────────────────────────────────────────────────────────────────────────
# Row 1 — the wrong KIND of thing, and the one on the seeded board every demo
# ─────────────────────────────────────────────────────────────────────────────

def test_row1_funding_short_BY_INITIATIVE_returns_initiatives(client):
    """The sharpest row. "where is funding short by initiative" delivered ORGANISATIONS —
    not a superset a reader might squint at, a different kind of thing entirely, rendering
    cleanly with clean provenance and no surface on which to notice.

    Asserted on `group_by` and on the identity of the subject, NOT on the row count: both
    groupings return 11 rows in the seed, so a count assertion would pass in both directions
    and prove nothing."""
    rows, refusals = ask(client, "plan_funding_gap", {"group_by": "initiative"})
    assert not refusals
    assert {r["group_by"] for r in rows} == {"initiative"}
    assert all("initiative_id" in r for r in rows)
    assert not any("org_id" in r for r in rows), "organisations came back for an initiative question"


def test_row1_control_the_default_really_does_return_organisations(client):
    """Non-vacuity for the row above: if the default ALSO returned initiatives, the test
    would pass over a system that ignores the parameter entirely. This is the measured
    baseline the finding recorded — subject O1, Corporate Capital Committee."""
    rows, _ = ask(client, "plan_funding_gap", {})
    assert {r["group_by"] for r in rows} == {"org"}
    assert rows[0]["subject_id"] == "O1"


# ─────────────────────────────────────────────────────────────────────────────
# Row 3 — the superset, and the shape defect underneath it
# ─────────────────────────────────────────────────────────────────────────────

def test_row3_sites_in_ONE_PERIOD_returns_one_period(client):
    """"which sites exceed the threshold in FY26-Q4" returned four quarters. A superset is
    the dangerous kind of wrong: it is the right kind of thing, so it reads as an answer."""
    rows, refusals = ask(client, "plan_site_load", {"window": ["FY26-Q4"]})
    assert not refusals
    assert {r["period"] for r in rows} == {"FY26-Q4"}


def test_row3_control_the_default_spans_every_period(client):
    """The superset the finding measured. Without this the test above cannot distinguish
    "filtered correctly" from "the seed only ever had one period"."""
    rows, _ = ask(client, "plan_site_load", {})
    assert len({r["period"] for r in rows}) > 1


def test_row3_a_bare_string_for_a_LIST_slot_is_refused_not_shredded(client):
    """THE DEFECT THE DECLARATIONS THEMSELVES CARRIED, until `_type_of` was fixed.

    `window: Optional[list[str]]` was declared `type: "str"` — the Optional-unwrap rule ate
    the container. An extraction reading that declaration produces the string "FY26-Q4",
    the measure iterates it, and the engine answers

        422 unknown fiscal period(s): F, Y, 2, 6, -, Q, 4

    a message that names characters and blames the engine for a lie told upstream. The guard
    refuses the shape instead, and the engine is never asked."""
    accepted = accept_slots({"window": "FY26-Q4"}, slots_for("plan_site_load"))
    assert accepted.params == {}
    assert [r.reason for r in accepted.refusals] == [WRONG_SHAPE]

    # ...and the shredding is real, so the guard is load-bearing rather than decorative.
    r = client.post("/measure/plan_site_load", json={"params": {"window": "FY26-Q4"}})
    assert r.status_code == 422
    assert "F, Y, 2, 6" in str(r.json()), "the shredding stopped happening — re-read this test"


# ─────────────────────────────────────────────────────────────────────────────
# Row 4 — THE ARRIVAL CHECK, which is the point of the whole method
# ─────────────────────────────────────────────────────────────────────────────

def test_row4_the_plan_by_initiative_arrives_rather_than_agreeing_by_accident(client):
    """`plan_schedule.group_by` DEFAULTS to `initiative`, so the certified phrasing "broken
    out by initiative" passed while nothing was carried at all. It is the only row of the
    four that was green, and it was green for a reason that had nothing to do with the
    question.

    A delivered-vs-spoken comparison is the only instrument that separates the two, so the
    discriminator is a value that DISAGREES with the default: if `capability` comes back
    looking like `initiative`, the parameter did not arrive."""
    by_default, _ = ask(client, "plan_schedule", {})
    spoken_same, _ = ask(client, "plan_schedule", {"group_by": "initiative"})
    spoken_other, _ = ask(client, "plan_schedule", {"group_by": "capability"})

    assert spoken_same == by_default, "the spoken value that agrees with the default must not change the answer"
    assert spoken_other != by_default, (
        "a group_by that DISAGREES with the default produced the default's answer — "
        "the parameter was dropped, and row 4's green is the coincidence the finding named"
    )


def test_row4_the_declared_enum_is_what_the_verb_actually_accepts(client):
    """The values are read out of the signature's `Literal`, so the declaration cannot drift
    from the vocabulary. Proven by USING each one rather than by comparing two lists, which
    would only prove the derivation is self-consistent."""
    declared = {d["name"]: d for d in slots_for("plan_schedule")}["group_by"]["values"]
    assert declared, "no enum values derived — this test would pass over nothing"
    for v in declared:
        rows, refusals = ask(client, "plan_schedule", {"group_by": v})
        assert not refusals and rows, f"group_by={v!r} is declared but the verb refused it"


# ─────────────────────────────────────────────────────────────────────────────
# Row 2 — pre-registered, and it does NOT pass. Recorded rather than quietly dropped.
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.xfail(
    strict=True,
    reason=(
        "THE CARRY IS NOT SUFFICIENT FOR THIS ROW, and that is a finding, not a gap in the "
        "test. `plan_maturity_grid.as_of` is compared against `assessed_at` DATES "
        "('2025-12-31', '2026-06-30'); the certified phrasing speaks a FISCAL PERIOD. "
        "'FY26-Q4' string-compares above every date in the seed, so the filter admits "
        "everything and returns the unfiltered superset with a 200 — the parameter now "
        "ARRIVES and is silently ignored, which is the same class of silence the finding "
        "was raised about, one layer further in. Needs a fiscal->date resolution step that "
        "does not exist. Strict, so it goes red the moment somebody builds it."
    ),
)
def test_row2_maturity_grid_AS_OF_a_fiscal_period_filters(client):
    unfiltered, _ = ask(client, "plan_maturity_grid", {})
    scoped, _ = ask(client, "plan_maturity_grid", {"as_of": "FY26-Q4"})
    assert len(scoped) < len(unfiltered)


def test_row2_the_filter_itself_works_when_spoken_in_the_units_it_reads(client):
    """The control that makes the xfail above a TRANSLATION defect rather than a broken
    measure — the same slot, given a date, filters exactly as it should."""
    unfiltered, _ = ask(client, "plan_maturity_grid", {})
    early, _ = ask(client, "plan_maturity_grid", {"as_of": "2025-01-01"})
    assert len(early) < len(unfiltered)


# ─────────────────────────────────────────────────────────────────────────────
# The boundary, end to end through the real engine
# ─────────────────────────────────────────────────────────────────────────────

def test_a_spoken_handle_cannot_forge_a_change_log(client):
    """WHY THE CARRY SHIPS WITH A GUARD RATHER THAN GAINING ONE LATER.

    `plan_session_changes` is the decision-artifact verb — the one that answers "why did we
    move this?" long after the session. engine-p injects its `ops` and `scenario_name` into
    the SAME `params` dict a caller's values land in, and does so with `setdefault`, so a
    supplied value WINS. Carried unfiltered, a spoken `ops: []` reports zero changes for a
    scenario that has one, under any `scenario_name` the speaker likes.

    Measured here rather than argued: the unguarded call is run first, and it lies."""
    sid = "carry-probe"
    client.post("/scenario", json={"scenario_id": sid, "name": "Probe Scenario"})
    client.post(f"/scenario/{sid}/op", json={"op": "move_project", "project_id": "P1",
                                             "start": "2026-01-01", "end": "2026-03-15"})

    honest = client.post("/measure/plan_session_changes", json={"state_ref": sid}).json()["rows"]
    assert honest["change_count"] == 1 and honest["scenario_name"] == "Probe Scenario"

    forged = client.post("/measure/plan_session_changes", json={
        "state_ref": sid, "params": {"ops": [], "scenario_name": "Board-Approved Plan"}}).json()["rows"]
    assert forged["change_count"] == 0 and forged["scenario_name"] == "Board-Approved Plan", (
        "engine-p stopped honouring caller-supplied handles — good, and this test should "
        "become the seal for it rather than being deleted"
    )

    # The guard is what stands between the carry and that forgery.
    accepted = accept_slots({"ops": [], "scenario_name": "Board-Approved Plan"},
                            slots_for("plan_session_changes"))
    assert accepted.params == {}
    assert {r.reason for r in accepted.refusals} == {"route-supplied"}


# ─────────────────────────────────────────────────────────────────────────────
# The plumbing joins — that the value can reach the engine at all
# ─────────────────────────────────────────────────────────────────────────────

def test_the_routers_response_can_carry_slots():
    """Join 1's landing site. Additive and defaulted: absent means `{}` means today."""
    # Engine O's module imports rdflib at module scope; it is present in the service image
    # and not in every dev env. Skipped rather than mocked — a stub of the module under test
    # would assert that the stub has the field.
    pytest.importorskip("rdflib")
    from agent_fleet.ontology_service.main import RouteIntentResponse

    bare = RouteIntentResponse(mode="ONE_SHOT", entity_refs=[], confidence=0.9, reasoning="r")
    assert bare.slots == {}, "the default must be empty — a non-empty default would honour a question nobody asked"

    filled = RouteIntentResponse(mode="ONE_SHOT", entity_refs=[], confidence=0.9, reasoning="r",
                                 slots={"group_by": "initiative"})
    assert filled.model_dump()["slots"] == {"group_by": "initiative"}


def test_the_gateway_forwards_slots_into_the_supervisors_run_config(monkeypatch):
    """Join 3, on the real function. The first draft of this carry read `intent_extraction`
    inside `_launch_supervisor_job`, where it is not in scope — a NameError on every request
    in the cluster, with every test still green because nothing called it. Hence this
    test calls it."""
    import asyncio
    import json

    from src.iagent import gateway

    captured: dict = {}

    class _Resp:
        status_code = 200
        def json(self): return {"run_id": "r1"}
        def raise_for_status(self): return None

    class _Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None, **k):
            captured["body"] = json
            return _Resp()

    monkeypatch.setattr(gateway.httpx, "AsyncClient", _Client)
    asyncio.run(gateway._launch_supervisor_job(
        "where is funding short by initiative", "thread-1",
        slots={"group_by": "initiative"},
    ))

    run_config = json.loads(captured["body"]["variables"]["runConfig"])
    for op, cfg in run_config["ops"].items():
        assert cfg["config"]["slots"] == {"group_by": "initiative"}, f"{op} lost the slots"


def test_the_gateway_defaults_slots_to_empty(monkeypatch):
    """A caller that passes nothing must produce today's payload exactly — this is what
    makes the carry landable ahead of the slot-filler."""
    import asyncio
    import json

    from src.iagent import gateway

    captured: dict = {}

    class _Resp:
        status_code = 200
        def json(self): return {"run_id": "r1"}
        def raise_for_status(self): return None

    class _Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None, **k):
            captured["body"] = json
            return _Resp()

    monkeypatch.setattr(gateway.httpx, "AsyncClient", _Client)
    asyncio.run(gateway._launch_supervisor_job("q", "thread-1"))
    run_config = json.loads(captured["body"]["variables"]["runConfig"])
    assert run_config["ops"]["execute_subtask"]["config"]["slots"] == {}


def test_the_supervisors_dispatch_payload_CARRIES_params():
    """Join 4, asserted structurally.

    `execute_subtask` is a Dagster op that needs postgres to import, so this reads the
    source instead — deliberately, and narrowly: it asserts that the dispatch payload's
    `params` key is fed by the ACCEPTANCE FILTER'S output and not by the raw config, which
    is the one substitution that would reintroduce the handle-forgery path while every
    other test in this file still passed."""
    tree = ast.parse((REPO / "src/iagent/defs/dynamic_supervisor.py").read_text(encoding="utf-8"))

    fn = next(f for f in ast.walk(tree)
              if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)) and f.name == "execute_subtask")

    payloads = [d for d in ast.walk(fn)
                if isinstance(d, ast.Dict)
                and any(isinstance(k, ast.Constant) and k.value == "routed_verb_iri" for k in d.keys)]
    assert payloads, "the dispatch payload moved — this seal is pointing at nothing"

    for d in payloads:
        keys = [k.value for k in d.keys if isinstance(k, ast.Constant)]
        assert "params" in keys, "the dispatch payload dropped `params` — the finding is back"
        value = d.values[keys.index("params")]
        assert (isinstance(value, ast.Attribute) and value.attr == "params"
                and isinstance(value.value, ast.Name) and value.value.id == "accepted"), (
            "`params` is fed by something other than the acceptance filter's output"
        )
