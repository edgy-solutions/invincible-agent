"""The seed contains its own demo — pinned, so a later seed edit cannot quietly remove a beat.

WHY THESE ARE TESTS AND NOT A CHECKLIST. Two of the three scripted conditions were ALREADY TRUE
when measured on 2026-08-24, against predictions that said otherwise in both directions. A
condition that is already satisfied is the dangerous kind: nobody edits it deliberately, and a
future seed change breaks it silently because nothing was watching. **An already-true condition
needs its test pinned; an edit-created one needs its before-state recorded.** These are the
pins.

MEASURED BEFORE ANY EDIT (the before-state, for attribution):

    coverage gap   9 capabilities, 8 covered, 1 uncovered (C9 "Regulatory Reporting")
    Q3 overrun     FY26-Q3 total 5,050,000 vs cap 4,000,000 -- over by 1,050,000
    site load      S2 peak 2.7 / threshold 2.0, OVER in FY26-Q4  <- since REVISED
                   S1 1.8/2.0, S3 2.2/2.5, S4 2.0/2.5 -- all under

RULED AND EDITED 2026-08-24: S2 now sits UNDER at baseline and the drag CAUSES the crossing.
The old state (S2 already over) made the beat narratively incoherent — a room seeing Site B
already red reads a second red cell as "more of the same", not "watch this decision break
something". The beat's payload is CAUSALITY, and a pre-existing breach dilutes it.

THE DRAG IS TWO OPS, and that is a finding rather than a workaround. `MoveProject` sets
`proj.planned` and does NOT touch site-impact windows, while `plan_site_load` overlaps the
IMPACT window — so a project drag alone cannot change site load. The windows are deliberately
independent: P12's project runs Apr-Sep while its S2 impact is a Jul-Sep SUBSET, because a
rollout's disruptive phase is narrower than the rollout. Auto-co-moving on MoveProject would
destroy that distinction. So the scripted reschedule emits `MoveProject` AND `MoveSiteImpact`,
which is what a real reschedule is.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agent_fleet.planning_agent import measures  # noqa: E402
from agent_fleet.planning_agent.seed import build_seed  # noqa: E402


@pytest.fixture
def state():
    return build_seed()


# ── Beat: the coverage gap ───────────────────────────────────────────────────────────────

def test_exactly_one_capability_is_uncovered(state):
    """EXACTLY ONE. Two would make the beat ambiguous — a room asked to look at "the gap"
    would have to be told which — and zero would make the absence query answer nothing on the
    one question it exists to answer."""
    out = measures.plan_coverage_gap(state)
    unc = out["uncovered_capabilities"]
    assert len(unc) == 1, f"expected exactly one uncovered capability, got {[c['capability_id'] for c in unc]}"
    assert unc[0]["capability_id"] == "C9"


def test_the_gap_is_not_on_any_capability_path(state):
    """The capability-path beat draws from capabilities that HAVE contributions. C9 has none —
    which is what makes it the gap — so the two beats cannot collide over it."""
    contributing = {c.capability_id for c in state.contributions}
    assert "C9" not in contributing


def test_the_gap_is_not_S2_ADJACENT(state):
    """The site-load beat is about S2. If the uncovered capability were advanced by a project
    that also loads S2, the two beats would share a cause and a room could not tell which
    finding it was looking at."""
    c9_projects = {x.project_id for x in state.contributions if x.capability_id == "C9"}
    s2_projects = {i.project_id for i in state.site_impacts if i.site_id == "S2"}
    assert not (c9_projects & s2_projects)


def test_the_gap_carries_no_technology_edge(state):
    """The tech-footprint beat walks technology -> capability. C9 having no such edge keeps it
    out of that beat too."""
    assert not [t for t in state.tech_capabilities if t.capability_id == "C9"]


def test_the_gap_is_NOT_the_only_enabler_of_its_process(state):
    """RECORDED, not asserted away. C9 enables BP1 — and so do six other capabilities, so the
    gap is not load-bearing for that process.

    THE RESIDUAL ADJACENCY, stated so the script can avoid it: if the process-evolution beat
    renders **BP1**, the uncovered C9 appears there too and the same fact shows up in two
    beats. **BP2 is enabled by C3/C4/C5/C6/C7 and does not touch C9** — so a process beat
    scoped to BP2 keeps the gap in exactly one place.
    """
    bp1_enablers = [c.capability_id for c in state.capabilities
                    if "BP1" in (c.enables_process_ids or [])]
    assert "C9" in bp1_enablers
    assert len(bp1_enablers) > 1, "C9 is BP1's only enabler — the gap would break that beat"

    bp2_enablers = [c.capability_id for c in state.capabilities
                    if "BP2" in (c.enables_process_ids or [])]
    assert "C9" not in bp2_enablers, "BP2 is the isolation-preserving scope for the process beat"


# ── Beat: the Q3 overrun ─────────────────────────────────────────────────────────────────

def test_FY26_Q3_is_over_its_cap(state):
    """Visible on first load with no interaction — the plan's Gate 1 wording."""
    rows = {r["period"]: r for r in measures.plan_cost_curve(state)}
    q3 = rows["FY26-Q3"]
    assert q3["over_cap"] is True
    assert q3["total"] > q3["cap"]


def test_Q3_is_the_ONLY_period_over_cap(state):
    """A second breach would split the room's attention on the beat that opens the demo."""
    over = [r["period"] for r in measures.plan_cost_curve(state) if r.get("over_cap")]
    assert over == ["FY26-Q3"], f"expected only FY26-Q3 over cap, got {over}"


def test_the_overrun_is_material_enough_to_read(state):
    """A 1% breach renders as a rounding error on a bar chart. Pinned at the measured
    magnitude so a seed edit that shaves it cannot quietly make the beat invisible."""
    rows = {r["period"]: r for r in measures.plan_cost_curve(state)}
    q3 = rows["FY26-Q3"]
    assert (q3["total"] - q3["cap"]) / q3["cap"] > 0.20


# ── Beat: the site threshold ─────────────────────────────────────────────────────────────

from agent_fleet.planning_agent.entities import Interval  # noqa: E402
from agent_fleet.planning_agent.state import MoveSiteImpact, PlanStore, apply_ops  # noqa: E402

# The scripted drag, named once so the test and the script cannot describe different moves.
SCRIPTED_DRAG = MoveSiteImpact("P12", "S2", Interval("2026-07-15", "2026-09-30"))


def test_NO_site_is_over_threshold_at_baseline(state):
    """The opening screen shows ONE red thing — Q3's funding overrun — and the drag creates
    the second. Two pre-existing breaches would split the room's attention before anyone has
    done anything."""
    over = [(r["site_id"], r["period"]) for r in measures.plan_site_load(state)
            if r.get("over_threshold")]
    assert over == [], f"a site is already over at baseline: {over}"


def test_S2_sits_NEAR_ITS_CEILING_at_baseline(state):
    """THE HEADROOM IS LOAD-BEARING and deliberately small. A site at 0.5/2.0 that flips reads
    as the drag doing something enormous, which misrepresents the physics. 1.8/2.0 reads as a
    site that was always one decision away — the foreshadowing the beat depends on."""
    rows = [r for r in measures.plan_site_load(state) if r["site_id"] == "S2"]
    peak = max(r["load"] for r in rows)
    threshold = rows[0]["threshold"]
    assert peak < threshold, f"S2 peaks at {peak} against {threshold} — not under"
    # Float sum: 1.2 + 0.6 == 1.7999999999999998. Compared as a RATIO with tolerance rather
    # than equality, because pinning a float literal here would fail on an unrelated re-order.
    assert peak / threshold >= 0.85,         f"S2 peaks at {peak}/{threshold} — too much headroom to foreshadow a crossing"


def test_the_SCRIPTED_DRAG_causes_S2_to_cross(state):
    """The beat, executed. Named as one op constant so the script and this test cannot drift
    into describing different moves."""
    after = apply_ops(state, [SCRIPTED_DRAG])
    s2 = [r for r in measures.plan_site_load(after)
          if r["site_id"] == "S2" and r.get("over_threshold")]
    assert s2, "the scripted drag does not push S2 over — the beat has no payload"
    assert [r["period"] for r in s2] == ["FY26-Q4"]


def test_the_crossing_is_LEGIBLE_not_marginal(state):
    """Same rule as Q3's overrun: a 1% breach renders as a rounding error. Pinned so a later
    weight change cannot make the beat technically true and visually invisible."""
    after = apply_ops(state, [SCRIPTED_DRAG])
    r = next(x for x in measures.plan_site_load(after)
             if x["site_id"] == "S2" and x["over_threshold"])
    assert (r["load"] - r["threshold"]) / r["threshold"] > 0.20


def test_NO_OTHER_SITE_flips_under_the_same_drag(state):
    """The crossing is SINGULAR and therefore attributable. If two sites tipped, the diff
    card would be honest and the beat would still be unreadable."""
    after = apply_ops(state, [SCRIPTED_DRAG])
    over = sorted({r["site_id"] for r in measures.plan_site_load(after)
                   if r.get("over_threshold")})
    assert over == ["S2"], f"expected only S2 to cross, got {over}"


def test_the_drag_is_REVERSIBLE_and_baseline_is_untouched(state):
    """`apply_ops` never mutates its input — the scenario is a fork, and the room can undo by
    discarding it. Pinned because the demo drags live and a mutated baseline would be
    unrecoverable on stage."""
    before = [(r["site_id"], r["period"], r["load"]) for r in measures.plan_site_load(state)]
    apply_ops(state, [SCRIPTED_DRAG])
    after = [(r["site_id"], r["period"], r["load"]) for r in measures.plan_site_load(state)]
    assert before == after


def test_a_PROJECT_move_alone_does_NOT_move_site_load(state):
    """THE FINDING, PINNED. `MoveProject` sets `proj.planned`; `plan_site_load` overlaps the
    IMPACT window. They are deliberately independent — P12's project runs Apr-Sep while its
    S2 impact is a Jul-Sep subset, because a rollout's disruptive phase is narrower than the
    rollout.

    So a timeline drag that emits only MoveProject changes the BAR and not the LOAD, and the
    diff would show a schedule change with no site consequence. This test exists so that
    stays a deliberate design rather than a surprise on stage: the scripted reschedule emits
    BOTH ops.
    """
    from agent_fleet.planning_agent.state import MoveProject
    moved = apply_ops(state, [MoveProject("P12", Interval("2026-07-01", "2026-09-30"))])
    s2_before = {(r["period"], r["load"]) for r in measures.plan_site_load(state)
                 if r["site_id"] == "S2"}
    s2_after = {(r["period"], r["load"]) for r in measures.plan_site_load(moved)
                if r["site_id"] == "S2"}
    assert s2_before == s2_after, "MoveProject moved site load — the windows are no longer independent"
