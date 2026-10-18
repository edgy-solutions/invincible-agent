"""An arrival in an open episode is a step of its case; after it closes, a new case follows it.

OpenDDIL ask 4 (architect, 2026-10-18): "episode-keyed cases, arrival under open = step, under
closed = new case with follows. Seal all three cases."

THE THREE CASES, on the openddil-lab `maintenance_fault` trigger as declared (not a fixture tree):

1. EPISODE-KEYED. A case is keyed by the id the bridge sent -- OpenDDIL keys each record on its
   `episode_id` and expects it back as `workflow.case_id` (their 2026-10-16 packet) -- and holds
   the DERIVED episode `(asset_id, fault.item, fault.fault_code)`. OpenDDIL's episode is new on
   every reset of their lab; ours is the fault. A first case says it follows nothing.
2. OPEN -> STEP. A second id for the same fault while the first case is open was a separate
   ATTACHED case nobody read. It is now a step of the open case: in the open case's `arrivals`,
   with no instance and no task of its own, and the open case's transitions -- which Lane 1's
   `GET /cases/{id}/action` reads `chose` and `released` from -- are exactly a lone case's.
3. CLOSED -> NEW CASE WITH FOLLOWS. A second id after the first case released opens its own case,
   on its own revision 1, whose record `follows` the first. A different fault on the same asset
   follows nothing: the line is the episode's, not the asset's.

WHAT IS REAL: the runner, `CaseEpisode`, the trigger/tables/definitions under policy/, the
declared walk against the committed MRAD fixture. STUBBED: as test_the_maintenance_fault_runs_as_
a_case.py (its doubles are imported, not copied), plus ONE withheld answer, so case 1 is OPEN --
claimed and waiting on its maintainer -- while the next arrival runs.

Run: uv run --frozen pytest tests/test_an_arrival_in_an_open_episode_is_a_step_of_its_case.py -v
"""
from __future__ import annotations

import asyncio
import copy

import pytest

from tests.test_a_case_runs_from_trigger_to_terminal import R, _answer, _body, _Cluster, wr
from tests.test_the_maintenance_fault_runs_as_a_case import (  # noqa: F401 (autouse fixtures)
    ACK, DECIDE, TRIGGER, _declared_walk_double, _event, _path, _real_policy, registered)

#: OpenDDIL-shaped episode ids. The first is the one their 2026-10-16 packet names in full; the
#: others are invented in the same shape. They differ; the fault they report does not.
FIRST = "c18ecb64-040f-5eab-b573-0aab1d245abc"
SECOND = "5b0e7d2a-91c4-5f3e-a8d6-2c47e1f09b13"
THIRD = "e4a9c1f7-3d28-5b6a-9e0c-71f5d2b8a640"

#: A lone resupply case, released on the tier's ack (the maintenance-fault suite's own path).
RESUPPLY = [("triaged", "selected", "maint_fault_propose"),
            ("maint_fault_propose", "replace_after_resupply", "maint_release"),
            ("maint_release", "released", "closed")]


def _resupply(key):
    return {(f"{key}~1", DECIDE): _answer("replace_after_resupply"),
            (f"{key}~2", ACK): _answer("released", "tier@x")}


def _episode(event):
    return R.episode_key(R.load_trigger(TRIGGER), R.flatten(event))


class _Held(_Cluster):
    """The runner's own cluster double, with ONE answer withheld until the arm opens the gate."""

    def __init__(self, answers, hold):
        super().__init__(answers)
        self.hold, self.gate, self.waiting = hold, asyncio.Event(), asyncio.Event()

    def ctx(self, key):
        c = super().ctx(key)
        if getattr(c, "_held", False):
            return c
        make = c.promise

        def promise(name, type_hint=None):
            p = make(name, type_hint)
            if (key, name) != self.hold:
                return p
            inner = p.value

            def value():
                async def _v():
                    self.waiting.set()
                    await self.gate.wait()
                    return await inner()
                return _v()
            p.value = value
            return p
        c.promise, c._held = promise, True
        return c


async def _open_then(arrive):
    """Case FIRST opens and waits on its maintainer; `arrive(c)` runs while it is open; then the
    maintainer answers and FIRST runs to `closed`. Returns (cluster, what arrive returned, the
    `case` read of FIRST taken while it was open, FIRST's own close)."""
    c = _Held(_resupply(FIRST), hold=(f"{FIRST}~1", DECIDE))
    first = asyncio.create_task(c.start(FIRST, TRIGGER, _event(FIRST)))
    await asyncio.wait_for(c.waiting.wait(), 5)
    got = await arrive(c)
    # A COPY: the double stores the record by reference, and `_release` updates that very dict at
    # close -- read uncopied, "while open" is the closed record (M4 survived until this copy).
    live = copy.deepcopy(await _body(wr.case)(c.ctx(FIRST), None))
    c.gate.set()
    out = await asyncio.wait_for(first, 5)
    return c, got, live, out


# ── 1. EPISODE-KEYED ────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_1_A_CASE_IS_KEYED_BY_THE_ID_SENT_AND_HOLDS_THE_DERIVED_EPISODE(registered):
    c = _Cluster(_resupply(FIRST))
    out = await c.start(FIRST, TRIGGER, _event(FIRST))
    assert (out["case_id"], out["status"], out["terminal"]) == (FIRST, "CLOSED", "closed"), out
    rec = c.case(FIRST)
    assert rec["case_id"] == FIRST, "the case id is the id the bridge sent, verbatim"
    # THE PREMISE OF 2 AND 3: two OpenDDIL episodes of one fault are one derived episode.
    assert rec["episode"] == _episode(_event(FIRST)) == _episode(_event(SECOND)), rec["episode"]
    assert "follows" in rec and rec["follows"] is None, "the first case on a fault follows nothing"
    assert rec["arrivals"] == [], rec


# ── 2. OPEN -> STEP ─────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_2_AN_ARRIVAL_WHILE_THE_CASE_IS_OPEN_IS_A_STEP_OF_IT(registered):
    async def _second(c):
        return await c.start(SECOND, TRIGGER, _event(SECOND))
    c, step, live, out = await _open_then(_second)

    assert (step["status"], step["step_of"]) == ("STEP", FIRST), step
    pointer = c.case(SECOND)
    assert pointer["step_of"] == FIRST
    assert [(t["from"], t["outcome"], t["to"]) for t in pointer["transitions"]][-1] == (
        "received", "arrival", "step")
    assert not any(k.startswith("instance:") for k in c.ctx(SECOND).state), "a step runs nothing"

    # WHILE OPEN, the open case's own read names the arrival.
    assert [a["case_id"] for a in live["arrivals"]] == [SECOND], live
    assert live["arrivals"][0]["at"], live["arrivals"]
    assert live["follows"] is None

    # AT CLOSE it is folded into the record, which no longer needs the episode to say so.
    assert out["status"] == "CLOSED", out
    rec = c.case(FIRST)
    assert [a["case_id"] for a in rec["arrivals"]] == [SECOND], rec
    assert "open" not in c.obj(_episode(_event(FIRST))).state


@pytest.mark.asyncio
async def test_2_control_A_STEP_ADDS_NO_TASK_AND_NO_TRANSITION_TO_THE_OPEN_CASE(registered):
    """Lane 1's `/cases/{id}/action` reads `chose` and `released` off the open case's transitions:
    a step must leave them exactly as a lone case's, and must file no task of its own."""
    async def _second(c):
        return await c.start(SECOND, TRIGGER, _event(SECOND))
    _c, _step, _live, out = await _open_then(_second)
    assert _path(out) == RESUPPLY, _path(out)
    assert [r[0] for r in registered] == [f"{FIRST}~1"], registered


@pytest.mark.asyncio
async def test_2_A_REPEATED_ARRIVAL_IS_ONE_STEP(registered):
    """The episode object is on the ingress: the same arrival's claim twice is still one step."""
    async def _twice(c):
        await c.start(SECOND, TRIGGER, _event(SECOND))
        return await _body(wr.claim)(c.obj(_episode(_event(SECOND))), {"case_id": SECOND})
    _c, owner, live, _out = await _open_then(_twice)
    assert owner == FIRST
    assert [a["case_id"] for a in live["arrivals"]] == [SECOND], live


# ── 3. CLOSED -> NEW CASE WITH FOLLOWS ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_3_AN_ARRIVAL_AFTER_THE_CASE_CLOSED_OPENS_A_CASE_THAT_FOLLOWS_IT(registered):
    c = _Cluster({**_resupply(FIRST), **_resupply(THIRD)})
    await c.start(FIRST, TRIGGER, _event(FIRST))
    out = await c.start(THIRD, TRIGGER, _event(THIRD))
    assert (out["case_id"], out["status"]) == (THIRD, "CLOSED"), out
    assert _path(out) == RESUPPLY, "a case of its own, run in full"
    rec = c.case(THIRD)
    assert rec["follows"] == FIRST, rec
    assert rec["arrivals"] == []
    assert [r["rev"] for r in rec["input_revisions"]] == [1], "its own chain, from revision 1"
    assert c.case(FIRST)["arrivals"] == [], "a later case is not a step of a closed one"
    # The line continues: the episode remembers the newest closed case, not the first.
    assert c.obj(_episode(_event(FIRST))).state["last"] == THIRD


@pytest.mark.asyncio
async def test_3_control_ANOTHER_FAULT_ON_THE_SAME_ASSET_FOLLOWS_NOTHING(registered):
    """The rejected rule: `follows` the asset's last case. The fixture distinguishes it -- same
    asset, another faulted item -- so a line keyed on the asset reds here. (The ITEM varies, not
    the code: the declared walk's fixture holds one fault code, and the episode keys on both.)"""
    other = copy.deepcopy(_event(THIRD))
    other["fault"]["item"] = "hydraulic-pump"
    assert other["asset_id"] == _event(FIRST)["asset_id"] and _episode(other) != _episode(
        _event(FIRST))
    c = _Cluster({**_resupply(FIRST), **_resupply(THIRD)})
    await c.start(FIRST, TRIGGER, _event(FIRST))
    await c.start(THIRD, TRIGGER, other)
    assert c.case(THIRD).get("follows") is None, c.case(THIRD)
