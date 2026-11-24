"""A measure picked from `/askable_measures` is asked the way a board ask is: the server's own
list names the subject, `dispatch_pre_resolved` confirms it against the mesh, and the routing
calls (`/route_intent`, `/plan`, `/resolve`, `/classify_predicate`) never run on the label.

SECTION 1 -- `orchestrate()`'s gates, called directly with `generate_dagster_stream` stubbed to a
call-counter, so a refusal is told from a pass by WHETHER THE STREAM WAS REACHED.
SECTION 2 -- the stream, driven through `_generate_dagster_stream_inner` with the doubles'
REQUESTS asserted (what `dispatch_pre_resolved` and the launch were handed), never their return.
SECTION 3 -- `GET /askable_measures` serves exactly the model's fields: the internal `subject`
the BFF dispatches with is not served.

Run: uv run pytest tests/routing/test_an_askable_pick_is_asked_without_routing.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import iagent.gateway as gw  # noqa: E402
from iagent import menu_blocks  # noqa: E402
from iagent.auth import User  # noqa: E402

_REAL_ASKABLE = menu_blocks.askable
_VERB = "mesh:finSomeMeasure"
_SUBJECT = "http://example.invalid/ont#TheServersSubject"
_CELL = "CELL_A"
_ENTRY = {
    "verb": _VERB, "name": "Some measure", "description": "d", "phrasings": ["some measure"],
    "cells": [_CELL], "shape": None, "unit": None, "example_ask": None, "group_label": None,
    "subject": _SUBJECT,
}
_MSG = "askable_pick names a measure that is not on your askable list."


@pytest.fixture(autouse=True)
def _the_list(monkeypatch):
    """The server's list: one measure, in one cell. Patched where `orchestrate` and the stream
    both read it (`menu_blocks.askable`)."""
    monkeypatch.setattr(
        menu_blocks, "askable",
        lambda: menu_blocks.AskableMeasures(True, [dict(_ENTRY)], []),
    )


def _user(domains) -> User:
    return User(id="u1", authz_id="alice@example.com", entitlement_source="none",
                entitled_domains=list(domains))


class _HttpReq:
    headers: dict = {}


async def _orchestrate(domains=(_CELL,), **fields):
    req = gw.InterviewRequest(message="a label", session_id="s-ap-1", **fields)
    return await gw.orchestrate(req, _HttpReq(), _user(domains))


# ── SECTION 1 -- the gates ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def stream_calls(monkeypatch):
    calls: list = []
    monkeypatch.setattr(gw, "generate_dagster_stream", lambda *a, **k: calls.append((a, k)))
    return calls


@pytest.mark.asyncio
async def test_a_verb_the_caller_holds_the_cell_for_is_accepted(stream_calls):
    """THE CONTROL of the two refusals below: the same verb, a caller who holds the cell."""
    result = await _orchestrate(askable_pick={"verb": _VERB, "bindings": {"program_id": "P1"}})
    assert result is not None
    assert len(stream_calls) == 1


@pytest.mark.asyncio
async def test_a_verb_not_in_the_callers_cells_is_422_with_the_one_message(stream_calls):
    with pytest.raises(HTTPException) as ei:
        await _orchestrate(domains=("SOME_OTHER_CELL",), askable_pick={"verb": _VERB, "bindings": {}})
    assert ei.value.status_code == 422
    assert ei.value.detail == _MSG
    assert stream_calls == []


@pytest.mark.asyncio
async def test_an_unknown_verb_is_the_same_status_and_body_as_a_withheld_one(stream_calls):
    with pytest.raises(HTTPException) as withheld:
        await _orchestrate(domains=("SOME_OTHER_CELL",), askable_pick={"verb": _VERB, "bindings": {}})
    with pytest.raises(HTTPException) as unknown:
        await _orchestrate(askable_pick={"verb": "mesh:noSuchMeasure", "bindings": {}})
    assert (unknown.value.status_code, unknown.value.detail) == (
        withheld.value.status_code, withheld.value.detail)
    assert stream_calls == []


@pytest.mark.asyncio
async def test_an_unreadable_list_is_503_not_a_refusal(stream_calls, monkeypatch):
    monkeypatch.setattr(
        menu_blocks, "askable", lambda: menu_blocks.AskableMeasures(False, [], []))
    with pytest.raises(HTTPException) as ei:
        await _orchestrate(askable_pick={"verb": _VERB, "bindings": {}})
    assert ei.value.status_code == 503
    assert "could not be read" in str(ei.value.detail)
    assert stream_calls == []


@pytest.mark.asyncio
async def test_askable_pick_with_seed_panel_is_422(stream_calls):
    with pytest.raises(HTTPException) as ei:
        await _orchestrate(
            askable_pick={"verb": _VERB, "bindings": {}},
            seed_panel={"template_id": "program_finance", "panel": 0,
                        "bindings": {"program": "NP-MERIDIAN"}},
        )
    assert ei.value.status_code == 422
    assert "askable_pick and seed_panel" in str(ei.value.detail)
    assert stream_calls == []


@pytest.mark.asyncio
async def test_askable_pick_with_answering_artifact_id_is_422(stream_calls):
    with pytest.raises(HTTPException) as ei:
        await _orchestrate(
            askable_pick={"verb": _VERB, "bindings": {}}, answering_artifact_id="artifact-1")
    assert ei.value.status_code == 422
    assert "askable_pick and answering_artifact_id" in str(ei.value.detail)
    assert stream_calls == []


# ── SECTION 2 -- the stream ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def stubbed(monkeypatch):
    """Everything the stream reaches for I/O, stubbed; the REQUESTS the doubles receive are what
    the tests read: `posts` (every httpx POST url), `dispatch` (kwargs of each
    `dispatch_pre_resolved`), `launch` (kwargs of each launch), `bundles`."""
    rec = {"posts": [], "dispatch": [], "launch": [], "bundles": [],
           "outcome": gw.direct_dispatch.DirectOutcome(kind=gw.direct_dispatch.ABSTAIN, reason="x")}

    class _FakeHttpClient:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, *a, **k):
            rec["posts"].append(str(url))
            raise RuntimeError("no network in this test")

    monkeypatch.setattr(gw.httpx, "AsyncClient", _FakeHttpClient)
    monkeypatch.setattr(gw, "_accumulated_slots", lambda *a, **k: {})

    async def _artifact(bundle):
        rec["bundles"].append(bundle)

    monkeypatch.setattr(gw, "_dispatch_answer_artifact", _artifact)

    async def _launch(*a, **k):
        rec["launch"].append(k)
        return None

    monkeypatch.setattr(gw, "_launch_supervisor_job", _launch)

    def _dispatch(**kwargs):
        rec["dispatch"].append(kwargs)
        return rec["outcome"]

    monkeypatch.setattr(gw, "dispatch_pre_resolved", _dispatch)
    return rec


async def _run(**fields):
    req = gw.InterviewRequest(message="a label", session_id="s-ap-2", **fields)
    return "".join([ev async for ev in gw._generate_dagster_stream_inner(req)])


@pytest.mark.asyncio
async def test_a_pick_with_its_program_bound_is_dispatched_once_and_never_routed(stubbed):
    await _run(askable_pick={"verb": _VERB, "bindings": {"program_id": "NP-MERIDIAN", "x": ""}})
    (call,) = stubbed["dispatch"]
    assert call["pre_resolved"]["subject_uri"] == _SUBJECT
    assert call["pre_resolved"]["verb_iri"] == _VERB
    assert call["bound_slots"] == {"program_id": "NP-MERIDIAN"}, "None/'' are dropped"
    assert not [u for u in stubbed["posts"] if "route_intent" in u], stubbed["posts"]
    assert stubbed["launch"] == [], "a ROUTED/ABSTAIN pick launched the run"


@pytest.mark.asyncio
async def test_the_subject_is_the_servers_not_the_requests(stubbed):
    await _run(askable_pick={
        "verb": _VERB, "bindings": {"program_id": "P1"},
        "subject": "http://example.invalid/ont#TheRequestsSubject",
        "subject_uri": "http://example.invalid/ont#TheRequestsSubject",
    })
    (call,) = stubbed["dispatch"]
    assert call["pre_resolved"]["subject_uri"] == _SUBJECT


@pytest.mark.asyncio
async def test_a_FALL_BACK_is_a_visible_failure_and_the_run_is_not_launched(stubbed):
    stubbed["outcome"] = gw.direct_dispatch.DirectOutcome(
        kind=gw.direct_dispatch.FALL_BACK, reason="verifier unreachable: down")
    blob = await _run(askable_pick={"verb": _VERB, "bindings": {"program_id": "P1"}})
    assert "askable_pick_fell_back" in blob, blob
    assert stubbed["launch"] == [], "a pick's FALL_BACK reached the full run on its label"
    assert not [u for u in stubbed["posts"] if "route_intent" in u]


@pytest.mark.asyncio
async def test_a_FALL_BACK_for_a_verb_outside_the_cell_names_that_cause(stubbed):
    stubbed["outcome"] = gw.direct_dispatch.DirectOutcome(
        kind=gw.direct_dispatch.FALL_BACK,
        reason=f"verb {_VERB} {gw.direct_dispatch.VERB_NOT_IN_CELL}: it declares ['D']",
        missing_domains=("D",))
    blob = await _run(askable_pick={"verb": _VERB, "bindings": {"program_id": "P1"}})
    assert "askable_pick_verb_not_visible" in blob, blob
    assert "askable_pick_fell_back" not in blob
    assert stubbed["launch"] == []


@pytest.mark.asyncio
async def test_an_ASK_launches_the_run_with_the_route_and_the_label_flag(stubbed):
    stubbed["outcome"] = gw.direct_dispatch.DirectOutcome(
        kind=gw.direct_dispatch.ASK, reason="a spoken-mandatory slot is unbound")
    await _run(askable_pick={"verb": _VERB, "bindings": {}})
    (launch,) = stubbed["launch"]
    assert launch["pre_resolved"]["subject_uri"] == _SUBJECT
    assert launch["pre_resolved"]["verb_iri"] == _VERB
    assert launch["message_is_label"] is True
    assert not [u for u in stubbed["posts"] if "route_intent" in u]


@pytest.mark.asyncio
async def test_the_CONTROL_an_ordinary_turn_is_not_a_label(stubbed, monkeypatch):
    """The same stubs, an ordinary ask-derived turn: the run is launched WITHOUT the label flag."""
    stubbed["outcome"] = gw.direct_dispatch.DirectOutcome(
        kind=gw.direct_dispatch.FALL_BACK, reason="verifier unreachable: down")
    monkeypatch.setattr(
        gw, "_pre_resolved_from_ask",
        lambda *a, **k: {"subject_uri": _SUBJECT, "subject_instance_id": "P1",
                         "subject_instance_label": "", "verb_iri": _VERB, "owner_persona": ""},
    )
    req = gw.InterviewRequest(message="q", session_id="s-ap-3", answering_artifact_id="artifact-1",
                              bound_slots={"program_id": "P1"})
    _ = [ev async for ev in gw._generate_dagster_stream_inner(req)]
    (launch,) = stubbed["launch"]
    assert not launch.get("message_is_label")


# ── SECTION 3 -- the served list does not change ────────────────────────────────────────────

class _User3:
    id = "u"
    email = "u@example.invalid"

    def __init__(self, domains):
        self.entitled_domains = list(domains)


def test_the_served_entry_carries_exactly_the_models_fields(monkeypatch):
    """`subject` is internal: the list the BFF reads has it, the list it serves does not."""
    monkeypatch.setattr(
        menu_blocks, "askable",
        lambda: menu_blocks.AskableMeasures(True, [dict(_ENTRY)], []),
    )
    gw.app.dependency_overrides[gw.get_current_user] = lambda: _User3([_CELL])
    try:
        with TestClient(gw.app) as c:
            r = c.get("/askable_measures")
    finally:
        gw.app.dependency_overrides.clear()
    assert r.status_code == 200, r.text
    served = r.json()["measures"]
    assert served and "subject" in menu_blocks.askable().measures[0]
    for entry in served:
        assert set(entry) == set(gw.AskableMeasure.model_fields)
        assert "subject" not in entry


def test_every_measure_the_real_list_names_carries_the_engines_subject():
    """The list is the place that knows verb -> subject: each entry's `subject` is the engine's
    registration (a built-in's `VERBS[...]["input_uri"]`; a declared row's `declared_subject()`)."""
    from agent_fleet.finance_agent import main as fin
    from agent_fleet.finance_agent import measure_verbs

    menu_blocks.clear_cache()
    try:
        by_verb = {v["verb"]: v["input_uri"] for v in fin.VERBS}
        got = _REAL_ASKABLE()
        assert got.composed and got.measures
        for m in got.measures:
            assert m["subject"] == by_verb[m["verb"]], m["verb"]
        assert measure_verbs.declared_subject() == fin._declared_input_uri()
    finally:
        menu_blocks.clear_cache()
