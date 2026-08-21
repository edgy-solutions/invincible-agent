"""The BFF's planning routes — the seam cortex-ui actually calls.

WHAT THESE DEFEND THAT THE ENGINE'S OWN ROUTE TESTS DO NOT:

  * the BFF must NOT name an archetype. `/instances_by_property` next door is a "temporary
    feeder" that hand-sets `"archetype": "INSTANCES_BY_PROPERTY"` — acknowledged as such, and
    exactly the `archetype-chosen-before-data` shape ADR-0042 §2 forbids for new work. A new
    route copying its neighbour is the most likely way that shape spreads, so it is asserted
    against here rather than trusted to discipline.

  * `frontend_id` must reach the response. It is what makes menu-scoped selection possible at
    all, and wiring it as None is the trap the seam's own packet records: every caller
    resolves to the default menu and every answer becomes a KNOWLEDGE_DOCUMENT — a regression
    that reads as completion.

  * an engine refusal must cross as a refusal. A 422 `not_in_model` collapsing into a 200 with
    an empty list at the BFF would destroy the honest-refusal path one hop from where it was
    carefully built.

The engine is stubbed rather than run: these are tests of the BFF's TRANSLATION, and standing
up Engine P would test the engine again while hiding a translation defect behind a working
backend.
"""
from __future__ import annotations

import pytest

httpx = pytest.importorskip("httpx")
fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import gateway  # noqa: E402


ENGINE_OK = {
    "measure": "plan_cost_curve",
    "output_uri": "http://invincible-agent/mesh#PeriodCostSeries",
    "state_ref": "baseline",
    "state_version": 3,
    "rows": [{"period": "FY26-Q3", "total": 5050000.0, "cap": 4000000.0,
              "over_cap": True, "overage": 1050000.0}],
}


class _Resp:
    def __init__(self, status: int, body):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("engine error", request=None, response=None)  # type: ignore[arg-type]


@pytest.fixture
def stub_engine(monkeypatch):
    """Capture what the BFF sends and control what the engine returns."""
    sent: dict = {}

    class _Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None, **k):
            sent["url"] = url
            sent["json"] = json
            return sent.get("_resp") or _Resp(200, ENGINE_OK)

    monkeypatch.setattr(gateway.httpx, "AsyncClient", _Client)
    return sent


@pytest.fixture
def client(monkeypatch):
    """Auth is bypassed at the dependency, not by disabling it — the route keeps its
    Depends(get_current_user) so a future removal of that dependency is still a visible diff."""
    user = type("U", (), {"authz_id": "tester", "sub": "tester", "persona": "PORTFOLIO_LEAD",
                          "domains": ["PORTFOLIO_PLANNING"], "is_authenticated": True})()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user
    with TestClient(gateway.app) as c:
        yield c
    gateway.app.dependency_overrides.clear()


# ─────────────────────────────────────────────────────────────────────────────

def test_the_bff_forwards_the_measure_and_returns_output_uri_and_rows(client, stub_engine):
    r = client.post("/plan/measure/plan_cost_curve",
                    json={"state_ref": "baseline", "params": {}},
                    headers={"X-Frontend-Id": "cortex-ui-desktop"})
    assert r.status_code == 200
    body = r.json()
    assert body["output_uri"] == "http://invincible-agent/mesh#PeriodCostSeries"
    assert body["rows"][0]["period"] == "FY26-Q3"
    assert body["state_version"] == 3
    assert stub_engine["url"].endswith("/measure/plan_cost_curve")


def test_the_bff_NAMES_NO_ARCHETYPE(client, stub_engine):
    """ADR-0042 §2. The BFF says WHAT this is; select_presentation decides HOW it draws.
    Its neighbour `/instances_by_property` hand-sets an archetype and is a documented
    temporary feeder — a new route copying it is how that shape spreads."""
    r = client.post("/plan/measure/plan_cost_curve", json={},
                    headers={"X-Frontend-Id": "cortex-ui-desktop"})
    # Non-vacuous: a 404 body also contains no archetype, so the status is asserted first.
    assert r.status_code == 200, "route missing — this assertion would pass over nothing"
    body = r.json()
    forbidden = {"archetype", "view", "chart_type", "component", "layout"}
    assert not (forbidden & set(body)), f"BFF named a presentation concern: {forbidden & set(body)}"


def test_the_frontend_id_reaches_the_response_so_selection_can_be_menu_scoped(client, stub_engine):
    """Wiring this as None is the trap the seam's packet records: every caller resolves to the
    default menu and every answer becomes a KNOWLEDGE_DOCUMENT — a regression that reads as
    completion, with 'the charts stopped appearing' as its only symptom."""
    body = client.post("/plan/measure/plan_cost_curve", json={},
                       headers={"X-Frontend-Id": "cortex-ui-desktop"}).json()
    assert body["frontend_id"] == "cortex-ui-desktop"


def test_an_absent_frontend_id_is_carried_as_absent_not_invented(client, stub_engine):
    """A non-UI caller is not an error. But the BFF must not substitute a plausible id — that
    would make an anonymous caller indistinguishable from a registered one at the selector,
    which is the exact distinction Ruling 9 depends on."""
    body = client.post("/plan/measure/plan_cost_curve", json={}).json()
    assert body["frontend_id"] is None


def test_an_engine_refusal_crosses_as_a_refusal(client, stub_engine):
    """422 with `not_in_model` must survive the hop. Collapsing it into a 200 with [] would
    destroy the honest-refusal path one hop from where it was built."""
    stub_engine["_resp"] = _Resp(422, {"detail": {"not_in_model": "unknown capability 'C99'"}})
    r = client.post("/plan/measure/plan_capability_path",
                    json={"params": {"capability_id": "C99"}},
                    headers={"X-Frontend-Id": "cortex-ui-desktop"})
    assert r.status_code == 422
    assert "not_in_model" in r.json()["detail"]


def test_an_unreachable_engine_is_502_and_says_so(client, stub_engine):
    """Not a 200 with empty rows. An unreachable engine and an empty result are different
    facts, and only one of them means 'nothing is planned'."""
    class _Boom:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k): raise httpx.ConnectError("no route to host")
    import src.iagent.gateway as g
    g.httpx.AsyncClient = _Boom  # type: ignore[assignment]
    r = client.post("/plan/measure/plan_cost_curve", json={},
                    headers={"X-Frontend-Id": "cortex-ui-desktop"})
    assert r.status_code == 502
    assert "unreachable" in str(r.json()["detail"]).lower()
