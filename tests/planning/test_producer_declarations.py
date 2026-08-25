"""The three producer declarations, asserted against their PRE-REGISTERED shapes.

Shapes were written down in docs/plans/producer-declarations-payload-preregistration.md BEFORE
any of this was emitted, so these tests check the code against an intention rather than
describing whatever came out.

THE ARM THAT MATTERS MOST IS THE UNCHANGED ONE. Each declaration adds something to a payload,
and each has a scope where it must add NOTHING. A declaration that quietly alters an existing
shape is a regression wearing a feature's commit message, and the baseline-scope samples are
pinned byte-for-byte against what the seed produced before the change.

CONVENTION, RULED 2026-08-24: risk_flag values are lowercase-hyphenated (`moved`,
`constraint-violated`), conforming to the incumbent vocabulary (`at-risk`, `unfunded`) rather
than to the checklist's `MOVED` shorthand. Nothing breaks either way — the renderer styles an
unknown string and stops — but the styling map that eventually keys these will be written
against ONE convention, and two conventions in one field means it silently misses half its
vocabulary.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agent_fleet.planning_agent import measures  # noqa: E402
from agent_fleet.planning_agent.entities import Interval  # noqa: E402
from agent_fleet.planning_agent.seed import build_seed  # noqa: E402
from agent_fleet.planning_agent.state import MoveProject, apply_ops  # noqa: E402


@pytest.fixture
def state():
    return build_seed()


# ── 1. value_unit ────────────────────────────────────────────────────────────────────────

def test_the_money_family_declares_its_unit():
    """A DECLARATION TABLE, not an inference. `run_measure` is generic and must never guess
    money-ness from a field name — `total` is money here and a count elsewhere."""
    assert measures.VALUE_UNIT["plan_cost_curve"] == "USD"
    assert measures.VALUE_UNIT["plan_funding_gap"] == "USD"


def test_non_money_verbs_declare_NOTHING():
    """Absent means silent. The renderer keeps reading `1.5M` rather than guessing a `$` the
    payload never sent — which is the shipped consumer's stated behaviour."""
    for fn in ("plan_schedule", "plan_site_load", "plan_maturity_grid",
               "plan_dependency_neighborhood", "plan_coverage_gap"):
        assert fn not in measures.VALUE_UNIT, f"{fn} declares a unit it has no business having"


def test_every_declared_unit_names_a_real_verb():
    """Positive control against a table that outlives its verbs."""
    for fn in measures.VALUE_UNIT:
        assert fn in measures.OUTPUT_URI, f"VALUE_UNIT names {fn}, which is not a verb"


# ── 2. the baseline series ───────────────────────────────────────────────────────────────

def test_baseline_scope_carries_NO_baseline_key(state):
    """ABSENT, not null. A `baseline: null` on every row would tell the renderer a comparison
    exists and is empty; absent says the card is not a comparison at all — which is the true
    statement, and the one the ghost's presence keys on."""
    for row in measures.plan_cost_curve(state):
        assert "baseline" not in row, f"{row['period']} carries a baseline in baseline scope"


def test_the_baseline_scope_row_is_BYTE_FOR_BYTE_unchanged(state):
    """THE REGRESSION ARM. Pinned against what the seed produced before this declaration."""
    q3 = next(r for r in measures.plan_cost_curve(state) if r["period"] == "FY26-Q3")
    assert q3 == {
        "period": "FY26-Q3", "capex": 4200000.0, "expense": 850000.0, "total": 5050000.0,
        "cap": 4000000.0, "over_cap": True, "overage": 1050000.0,
    }


def test_a_comparison_scope_carries_a_NESTED_baseline_series(state):
    """NESTED because the entry calls it a SERIES. Three sibling columns would have to be
    added or dropped together — an invariant living in a convention nobody enforces. One
    object cannot half-arrive."""
    moved = apply_ops(state, [MoveProject("P3", Interval("2026-07-01", "2026-09-30"))])
    rows = measures.plan_cost_curve(moved, baseline_state=state)
    q3 = next(r for r in rows if r["period"] == "FY26-Q3")
    assert set(q3["baseline"]) == {"capex", "expense", "total"}
    assert q3["baseline"]["total"] == 5050000.0


def test_the_baseline_series_is_the_BASELINE_not_a_copy_of_the_scenario(state):
    """The whole point. If the two series were equal on a period the op changed, the ghost
    would sit exactly behind the bar and the comparison would be invisible while looking
    rendered.

    THE OP HERE IS `SetCost`, NOT `MoveProject`, and that is a finding rather than a detail:
    **moving a project does not move its money.** Funding requirements are period-keyed rows,
    independent of the project's interval — the same independence as site-impact windows, one
    measure over. A drag alone therefore leaves the cost curve identical, and a ghost drawn
    from a project move would be a ghost hidden exactly behind its bar.
    """
    from agent_fleet.planning_agent.state import SetCost
    changed_state = apply_ops(
        state, [SetCost(project_id="P3", kind="capex", period="FY26-Q3", amount=1_000_000.0)]
    )
    rows = measures.plan_cost_curve(changed_state, baseline_state=state)
    changed = [r for r in rows if r["baseline"]["total"] != r["total"]]
    assert changed, "no period differs from baseline — the comparison carries no information"
    q3 = next(r for r in rows if r["period"] == "FY26-Q3")
    assert q3["baseline"]["total"] == 5050000.0 and q3["total"] != 5050000.0


def test_a_PROJECT_MOVE_alone_leaves_the_cost_curve_identical(state):
    """PINNED, because it decides what the ghost can show. `MoveProject` sets `proj.planned`;
    requirements are keyed by (project, period) and never re-derived from the interval. So the
    drag beat changes the SCHEDULE and the SITE LOAD and leaves spend untouched — which is the
    honest model, and means a cost ghost needs a funding op to have anything to draw."""
    moved = apply_ops(state, [MoveProject("P3", Interval("2026-10-01", "2026-12-31"))])
    assert measures.plan_cost_curve(moved) == measures.plan_cost_curve(state)


def test_every_row_in_a_comparison_carries_the_series(state):
    """All or none. A payload where some rows have a baseline and some do not would render a
    ghost that appears and vanishes across the axis."""
    rows = measures.plan_cost_curve(state, baseline_state=state)
    assert all("baseline" in r for r in rows)


# ── 3. risk_flag vocabulary ──────────────────────────────────────────────────────────────

def test_no_scenario_context_means_NO_flags(state):
    """Unchanged behaviour with nothing handed in. `risk_flag` stays null exactly as before,
    so the baseline schedule card is untouched by this declaration."""
    for row in measures.plan_schedule(state):
        assert row["risk_flag"] is None


def test_an_op_touched_project_is_flagged_MOVED(state):
    """Lowercase-hyphenated, conforming to the incumbent vocabulary."""
    rows = measures.plan_schedule(state, touched_project_ids={"P12"})
    p12 = [r for r in rows if r["project_id"] == "P12"]
    assert p12 and all(r["risk_flag"] == "moved" for r in p12)


def test_untouched_projects_stay_unflagged(state):
    """The flag must localise. A scenario flagging every bar tells the room nothing."""
    rows = measures.plan_schedule(state, touched_project_ids={"P12"})
    others = [r for r in rows if r["project_id"] != "P12"]
    assert others and all(r["risk_flag"] is None for r in others)


def test_a_constraint_breaching_project_is_flagged(state):
    """The FS-violation value. P5 depends on P3 (D4, FS +14); pulling P3 late breaches it."""
    broken = apply_ops(state, [MoveProject("P3", Interval("2026-10-01", "2026-12-31"))])
    assert measures.plan_dependency_violations(broken), "precondition: the move must breach D4"
    rows = measures.plan_schedule(broken)
    p5 = [r for r in rows if r["project_id"] == "P5"]
    assert p5 and all(r["risk_flag"] == "constraint-violated" for r in p5)


def test_VIOLATION_OUTRANKS_MOVED_when_both_apply(state):
    """RULED, and recorded as a CHOICE rather than a discovery.

    A broken constraint is the STATE; the move is the CAUSE — and a status flag reports state.
    The opposite reading is real ("the room moved it, show them their fingerprint") but it is
    the DIFF CARD's job: the diff attributes causes, the bar reports conditions. Two surfaces,
    two questions.
    """
    broken = apply_ops(state, [MoveProject("P3", Interval("2026-10-01", "2026-12-31"))])
    rows = measures.plan_schedule(broken, touched_project_ids={"P5"})
    p5 = [r for r in rows if r["project_id"] == "P5"]
    assert p5 and all(r["risk_flag"] == "constraint-violated" for r in p5)


def test_the_new_values_share_the_INCUMBENT_convention(state):
    """One field, one convention. A styling map keyed on lowercase-hyphen must not silently
    miss half its vocabulary — which is what shipping `MOVED` beside `at-risk` would cause."""
    rows = measures.plan_schedule(state, touched_project_ids={"P12"}, color_by="funding_risk")
    seen = {r["risk_flag"] for r in rows if r["risk_flag"]}
    assert seen, "no flags emitted — the arm proves nothing"
    for v in seen:
        assert v == v.lower(), f"{v!r} is not lowercase"
        assert " " not in v and "_" not in v, f"{v!r} is not hyphen-separated"


# ── the route: the declarations reaching the wire ────────────────────────────────────────

def _client():
    from fastapi.testclient import TestClient
    from agent_fleet.planning_agent import main as _main
    return TestClient(_main.app), _main


def test_the_envelope_carries_value_unit_for_money_verbs():
    client, _ = _client()
    for fn in ("plan_cost_curve", "plan_funding_gap"):
        body = client.post(f"/measure/{fn}", json={"params": {}}).json()
        assert body.get("value_unit") == "USD", f"{fn} envelope: {body.get('value_unit')!r}"


def test_the_envelope_OMITS_the_key_for_everything_else():
    """Absent, not null. A `value_unit: null` would be a unit the payload claims to have sent."""
    client, _ = _client()
    for fn in ("plan_schedule", "plan_site_load", "plan_coverage_gap"):
        body = client.post(f"/measure/{fn}", json={"params": {}}).json()
        assert "value_unit" not in body, f"{fn} declared a unit it has no business having"


def test_baseline_scope_gets_no_ghost_and_scenario_scope_does():
    client, main = _client()
    base = client.post("/measure/plan_cost_curve", json={"state_ref": "baseline"}).json()
    assert all("baseline" not in r for r in base["rows"])

    client.post("/scenario", json={"scenario_id": "SC-G", "name": "ghost"})
    client.post("/scenario/SC-G/op", json={"op": "set_cost", "project_id": "P3",
                                           "kind": "capex", "period": "FY26-Q3",
                                           "amount": 1000000.0})
    sc = client.post("/measure/plan_cost_curve", json={"state_ref": "SC-G"}).json()
    assert all("baseline" in r for r in sc["rows"])
    q3 = next(r for r in sc["rows"] if r["period"] == "FY26-Q3")
    assert q3["baseline"]["total"] != q3["total"], "the ghost sits exactly behind its bar"


def test_the_schedule_flags_op_touched_bars_in_scenario_scope_only():
    client, _ = _client()
    base = client.post("/measure/plan_schedule", json={"state_ref": "baseline"}).json()
    assert all(r["risk_flag"] is None for r in base["rows"])

    # A SEVEN-DAY PULL, and the number is measured rather than chosen. P12 must start no
    # earlier than P11 ends (D7, FS lag 0, P11 ends 2026-03-25); 2026-03-25 is exactly that
    # boundary. A larger pull — the 92-day one first written for beat 2 — ALSO breaks D7, and
    # `constraint-violated` outranks `moved`, so the bigger drag never shows a `moved` flag at
    # all. See test_the_scripted_pull_stays_inside_D7 below.
    client.post("/scenario", json={"scenario_id": "SC-M", "name": "moved"})
    client.post("/scenario/SC-M/reschedule", json={"project_id": "P12",
                                                   "start": "2026-03-25", "end": "2026-09-23"})
    sc = client.post("/measure/plan_schedule", json={"state_ref": "SC-M"}).json()
    p12 = [r for r in sc["rows"] if r["project_id"] == "P12"]
    assert p12 and all(r["risk_flag"] == "moved" for r in p12)
    others = [r for r in sc["rows"] if r["project_id"] != "P12"]
    assert all(r["risk_flag"] is None for r in others), "the flag did not localise"


def test_the_scripted_pull_stays_inside_D7_and_still_crosses(state):
    """THE BEAT'S BOUNDARY, measured. Beat 2 wants ONE consequence the room caused: Site B
    crossing. A pull large enough to also breach D7 gives two, and — because
    `constraint-violated` outranks `moved` — the bar the room just dragged stops reporting
    that it was dragged.

    Seven days is the largest pull that stays clean: P12 may start no earlier than P11 ends
    (D7, FS lag 0, P11 ends 2026-03-25).

    NOTE THE PHYSICS THIS RELIES ON, because it is thin and should be seen rather than
    discovered: site load counts an impact whose window OVERLAPS a period, at full weight. A
    seven-day pull slides P12's impact from 2026-10-01 to 2026-09-24, overlapping FY26-Q4 by
    seven days — and those seven days carry the same 0.9 as a full quarter would. That is the
    measure as defined and it is honest, but the crossing is driven by a sliver.
    """
    from agent_fleet.planning_agent.entities import Interval as _I
    ops = measures.derive_reschedule(state, project_id="P12",
                                     new_planned=_I("2026-03-25", "2026-09-23"))
    after = apply_ops(state, ops)
    assert measures.plan_dependency_violations(after) == [], "the scripted pull breaches D7"
    crossed = [(r["site_id"], r["period"]) for r in measures.plan_site_load(after)
               if r["over_threshold"]]
    assert crossed == [("S2", "FY26-Q4")]
    p12 = [r for r in measures.plan_schedule(after, touched_project_ids={"P12"})
           if r["project_id"] == "P12"]
    assert p12 and all(r["risk_flag"] == "moved" for r in p12)


def test_a_LARGER_pull_breaches_D7_and_the_flag_changes(state):
    """The other side, pinned so the boundary is a fact rather than a preference. Recorded
    because a richer two-consequence beat is a DEFENSIBLE script choice — but it must be a
    choice, made knowing the moved-flag disappears."""
    from agent_fleet.planning_agent.entities import Interval as _I
    ops = measures.derive_reschedule(state, project_id="P12",
                                     new_planned=_I("2026-01-01", "2026-06-30"))
    after = apply_ops(state, ops)
    viol = measures.plan_dependency_violations(after)
    assert [v["dependency_id"] for v in viol] == ["D7"]
    p12 = [r for r in measures.plan_schedule(after, touched_project_ids={"P12"})
           if r["project_id"] == "P12"]
    assert all(r["risk_flag"] == "constraint-violated" for r in p12)
