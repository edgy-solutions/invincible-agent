"""RULED 2026-11-23 (architect): engine-cost refuses a caller's `as_of`, paired with the BFF.

A cost export's dates are stamped by this engine's clock (`measures._request_date`). A caller's
`as_of` is a request-shape fault: a 422 `as_of_not_accepted`, never a silent drop and never an
ADR-0049 `outcome`. The slot is gone from the verb's signature, so the ontology cannot ask a
person for it. Mirrors finance's `_AS_OF_REFUSED`; the BFF sends none and refuses one too.

The page's `generated` date being the pinned `_request_date` is pinned by
`test_a_canvas_exports_the_alpha_document.py::test_AS_OF_absent_is_the_request_date_resolved_ONCE`.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent_fleet.cost_agent import main as cost_main
from agent_fleet.cost_agent import measures as M
from agent_fleet.cost_agent import slots

ALPHA = "notional-customer-alpha"


@pytest.mark.parametrize("value", ["2026-01-02", "yesterday", "", None])
def test_a_caller_as_of_is_a_422_and_the_verb_never_runs(monkeypatch, value):
    calls = []
    monkeypatch.setattr(M, "_request_date", lambda: calls.append(1) or "2031-03-04")
    ran = []
    real = M.VERBS["package_export"]
    monkeypatch.setitem(M.VERBS, "package_export", lambda *a, **k: ran.append(1) or real(*a, **k))
    with TestClient(cost_main.app) as c:
        r = c.post("/measure/package_export", json={"params": {
            "recipient_scope": ALPHA, "as_of": value}})
    assert r.status_code == 422, (r.status_code, r.text[:300])
    detail = r.json()["detail"]
    assert detail["error"] == "as_of_not_accepted" and detail["field"] == "as_of"
    assert isinstance(detail["reason"], str) and detail["reason"]
    assert ran == [] and calls == []


def test_the_refusal_comes_before_the_mandatory_slot_check(monkeypatch):
    with TestClient(cost_main.app) as c:
        r = c.post("/measure/package_export", json={"params": {"as_of": "2026-01-02"}})
    assert r.status_code == 422 and r.json()["detail"]["error"] == "as_of_not_accepted"


def test_as_of_is_not_a_declared_slot_of_package_export():
    assert "as_of" not in {d["name"] for d in slots.slots_for("package_export")}
