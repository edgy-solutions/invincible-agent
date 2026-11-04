"""THE STREAM HALF OF THE PAUSE (ruling 2026-11-03).

A run whose token cannot be refreshed pauses as ``awaiting_reauth``. The stream that watches
the run must (1) tell the card ONCE that it is waiting for the person, (2) tell it ONCE when the
person is back, (3) never let its own 900-tick ceiling end a run that is waiting for a person,
and (4) close the vault reference when the run reaches a terminal state.

DRIVEN THROUGH THE REAL ``_generate_dagster_stream_inner``, reusing the harness of
tests/planning/test_seed_panel_gates_and_fallback.py (its CONTROL turn reaches the launch). The
Dagster run is a scripted ``_get_run_status``; the vault is a real ``IdentityVault``; the clock
is not slept.

Run:  uv run --frozen python -m pytest tests/identity/test_the_stream_pauses_for_the_person.py -q
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import iagent.gateway as gw  # noqa: E402
from iagent.identity_vault import IdentityVault  # noqa: E402
from tests.planning.test_seed_panel_gates_and_fallback import stubbed_stream  # noqa: E402,F401

RUN = "run-stream-1"
ALICE = "alice@example.com"
TOKEN = "eyJhbGciOiJSUzI1NiJ9.ALICE-STREAM.signature"
FRESH = "eyJhbGciOiJSUzI1NiJ9.ALICE-STREAM-FRESH.signature"


def _req():
    return gw.InterviewRequest(
        message="how is NP-MERIDIAN's variance",
        session_id="s-stream-1",
        answering_artifact_id="artifact-1",
        bound_slots={"program_id": "NP-MERIDIAN"},
    )


@pytest.fixture
def harness(stubbed_stream, monkeypatch):  # noqa: F811
    vault = IdentityVault()
    monkeypatch.setattr(gw, "VAULT", vault)
    monkeypatch.setattr(
        gw, "_pre_resolved_from_ask",
        lambda *a, **k: {
            "subject_uri": "http://invincible-agent/fin#Program",
            "subject_instance_id": "NP-MERIDIAN", "subject_instance_label": "",
            "verb_iri": "mesh:finVarianceAnalysis", "owner_persona": "",
        },
    )

    async def _launch(*a, **k):
        return RUN

    monkeypatch.setattr(gw, "_launch_supervisor_job", _launch)
    real_sleep = asyncio.sleep

    async def _nosleep(_s=0, *a, **k):
        await real_sleep(0)

    monkeypatch.setattr(gw.asyncio, "sleep", _nosleep)
    box = {"polls": 0, "script": lambda n: {"status": "STARTED"}, "vault": vault}

    async def _status(run_id):
        box["polls"] += 1
        return box["script"](box["polls"])

    monkeypatch.setattr(gw, "_get_run_status", _status)
    return box


async def _drive(box):
    events = []
    agen = gw._generate_dagster_stream_inner(_req(), user_email=ALICE, caller_token=TOKEN)
    try:
        async for ev in agen:
            events.append(ev)
    except Exception:  # noqa: BLE001 -- the post-loop tail is not this file's subject
        pass
    return "".join(events)


def _count(blob, name):
    return blob.count(f"event: {name}")


@pytest.mark.asyncio
async def test_a_run_with_no_pause_still_ends_at_its_900_tick_ceiling(harness):
    """THE CONTROL: the deadline still exists for a run nobody is waiting on."""
    blob = await _drive(harness)
    assert harness["polls"] == 900
    assert _count(blob, "run_awaiting_reauth") == 0 and _count(blob, "run_reauth_resumed") == 0


@pytest.mark.asyncio
async def test_a_paused_run_outlives_the_ceiling_and_each_event_arrives_exactly_once(harness):
    v = harness["vault"]

    def script(n):
        if n == 1:
            v.mark_awaiting_reauth(RUN, "token_near_expiry_and_not_refreshable")
        if n == 1200:  # well past 900 ticks, the person comes back
            assert v.replace(RUN, FRESH, ALICE)
        if n == 1210:
            return {"status": "CANCELED"}
        return {"status": "STARTED"}

    harness["script"] = script
    blob = await _drive(harness)
    assert harness["polls"] == 1210, "the 900-tick ceiling ended a run waiting for its person"
    assert _count(blob, "run_awaiting_reauth") == 1
    assert _count(blob, "run_reauth_resumed") == 1
    assert blob.index("run_awaiting_reauth") < blob.index("run_reauth_resumed")
    for line in blob.splitlines():
        if line.startswith("data:") and "run_id" in line:
            assert json.loads(line[5:])["run_id"] == RUN
    assert TOKEN not in blob and FRESH not in blob


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", ["CANCELED", "FAILURE", "SUCCESS"])
async def test_the_reference_is_closed_when_the_run_reaches_a_terminal_state(harness, terminal):
    v = harness["vault"]
    v.stash(RUN, TOKEN, subject=ALICE)  # the real stash happens at launch; restated for a clean slate
    harness["script"] = lambda n: {"status": terminal if n == 3 else "STARTED"}
    await _drive(harness)
    assert v.state(RUN) is None, f"the reference outlived a {terminal} run"
    assert v.redeem(RUN, "late-call").token is None
