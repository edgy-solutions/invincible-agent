"""The episode compares an attaching delegate with the open case's seeder (Chris, 2026-11-06).

    "the refile tests' security half for #283 (a delegate cannot attach to a case it didn't seed)"

lane/saf's seal (`tests/test_a_delegate_attaches_only_to_a_case_it_seeded.py`, #287) drives the
door. These arms are the runner's half and the door's join, on the same harness:

  - `claim` records the holder's seeder; `release` drops it with the episode.
  - `attach` refuses a delegate that is not the holder's seeder. That covers another delegate's
    case and a person's. The refusal records nothing and does not name the holder. The seeding
    delegate and a person attach as #283 ruled.
  - An episode claimed before `claim` recorded a seeder is compared on the holder's own case
    record, read once and kept. It is never refused or admitted on a guess.
  - The run's race fallback, an occurrence that saw no holder at the door, applies the same rule.
  - The door answers the runner's refusal as a 403 with the runner's code, and writes no row.

Each refusal arm has a control that differs only in the caller.
"""
from __future__ import annotations

import json

import pytest

from tests.test_a_case_runs_from_trigger_to_terminal import (  # noqa: F401
    DOOR_BLOCK, _Cluster, _body, _episode, _facts, _hops, policy, registered, restate, wr,
)
from tests.test_an_occurrence_attaches_to_its_open_episode import (  # noqa: F401
    _occurrences, can_drop_open, gateway, pytestmark, world,
)

from fastapi.testclient import TestClient

A, B = "svc-a@example.test", "svc-b@example.test"
PERSON = "alice@example.com"


async def _held(seeded_by, *, legacy=False):
    """An episode held by E-1. `legacy`: claimed before `claim` recorded a seeder, so the episode
    carries only `open` and the seeder is on E-1's own case record."""
    c = _Cluster()
    o = c.obj("ep-x")
    if legacy:
        o.state["open"] = "E-1"
        c.ctx("E-1").state["case"] = {"case_id": "E-1", "seeded_by": seeded_by}
    else:
        await _body(wr.claim)(o, {"case_id": "E-1", "seeded_by": seeded_by})
    return c, o


def _attach(o, event_id, seeded_by):
    return _body(wr.attach)(o, {"event_id": event_id, "received_at": "t", "ingest_id": "i",
                                "seeded_by": seeded_by})


REFUSED = {"attached_to": None, "predecessor": None, "refused": wr.NOT_THE_SEEDER}
ADMITTED = {"attached_to": "E-1", "predecessor": None}


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True], ids=["recorded", "claimed-before-the-record"])
@pytest.mark.parametrize("seeder,caller,answer", [
    (A, B, REFUSED),          # another delegate's case
    (A, A, ADMITTED),         # control: the seeding delegate
    (None, B, REFUSED),       # a person's case
    (A, None, ADMITTED),      # control: a person attaches, as #283 ruled
    (None, None, ADMITTED),   # control: a person on a person's case
], ids=["foreign-delegate", "seeder-control", "delegate-on-a-persons-case", "person-control",
        "person-on-person-control"])
async def test_ATTACH_ADMITS_A_DELEGATE_ONLY_ONTO_THE_CASE_IT_SEEDED(seeder, caller, answer, legacy):
    c, o = await _held(seeder, legacy=legacy)
    assert await _attach(o, "E-2", caller) == answer
    occ = o.state.get("occurrences:E-1")
    if answer is REFUSED:
        assert occ is None                                    # a refusal records nothing
        assert "E-1" not in json.dumps(answer)                # and does not name the holder
    else:
        assert [x["event_id"] for x in occ] == ["E-2"]
    if legacy and caller is not None:                         # read once from the case, kept
        assert o.state["holder"] == {"seeded_by": seeder}
    elif legacy:                                              # a person never asks
        assert "holder" not in o.state


@pytest.mark.asyncio
async def test_A_CLAIMED_BEFORE_THE_RECORD_HOLDER_IS_READ_ONCE():
    c, o = await _held(A, legacy=True)
    assert await _attach(o, "E-2", A) == ADMITTED
    c.ctx("E-1").state["case"]["seeded_by"] = B      # a later read would see B
    assert await _attach(o, "E-3", B) == REFUSED     # the kept record still says A


@pytest.mark.asyncio
async def test_RELEASE_DROPS_THE_SEEDER_WITH_THE_EPISODE():
    c, o = await _held(A)
    assert o.state["holder"] == {"seeded_by": A}
    await _body(wr.release)(o, {"case_id": "E-1"})
    assert "holder" not in o.state
    # with none open, any caller is answered the predecessor, as #283 ruled
    assert await _attach(o, "E-2", B) == {"attached_to": None, "predecessor": "E-1"}


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["", "  ", 7])
async def test_A_BLANK_SEEDED_BY_IS_REFUSED_AT_ATTACH(bad):
    c, o = await _held(A)
    with pytest.raises(restate.TerminalError) as exc:
        await _attach(o, "E-2", bad)
    assert exc.value.status_code == 400
    assert o.state.get("occurrences:E-1") is None


async def _race(seeded_by, holder_seeder=A):
    """E-2's run reaches triage while E-1 holds the episode: the door saw no holder."""
    c = _Cluster()
    ep = _episode(_facts("E-2"))
    await _body(wr.claim)(c.obj(ep), {"case_id": "E-1", "seeded_by": holder_seeder})
    req = {"trigger": "fault", "facts": _facts("E-2"), "provenance": DOOR_BLOCK}
    if seeded_by is not None:
        req["seeded_by"] = seeded_by
    out = await _body(wr.run)(c.ctx("E-2"), req)
    return c, ep, out


@pytest.mark.asyncio
async def test_THE_RACE_FALLBACK_REFUSES_A_FOREIGN_DELEGATE(policy, registered):
    c, ep, out = await _race(B)
    assert out["status"] == "FAILED" and "attached_to" not in out, out
    assert _hops(c.case("E-2"))[-1] == ("received", wr.NOT_THE_SEEDER, "failed")
    assert "E-1" not in c.case("E-2")["transitions"][-1]["reason"]
    assert c.obj(ep).state.get("occurrences:E-1") is None
    assert c.obj(ep).state["open"] == "E-1" and registered == []


@pytest.mark.asyncio
@pytest.mark.parametrize("seeded_by", [A, None], ids=["seeder-control", "person-control"])
async def test_THE_RACE_FALLBACK_CONTROL_ATTACHES(seeded_by, policy, registered):
    c, ep, out = await _race(seeded_by)
    assert (out["status"], out["attached_to"]) == ("ATTACHED", "E-1"), out
    assert _hops(c.case("E-2"))[-1] == ("received", "duplicate", "attached")
    assert [x["event_id"] for x in c.obj(ep).state["occurrences:E-1"]] == ["E-2"]


@pytest.fixture
def delegates(monkeypatch):
    monkeypatch.setenv("DELEGATE_ON_BEHALF_OF", json.dumps({A: [PERSON], B: [PERSON]}))


def _post(facts, caller):
    user = type("U", (), {"authz_id": caller, "id": caller, "sub": caller, "email": caller,
                          "persona": None, "entitled_domains": [], "is_authenticated": True})()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user
    return TestClient(gateway.app).post("/ingest/events", json={
        "content_kind": "episode-event", "on_behalf_of": PERSON, "payload": facts})


@pytest.mark.parametrize("caller,status", [(B, 403), (A, 200)],
                         ids=["foreign-delegate", "seeder-control"])
def test_THE_DOOR_ANSWERS_THE_RUNNERS_REFUSAL_WITH_ITS_CODE_AND_WRITES_NOTHING(
        world, delegates, caller, status):
    assert _post(_facts("E-1"), A).status_code == 200
    rows_before = set(world.rows)
    out = _post(_facts("E-2"), caller)
    assert out.status_code == status, out.text
    if status == 403:
        assert out.json()["detail"]["error"] == wr.NOT_THE_SEEDER      # the join, not a restatement
        assert "E-1" not in out.text
        assert set(world.rows) == rows_before                          # no status row
        assert "case" not in world.cluster.ctx("E-2").state            # no case
        assert not _occurrences(world, _facts(), "E-1")
    else:
        assert out.json()["workflow"] == {"case_id": "E-1", "started": False, "attached": True}
