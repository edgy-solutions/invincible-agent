"""RULED 2026-10-17: an export's entitlement refusal says it was refused for entitlement and
nothing more. The route's `reason` is the constant `canvas.ENTITLEMENT_REFUSAL`; the
`Unentitled` exception keeps the recipient, the answer ids and the lots, and the route logs
them. Only `package_export` is ruled; another verb keeps its own message."""
from __future__ import annotations

import json
import logging

import pytest
from fastapi.testclient import TestClient

from agent_fleet.cost_agent import canvas as C
from agent_fleet.cost_agent import main as cost_main
from agent_fleet.cost_agent import measures as M
from tests.cost.test_a_canvas_exports_the_alpha_document import ALPHA, _a, _resolve

#: alpha reads lot 2 but not lot 7.
CANVAS = {"answers": [_a("mine", "costLaborComposition", 2),
                      _a("theirs", "costLaborComposition", 7)]}


def _post_export():
    with TestClient(cost_main.app) as c:
        return c.post("/measure/package_export", json={"params": {
            "recipient_scope": ALPHA, "canvas": CANVAS}})


def test_the_route_refuses_with_the_constant_and_names_no_lot_answer_or_recipient():
    with pytest.raises(C.Unentitled) as ei:
        _resolve(CANVAS)
    detail = str(ei.value)
    for needle in ("7", "theirs", ALPHA):  # positive control: the exception DOES carry each
        assert needle in detail, (needle, detail)

    body = _post_export().json()
    assert body.get("refused") is True and body.get("outcome") == "unentitled", body
    assert body["reason"] == C.ENTITLEMENT_REFUSAL, body
    wire = json.dumps(body)
    for needle in ("7", "theirs", ALPHA):
        assert needle not in wire, (needle, wire)


def test_the_warning_log_carries_the_lot(caplog):
    with caplog.at_level(logging.WARNING, logger="engine-cost"):
        _post_export()
    msgs = [r.getMessage() for r in caplog.records
            if r.name == "engine-cost" and r.levelno == logging.WARNING]
    assert any("theirs (lot 7)" in m and ALPHA in m for m in msgs), msgs


def test_another_verb_keeps_its_own_unentitled_message(monkeypatch):
    def _verb(*a, **k):
        raise C.Unentitled("this verb's own message, naming lot 7")

    monkeypatch.setitem(M.VERBS, "cost_unit_price_trend", _verb)
    with TestClient(cost_main.app) as c:
        r = c.post("/measure/cost_unit_price_trend", json={"params": {}})
    body = r.json()
    assert body.get("outcome") == "unentitled", body
    assert body["reason"] == "this verb's own message, naming lot 7", body
    assert body["reason"] != C.ENTITLEMENT_REFUSAL
