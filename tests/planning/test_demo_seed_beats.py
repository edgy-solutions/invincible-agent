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
    site load      S2 peak 2.7 / threshold 2.0, over in FY26-Q4
                   S1 1.8/2.0, S3 2.2/2.5, S4 2.0/2.5 -- all under

THE ONE THING THAT IS **NOT** PINNED HERE, and it needs a ruling rather than a test: the script
calls for "S2 FLIPS on the scripted drag". S2 is ALREADY over threshold at baseline. A drag
cannot demonstrate a crossing that has already happened, so either the drag targets a period
where S2 is currently under, or the seed puts S2 under at baseline so the drag causes the flip.
That is a script-shape decision. What IS pinned below is the half that holds unambiguously:
**S2 is the only site over threshold at all**, which is the "no other site does" requirement and
is true today.
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

def test_S2_is_the_ONLY_site_over_threshold(state):
    """The "no other site does" half of the requirement, and it holds unambiguously today."""
    rows = measures.plan_site_load(state)
    over = sorted({r["site_id"] for r in rows if r.get("over_threshold")})
    assert over == ["S2"], f"expected only S2 over threshold, got {over}"


def test_every_other_site_has_HEADROOM_not_a_near_miss(state):
    """A site at 1.99/2.00 is under threshold and reads as over on a heat grid. Pinned so the
    contrast the beat depends on is real rather than a rounding artefact."""
    rows = measures.plan_site_load(state)
    peaks: dict[str, float] = {}
    thresholds: dict[str, float] = {}
    for r in rows:
        sid = r["site_id"]
        peaks[sid] = max(peaks.get(sid, 0.0), r.get("load") or 0.0)
        thresholds[sid] = r.get("threshold")
    for sid, peak in peaks.items():
        if sid == "S2":
            continue
        assert peak <= thresholds[sid] * 0.95, \
            f"{sid} peaks at {peak} against {thresholds[sid]} — too close to read as headroom"


def test_S2_is_over_in_a_SINGLE_period(state):
    """One breach period, so the drag beat has one thing to point at."""
    rows = [r for r in measures.plan_site_load(state)
            if r["site_id"] == "S2" and r.get("over_threshold")]
    assert [r["period"] for r in rows] == ["FY26-Q4"]
