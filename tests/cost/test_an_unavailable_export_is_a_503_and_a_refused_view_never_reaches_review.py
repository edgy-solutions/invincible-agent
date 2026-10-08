"""Two consumers of engine-cost's refusal envelope, each read it wrong.

1. THE GATEWAY ANSWERED "THE ENGINE COULD NOT BUILD" AS A VERDICT. engine-cost refuses in a 200
   envelope (`refused: true`, `outcome`, `reason`), and `POST /export/package` relayed every
   outcome as a 200 `status: "failed"` -- so a missing runtime or a builder that exited read, at
   the HTTP edge, exactly like a refusal of the caller's request. `outcome: "unavailable"` is now
   a 503 carrying the same body as its detail; every other outcome is still a 200 `failed`.

2. THE COSTING REVIEW READ A KEY ENGINE-COST NEVER WRITES. Its fetch node tested
   `payload.get("refusal")`; the engine writes `refused`. So a refused view reached `review`, which
   headlined the refusal body as a cost figure. The row declares `refusal: fail`, so a refused
   inner verb must end the graph -- and now does.

BOTH JOINS ARE DRIVEN THROUGH THE REAL ENGINE-COST APP: the gateway's httpx client and the graph's
`httpx.post` are routed into it, so the envelope each consumer reads is the one the engine writes,
not a double's recollection of it.
"""
from __future__ import annotations

import ast
import pathlib

import pytest
from fastapi.testclient import TestClient

from agent_fleet.cost_agent import main as cost_main
from agent_fleet.cost_agent import measures as m
from agent_fleet.graph_host.graphs import cost_lot_costing_review as review_graph
from src.iagent import gateway
from tests.cost.test_the_export_survives_the_image_layout import (  # noqa: F401 (fixture)
    _SHA_POD, _stage_fake_pod_root, real_builder,
)

_SCOPE = "notional-customer-alpha"
_LOT = 3


@pytest.fixture(scope="module")
def engine():
    with TestClient(cost_main.app) as c:
        yield c


@pytest.fixture
def bff():
    user = type("U", (), {
        "authz_id": "alice@example.com", "id": "sub-alice", "email": "alice@example.com",
        "roles": [], "persona": None, "entitled_domains": [], "is_authenticated": True,
    })()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user
    with TestClient(gateway.app) as c:
        yield c
    gateway.app.dependency_overrides.clear()


def _gateway_reaches(monkeypatch, answer):
    """Route the gateway's engine call to `answer(url, json) -> response`."""
    class _Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

        async def post(self, url, json=None, headers=None, **k):
            assert url.startswith(gateway._ENGINE_COST_URL), url
            return answer(url[len(gateway._ENGINE_COST_URL):], json)

    monkeypatch.setattr(gateway.httpx, "AsyncClient", _Client)


def _export(bff):
    return bff.post("/export/package", json={"recipient_scope": _SCOPE, "answers": []})


# -- 1. the gateway --------------------------------------------------------------------------

def test_A_AN_ENGINE_THAT_CANNOT_BUILD_IS_A_503_AT_THE_EDGE_WITH_THE_BUILDERS_REASON(
        bff, engine, tmp_path, monkeypatch, real_builder):
    """The JOIN: the real engine-cost app, whose real builder refuses an unpinned loader."""
    root = _stage_fake_pod_root(tmp_path, real_builder, with_git=False)
    monkeypatch.setattr(m, "_repo_root", lambda: root)
    monkeypatch.setenv("IAGENT_GIT_SHA", _SHA_POD)
    _gateway_reaches(monkeypatch, lambda path, body: engine.post(path, json=body))

    r = _export(bff)
    assert r.status_code == 503, (
        f"the engine could not build and the edge said {r.status_code}: {r.text[:300]}")
    detail = r.json()["detail"]
    assert detail["outcome"] == "unavailable" and detail["status"] == "failed", detail
    assert detail["export_id"] is None and detail["recipient_scope"] == _SCOPE, detail
    # cortex-ui's export button renders `detail.reason` for a non-409/403 error.
    assert isinstance(detail["reason"], str)
    assert "dynamic-import branch was not found" in detail["reason"], detail["reason"]


def _engine_refusal_kinds() -> set[str]:
    """Every `outcome` engine-cost's route can write: the constant first argument of each
    `_refusal(...)` call in its source. Derived, so a kind the engine gains is covered here."""
    tree = ast.parse(pathlib.Path(cost_main.__file__).read_text(encoding="utf-8"))
    return {
        n.args[0].value for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_refusal"
        and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)
    }


def test_B_THE_DERIVED_POPULATION_HOLDS_UNAVAILABLE_AND_THE_REST():
    kinds = _engine_refusal_kinds()
    assert "unavailable" in kinds, kinds
    assert {"unentitled", "vintage_required", "not_in_model", "slot_required"} <= kinds, kinds


@pytest.mark.parametrize("kind", sorted(_engine_refusal_kinds() - {"unavailable"}))
def test_C_EVERY_OTHER_OUTCOME_IS_STILL_A_200_FAILED_EXPORT(bff, monkeypatch, kind):
    """The control: only `unavailable` moves. A refusal of THIS request stays a 200 answer."""
    class _Resp:
        status_code = 200
        def json(self):
            return {"refused": True, "outcome": kind, "reason": f"the engine said {kind}"}

    _gateway_reaches(monkeypatch, lambda path, body: _Resp())
    r = _export(bff)
    assert r.status_code == 200, (kind, r.status_code, r.text[:300])
    body = r.json()
    assert body["status"] == "failed" and body["outcome"] == kind, body
    assert body["reason"] == f"the engine said {kind}", body


# -- 2. the costing review -------------------------------------------------------------------

def _graph_reaches(monkeypatch, engine):
    def via_app(url, *, json, headers, timeout):
        assert url.startswith(review_graph.ENGINE_COST_URL), url
        return engine.post(url[len(review_graph.ENGINE_COST_URL):], json=json)

    monkeypatch.setattr(review_graph.httpx, "post", via_app)


_STATE = {"lot": _LOT, "identity": {"authorization": "Bearer person"}}


@pytest.mark.parametrize("vintage,outcome", [(None, "vintage_required"),
                                             ("not-a-vintage", "not_in_model")])
@pytest.mark.parametrize("fn,label", review_graph._VIEWS)
def test_D_A_REFUSED_VIEW_ENDS_AT_ITS_NODE_NAMING_THE_OUTCOME(
        engine, monkeypatch, fn, label, vintage, outcome):
    _graph_reaches(monkeypatch, engine)
    body = engine.post(f"/measure/{fn}",
                       json={"params": {"lot": _LOT, "rate_vintage": vintage}}).json()
    assert body.get("refused") is True and body.get("outcome") == outcome, (
        f"the fixture no longer makes the engine refuse: {body}")

    with pytest.raises(review_graph.RefusedInner) as exc:
        review_graph._fetch(fn, label)({**_STATE, "rate_vintage": vintage})
    assert f"{fn} refused: {outcome}" in str(exc.value), str(exc.value)
    assert body["reason"] in str(exc.value), "the engine's reason was dropped"


def test_E_THE_COMPILED_GRAPH_NEVER_CALLS_REVIEW_ON_A_REFUSAL(engine, monkeypatch):
    """The whole row, compiled: a refusal at the first view ends the graph before `review`."""
    _graph_reaches(monkeypatch, engine)
    reached = []
    monkeypatch.setattr(review_graph, "review",
                        lambda state: reached.append(state) or {"summary": "reviewed"})
    graph = review_graph.build().compile()
    with pytest.raises(review_graph.RefusedInner):
        graph.invoke({**_STATE, "rate_vintage": "not-a-vintage"})
    assert reached == [], "a refused view reached the review"


def test_F_THE_SAME_GRAPH_ANSWERED_DOES_REACH_REVIEW(engine, monkeypatch):
    """E's positive control: identical wiring, an answerable vintage, and `review` runs."""
    _graph_reaches(monkeypatch, engine)
    reached = []
    monkeypatch.setattr(review_graph, "review",
                        lambda state: reached.append(state) or {"summary": "reviewed"})
    out = review_graph.build().compile().invoke({**_STATE, "rate_vintage": "2021-02-01"})
    assert out["summary"] == "reviewed" and len(reached) == 1
    assert len(reached[0]["views"]) == len(review_graph._VIEWS)
