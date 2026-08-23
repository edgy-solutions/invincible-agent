"""Engine P's HTTP surface — the seam the BFF will actually call.

WHY ROUTE TESTS AND NOT JUST UNIT TESTS. The measures are already covered as pure functions.
What is NOT covered by those is everything the wire adds: that a refusal crosses as 422 with
a machine-readable discriminant rather than as an empty 200, that `output_uri` and
`state_version` are actually ON the response (a live view's freshness stamp and the pull
trigger both live there), and that the baseline anti-goal survives translation from a Python
exception into an HTTP status.

The demo flow is walked end to end here — fork, drag, diff, commit — because that sequence is
the product, and a suite that tests each step alone can pass while the sequence is broken.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent_fleet.planning_agent import main as engine
from agent_fleet.planning_agent.seed import build_seed
from agent_fleet.planning_agent.state import PlanStore

M = 1_000_000.0


@pytest.fixture
def client(monkeypatch):
    """A FRESH store per test. The module-level STORE is process-wide, so without this the
    tests order-couple — and this repo has spent a whole enforcement arc on exactly that
    class (see the suite-signal work). Rebuilt rather than deep-copied so a mutation in one
    test cannot reach another by any route."""
    monkeypatch.setattr(engine, "STORE", PlanStore(build_seed()))
    with TestClient(engine.app) as c:
        yield c


# ─────────────────────────────────────────────────────────────────────────────
# The contract every response carries
# ─────────────────────────────────────────────────────────────────────────────

def test_a_measure_response_declares_its_output_uri_and_never_a_view(client):
    """ADR-0042 §2. The engine says WHAT this is; select_presentation decides HOW it draws.
    If a view/archetype/chart_type ever appears here, `archetype-chosen-before-data` has been
    re-opened from the engine end."""
    r = client.post("/measure/plan_cost_curve", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["output_uri"] == "http://invincible-agent/mesh#PeriodCostSeries"
    forbidden = {"view", "archetype", "chart_type", "component", "layout"}
    assert not (forbidden & set(body)), f"engine named a presentation concern: {forbidden & set(body)}"


# The minimum slots each verb needs to run. Three of the ten are SUBJECT-SCOPED — they
# answer a question about a named thing and have nothing to say without it. Written out
# rather than defaulted, because a verb that invents a subject when none was supplied is
# how "which capability?" gets silently answered about the wrong one.
MINIMUM_PARAMS: dict[str, dict] = {
    "plan_capability_path":   {"capability_id": "C4"},
    "plan_process_evolution": {"process_id": "BP2"},
    "plan_tech_footprint":    {"tech_id": "T1"},
    # plan_diff needs no params: `vs` defaults to baseline, and a scenario
    # diffed against baseline with no ops is legitimately empty.
    "plan_dependency_neighborhood": {"project_id": "P5", "direction": "upstream"},
}


def test_every_declared_verb_runs_and_declares_a_distinct_output_uri(client):
    """The catalogue and the module must not drift. A verb registered to the mesh that 404s
    here is a routable promise with nothing behind it."""
    # DERIVED, not hardcoded. This read `== 12` and went stale the day a thirteenth verb
    # landed — the drift guard carrying the number it is guarding, which is the same defect
    # test_prime_timeout_bounds_agree had. The property is that the CATALOGUE and the ROUTES
    # agree, not that either has a particular size.
    from agent_fleet.planning_agent import main as _main
    expected = len(_main.VERBS)
    assert expected >= 12, f"only {expected} verbs declared — the catalogue shrank unexpectedly"

    listed = client.get("/verbs").json()["verbs"]
    assert len(listed) == expected
    uris = {v["output_uri"] for v in listed}
    assert len(uris) == expected,         "two verbs share an output_uri — the type is meant to be fixed AND distinct"
    for v in listed:
        body = {"params": MINIMUM_PARAMS.get(v["fn"], {})}
        r = client.post(f"/measure/{v['fn']}", json=body)
        assert r.status_code == 200, f"{v['fn']} -> {r.status_code} {r.text[:200]}"
        assert r.json()["output_uri"] == v["output_uri"]


@pytest.mark.parametrize("fn", sorted(MINIMUM_PARAMS))
def test_a_subject_scoped_verb_refuses_an_empty_call_rather_than_guessing(client, fn):
    """400, not a 500 and not a 200 over some default subject. A verb asked "which
    capability?" with no answer must say so — picking one would produce a confident,
    correct-looking card about the wrong thing, which is the wrong-but-confident class the
    eval gate treats as an automatic fail."""
    r = client.post(f"/measure/{fn}", json={})
    assert r.status_code == 400
    assert "bad params" in r.json()["detail"]


def test_an_unknown_measure_is_404_not_an_empty_result(client):
    assert client.post("/measure/plan_nonsense", json={}).status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# The refusal path, across the wire
# ─────────────────────────────────────────────────────────────────────────────

def test_out_of_model_refuses_with_a_machine_readable_discriminant(client):
    """422 with `not_in_model`, never 200 with []. An empty row set renders as 'none found',
    which is a false statement about something that does not exist — and the refusal path
    cannot fire on a 200."""
    r = client.post("/measure/plan_capability_path", json={"params": {"capability_id": "C99"}})
    assert r.status_code == 422
    assert "not_in_model" in r.json()["detail"]
    assert "C99" in r.json()["detail"]["not_in_model"]


def test_an_unknown_state_ref_is_404(client):
    r = client.post("/measure/plan_cost_curve", json={"state_ref": "SC-nope"})
    assert r.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# The demo flow, end to end
# ─────────────────────────────────────────────────────────────────────────────

def test_the_whole_meeting_loop(client):
    """tension -> question -> proposal -> consequences -> decision, over HTTP.

    This is the product. Each step is covered elsewhere; this asserts the SEQUENCE, which is
    the thing a demo actually exercises and which per-step tests can all pass without.
    """
    # TENSION: Q3 is over its cap on first load, with no interaction.
    base = client.post("/measure/plan_cost_curve", json={}).json()
    q3 = next(r for r in base["rows"] if r["period"] == "FY26-Q3")
    assert q3["over_cap"] is True and q3["overage"] == pytest.approx(1.05 * M)

    # ...and Site B is over threshold in Q4, likewise unprompted.
    load = client.post("/measure/plan_site_load", json={}).json()
    assert any(r["site_id"] == "S2" and r["period"] == "FY26-Q4" and r["over_threshold"]
               for r in load["rows"])

    # PROPOSAL: fork, then make the natural move — drag Wave 1 Cutover left.
    assert client.post("/scenario", json={"scenario_id": "SC1", "name": "Option A"}).status_code == 200
    r = client.post("/scenario/SC1/op", json={
        "op": "move_project", "project_id": "P5", "start": "2026-07-01", "end": "2026-09-30",
    })
    assert r.status_code == 200 and r.json()["version"] == 1

    # CONSEQUENCES: the same verb over two state refs IS the diff (ADR-0042 OQ2).
    base_v = client.post("/measure/plan_dependency_violations", json={}).json()
    scen_v = client.post("/measure/plan_dependency_violations", json={"state_ref": "SC1"}).json()
    assert base_v["rows"] == []                       # baseline clean — the trap was unsprung
    assert len(scen_v["rows"]) == 1                   # and the move sprang it
    assert scen_v["rows"][0]["dependency_id"] == "D4"
    assert scen_v["rows"][0]["shortfall_days"] == 13

    # The freshness stamp advanced with the op; baseline's did not.
    assert scen_v["state_version"] == 1
    assert base_v["state_version"] == 0

    # MEMORY: the change log answers "what did this meeting do".
    changes = client.post("/measure/plan_session_changes", json={"state_ref": "SC1"}).json()
    assert changes["rows"]["change_count"] == 1
    assert changes["rows"]["changes"][0]["op"] == "move_project"
    assert changes["rows"]["changes"][0]["project_id"] == "P5"
    assert changes["rows"]["scenario_name"] == "Option A"


def test_baseline_is_untouched_while_a_scenario_carries_the_change(client):
    client.post("/scenario", json={"scenario_id": "SC1", "name": "Option A"})
    client.post("/scenario/SC1/op", json={
        "op": "move_project", "project_id": "P5", "start": "2026-07-01", "end": "2026-09-30"})
    rows = client.post("/measure/plan_schedule", json={}).json()["rows"]
    p5 = next(r for r in rows if r["project_id"] == "P5")
    assert p5["planned_start"] == "2026-10-01"   # baseline, unmoved


# ─────────────────────────────────────────────────────────────────────────────
# The anti-goal survives the wire
# ─────────────────────────────────────────────────────────────────────────────

def test_a_drag_cannot_edit_baseline_over_http(client):
    """'No editing baseline directly from a drag' translated into a status code. An anti-goal
    that only exists in a plan document is a suggestion."""
    r = client.post("/baseline/op", json={
        "op": "move_project", "project_id": "P5", "start": "2027-01-01", "end": "2027-03-31"})
    assert r.status_code == 400
    assert "require a scenario" in r.json()["detail"]


def test_a_cost_edit_may_write_baseline_because_costs_must_persist(client):
    r = client.post("/baseline/op", json={
        "op": "set_cost", "project_id": "P3", "kind": "capex",
        "period": "FY26-Q3", "amount": 1.0 * M})
    assert r.status_code == 200 and r.json()["version"] == 1
    q3 = next(x for x in client.post("/measure/plan_cost_curve", json={}).json()["rows"]
              if x["period"] == "FY26-Q3")
    assert q3["capex"] == pytest.approx((1.00 + 1.80 + 0.20) * M)


def test_an_unknown_op_is_rejected_rather_than_ignored(client):
    client.post("/scenario", json={"scenario_id": "SC1", "name": "Option A"})
    assert client.post("/scenario/SC1/op", json={"op": "teleport_project", "project_id": "P5"}).status_code == 400


def test_a_bad_op_leaves_no_phantom_version_bump(client):
    """The room must not see a version advance for a change that did not apply."""
    client.post("/scenario", json={"scenario_id": "SC1", "name": "Option A"})
    client.post("/scenario/SC1/op", json={
        "op": "move_project", "project_id": "P99", "start": "2027-01-01", "end": "2027-03-31"})
    assert client.get("/state/SC1/version").json()["version"] == 0
