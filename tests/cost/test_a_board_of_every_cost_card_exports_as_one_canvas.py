"""A board of every cost card exports as ONE canvas, through the gateway, into the cost engine.

THE JOIN THIS SEALS. cortex-ui's canvas-level export sends EVERY non-task artifact id on the
board to `POST /export/package` as `answers: [{artifact_id}]`. The gateway reads each
artifact's `resolved_intent` from the store and forwards `{id, verb_iri, subject_instance_id}`
to engine-cost, whose `canvas.resolve` reads them. Every endpoint had a test; the join did
not: `tests/test_gateway_export_routes.py` stubs the engine with made-up IRIs (`mesh#Foo`),
and nothing asserted that what the system WRITES into `resolved_intent` survives
`canvas.resolve`.

THE FORM, DERIVED (not typed):
  * the writer is `gateway.py` ~L6796-6812 (the `subtask_slots_decision` branch of the
    streaming loop; it is inline in a generator and not importable), fed by the supervisor's
    materialization at `dynamic_supervisor.py` ~L2905-2936:
      - `verb_iri` = `predicate["verb_iri"]`, the verb as the ontology edge stores it, which
        is the COMPACT form the engine registered (`cost_agent/main.py` "verb":
        "mesh:costLotBreakdown"; `tests/test_every_registered_verb_is_compact.py`);
      - `subject_instance_id` = `telemetry["subject_instance_id"]`, the id /resolve's
        provider handed back, and the cost provider's lot id is the bare lot number as a
        string (`cost_agent/instances.py::_lots` -> `{"instance_id": str(n)}`).
  * `_resolve_export_answers` (gateway.py ~L1802) reads that JSON back and forwards
    `{id, verb_iri, subject_instance_id}`, mapping "" / "UNKNOWN" to None.

So a lot card carries `mesh:costX` + a digit string, which is exactly what `canvas._verb_local`
and `canvas._lot_number` accept. A card with no subject (trend, assumptions) carries "".

MIXED BOARD (RULED 2026-10-09, architect Q1): a board holding the 8 cost cards plus one
finance answer is SPLIT per engine. engine-cost receives only the cost partition and exports
it; the finance answer is a refusal section naming it. The response is a 200 with `documents`
and status "partial" (see `tests/test_a_mixed_board_exports_per_engine.py`).
"""
from __future__ import annotations

import json

import pytest

httpx = pytest.importorskip("httpx")
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from agent_fleet.cost_agent import canvas as C  # noqa: E402
from agent_fleet.cost_agent.entities import NotInModel  # noqa: E402
from agent_fleet.cost_agent.seed import lots_for_recipient  # noqa: E402
from src.iagent import gateway  # noqa: E402
from tests.cost.test_a_canvas_exports_the_alpha_document import (  # noqa: E402
    ALPHA_CANVAS, FIXTURE,
)

ALPHA = "notional-customer-alpha"
ALL_IDS = [a["id"] for a in ALPHA_CANVAS["answers"]]


def _resolved_intent_as_written(card: dict) -> str:
    """`resolved_intent` as the gateway writes it for a cost answer (gateway.py ~L6796-6812):
    compact verb, subject id as a string, "" when the answer has no subject. The JSON string
    is the store's shape (`answer_artifact_writer._to_json`)."""
    subject = card["subject_instance_id"]
    return json.dumps({
        "verb_iri": card["verb_iri"],
        "disposition": "route",
        "accepted_slots": {},
        "bound_slot_sources": {},
        "refused_slots": [],
        "slot_resolution": {},
        "owner_persona": "",
        "subject_uri": "",
        "subject_instance_id": "" if subject is None else str(subject),
        "subject_instance_label": "",
    })


class _Rec:
    def __init__(self, row):
        self._row = row

    def single(self):
        return self._row


class _Session:
    def __init__(self, store):
        self._store = store

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, _cypher, artifact_id=None, user_id=None, **_k):
        return _Rec(self._store.get(artifact_id))


class _Driver:
    def __init__(self, store):
        self._store = store

    def session(self):
        return _Session(self._store)


class _Resp:
    status_code = 200

    def json(self):
        return {"artifact_sha256": "sha256:" + "a" * 64,
                "artifact_filename": "cost-validation-notional-customer-alpha.html",
                "artifact_bytes": 1, "algorithm_sha": "x",
                "lots_disclosed": [], "sections": []}


@pytest.fixture
def export(monkeypatch):
    """Drive the REAL POST /export/package. Returns `run(cards)` -> the canvas the gateway
    forwarded to engine-cost (None if it forwarded none)."""
    user = type("U", (), {
        "authz_id": "alice@example.com", "id": "sub-alice", "email": "alice@example.com",
        "roles": [], "persona": None, "entitled_domains": [], "is_authenticated": True,
    })()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user
    sent: dict = {}

    class _Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

        async def post(self, url, json=None, headers=None, **k):
            sent["json"] = json
            return _Resp()

    monkeypatch.setattr(gateway.httpx, "AsyncClient", _Client)

    def run_full(cards):
        store = {c["id"]: {"id": c["id"], "is_owner": True,
                           "resolved_intent": _resolved_intent_as_written(c)} for c in cards}
        monkeypatch.setattr(gateway, "neo4j_driver", _Driver(store))
        sent.clear()
        with TestClient(gateway.app) as client:
            r = client.post("/export/package", json={
                "recipient_scope": ALPHA,
                "answers": [{"artifact_id": c["id"]} for c in cards]})
        assert r.status_code == 200, r.text
        canvas = sent["json"]["params"]["canvas"] if "json" in sent else None
        return canvas, r.json()

    def run(cards):
        return run_full(cards)[0]

    run.full = run_full
    yield run
    gateway.app.dependency_overrides.clear()


def _resolve(canvas):
    return C.resolve(canvas, recipient_scope=ALPHA, entitled_lots=lots_for_recipient(ALPHA))


def test_a_whole_board_is_forwarded_whole_in_board_order(export):
    canvas = export(ALPHA_CANVAS["answers"])
    assert [a["id"] for a in canvas["answers"]] == ALL_IDS


def test_the_board_the_gateway_forwards_resolves_to_the_alpha_sections_and_every_entitled_lot(
    export,
):
    canvas = export(ALPHA_CANVAS["answers"])
    composed = _resolve(canvas)
    assert composed["sections"] == tuple(FIXTURE["sections"])
    assert composed["lots"] == tuple(lots_for_recipient(ALPHA))
    assert composed["answers"] == ALL_IDS


def test_CONTROL_a_board_of_one_card_carries_only_that_cards_sections(export):
    """The full-board assertions can tell the two apart: one labor card is two sections and
    one lot, not the alpha document."""
    canvas = export([ALPHA_CANVAS["answers"][0]])
    composed = _resolve(canvas)
    assert composed["sections"] == ("labor", "sepm")
    assert composed["lots"] == (1,)
    assert composed["sections"] != tuple(FIXTURE["sections"])
    assert composed["lots"] != tuple(lots_for_recipient(ALPHA))


def test_MIXED_a_finance_card_is_split_off_and_the_eight_cost_cards_still_export(export):
    """RULED 2026-10-09: engine-cost receives exactly the eight cost cards (no finance id), they
    resolve to the alpha document, and the finance card is a refusal section naming it."""
    fin = {"id": "ans-fin-funding", "verb_iri": "mesh:finFundingStatus",
           "subject_instance_id": None}
    canvas, body = export.full(list(ALPHA_CANVAS["answers"]) + [fin])
    assert [a["id"] for a in canvas["answers"]] == ALL_IDS
    composed = _resolve(canvas)
    assert composed["sections"] == tuple(FIXTURE["sections"])
    assert composed["lots"] == tuple(lots_for_recipient(ALPHA))
    assert body["status"] == "partial"
    cost_doc, fin_doc = body["documents"]
    assert (cost_doc["engine"], cost_doc["status"]) == ("cost", "exists")
    assert cost_doc["answers"] == ALL_IDS
    assert (fin_doc["engine"], fin_doc["status"]) == ("fin", "failed")
    assert fin_doc["answers"] == ["ans-fin-funding"]
    assert "ans-fin-funding" in fin_doc["reason"]


def test_CONTROL_a_board_of_only_the_trend_card_discloses_every_entitled_lot(export):
    """On the 8-card board the lot cards already cover lots 1-5, so the program-wide card's
    widening is invisible there (mutation M4 stayed green on the full board). Alone, the trend
    card is the only source of lots."""
    trend = next(a for a in ALPHA_CANVAS["answers"] if a["id"] == "ans-trend")
    composed = _resolve(export([trend]))
    assert composed["lots"] == tuple(lots_for_recipient(ALPHA))
    assert composed["sections"] == ("program",)
