"""engine-o `/fill_slots` refuses a caller who is not a person: 422 `no_person`.

THE RULINGS. Chris, 2026-10-10 (b): "scripts and restate_analyst send a real test persona or get
refused -- a domains list is never an entitlement". Architect, 2026-10-14: "a svc: literal counts
as absent in every arm, same as blank; a service identity is never a person." Chris, 2026-10-16:
"Battery scripts: /fill_slots refuses no-person callers in 190 -- your PR, same shape as #59."

WHY NOW. Same change as `/enumerate_instances` (#59) on the next route. In
`tests/security/test_every_engine_o_caller_is_classified.py`, row 2 (supervisor
`_fill_slots_from_query`, TOKEN) carries a person; rows 15/16 (the two battery scripts, NO_PERSON)
are the callers now refused.

WHAT IS SEALED. The refusal body (the shape of safety's `no_person`), that nothing downstream is
asked (the model call, which is the first thing the route reaches, is never made), the CONTROL
that differs only in the caller, and the supervisor NAMING a refused person in its log before
it degrades to defaults. It does not raise: `tests/planning/test_fill_slots_seam.py` seals that
no failure path of `_fill_slots_from_query` raises, and a raise would fail the op at
`execute_subtask`. Whether a refused person should fail the run is for a ruling, not this file.

Run: uv run --frozen pytest tests/security/test_fill_slots_refuses_a_caller_who_is_not_a_person.py -v
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

PERSON = "alice@example.com"
EXPECTED = {"error": "no_person",
            "message": "this verb answers for a person; the caller carries none",
            "fn": "fill_slots"}


@pytest.fixture
def eo(monkeypatch):
    from agent_fleet.ontology_service import main as mod
    reached: list = []

    async def _model(**kw):
        reached.append(kw)
        return SimpleNamespace(slots_json="{}", confidence=0.9, reasoning="stub")

    monkeypatch.setattr(mod.b, "FillVerbSlots", _model)
    mod._test_reached = reached
    return mod


def _post(eo, **body):
    from agent_fleet.planning_agent.slots import slots_for
    from fastapi.testclient import TestClient
    base = {"query": "q", "verb_iri": "mesh:planFundingGap",
            "declarations": json.dumps(slots_for("plan_funding_gap"))}
    return TestClient(eo.app).post("/fill_slots", json={**base, **body})


_NOT_PERSONS = [pytest.param({"user_email": ""}, id="blank"),
                pytest.param({"user_email": "  "}, id="whitespace"),
                pytest.param({}, id="absent"),
                pytest.param({"user_email": "svc:supervisor"}, id="svc"),
                pytest.param({"user_email": " svc:engine-o"}, id="padded-svc")]


@pytest.mark.parametrize("caller", _NOT_PERSONS)
def test_a_caller_who_is_not_a_person_is_refused_and_nothing_is_asked(eo, caller):
    r = _post(eo, acting_domains=["SUSTAINMENT"], **caller)
    assert r.status_code == 422, r.text
    assert r.json() == EXPECTED
    assert eo._test_reached == [], "the model was asked on behalf of a non-person"


def test_CONTROL_a_person_with_the_same_stubs_is_answered(eo):
    r = _post(eo, acting_domains=["SUSTAINMENT"], user_email=PERSON)
    assert r.status_code == 200, r.text
    assert eo._test_reached, "the model was not asked; the control proves nothing"


def test_the_in_process_call_is_refused_too(eo):
    from agent_fleet.planning_agent.slots import slots_for
    r = asyncio.run(eo.fill_slots(eo.FillSlotsRequest(
        query="q", verb_iri="mesh:planFundingGap",
        declarations=json.dumps(slots_for("plan_funding_gap")))))
    assert r.status_code == 422 and json.loads(r.body) == EXPECTED
    assert eo._test_reached == []


# --- the supervisor --------------------------------------------------------------------------

class _Ctx:
    def __init__(self):
        self.warnings: list[str] = []
        self.log = SimpleNamespace(warning=lambda msg, *a, **k: self.warnings.append(msg % a),
                                   info=lambda *a, **k: None)


def _response(status, body):
    r = requests.Response()
    r.status_code = status
    r._content = json.dumps(body).encode()
    r.headers["Content-Type"] = "application/json"
    r.url = "http://eo/fill_slots"
    return r


def _fill(monkeypatch, response):
    from iagent.defs import dynamic_supervisor as ds
    posts: list = []

    def _post(*a, **k):
        posts.append(k.get("json"))
        return response

    monkeypatch.setattr(ds.requests, "post", _post)
    ctx = _Ctx()
    got = ds._fill_slots_from_query(ctx, query="q", verb_iri="mesh:planFundingGap",
                                    declarations="[]", user_email=PERSON)
    assert posts, "the supervisor never reached the wire; the arm proves nothing"
    return got, ctx.warnings


def test_the_supervisor_names_a_no_person_refusal_and_degrades(monkeypatch):
    got, warnings = _fill(monkeypatch, _response(422, EXPECTED))
    assert got.slots == {} and got.resolution == {}
    assert len(warnings) == 1 and "refused no_person" in warnings[0], warnings


def test_CONTROL_another_422_is_the_generic_non_200(monkeypatch):
    got, warnings = _fill(monkeypatch, _response(422, {"detail": "bad"}))
    assert got.slots == {} and got.resolution == {}
    assert len(warnings) == 1 and "non-200" in warnings[0] and "no_person" not in warnings[0], warnings
