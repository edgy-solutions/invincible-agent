"""A mixed board exports PER ENGINE: a refused engine is a section, the rest export.

RULED (architect, 2026-10-09, Q1): the ad-hoc `POST /export/package` splits a board's answers
by the engine that serves their verb. engine-cost gets only its own answers; engine-fin, which
packages a ratified template's panels and takes no ad-hoc answers, is a refusal section made
in the gateway. A cost-only board answers in today's shape (no `documents`) and still raises
on an engine refusal -- the section form is only for a board that has a fin answer on it.
"""
from __future__ import annotations

import json

import pytest

httpx = pytest.importorskip("httpx")
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from agent_fleet.cost_agent import canvas as C  # noqa: E402
from src.iagent import gateway  # noqa: E402

SCOPE = "notional-customer-alpha"
GOOD = "sha256:" + "a" * 64


def _card(aid, verb, subject=""):
    return {"id": aid, "verb_iri": verb, "subject": subject}


COST1 = _card("c1", "mesh:costTrendAnalysis")
COST2 = _card("c2", "mesh:costLotBreakdown", "1")
FIN1 = _card("f1", "mesh:finFundingStatus")
FIN2 = _card("f2", "mesh:finBurnRate")


def _store_row(card):
    return {"id": card["id"], "is_owner": True, "resolved_intent": json.dumps(
        {"verb_iri": card["verb_iri"], "subject_instance_id": card["subject"]})}


class _Rec:
    def __init__(self, row): self._row = row
    def single(self): return self._row


class _Session:
    def __init__(self, store, log): self._store, self._log = store, log
    def __enter__(self): return self
    def __exit__(self, *a): return False

    def run(self, _cypher, artifact_id=None, user_id=None, **_k):
        self._log.append(artifact_id)
        return _Rec(self._store.get(artifact_id))


class _Driver:
    def __init__(self, store, log): self._store, self._log = store, log
    def session(self): return _Session(self._store, self._log)


class _Resp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body if body is not None else {
            "artifact_sha256": GOOD, "artifact_filename": "cost-validation-x.html",
            "artifact_bytes": 1, "algorithm_sha": "x", "lots_disclosed": [], "sections": []}
        self.text = json.dumps(self._body)

    def json(self): return self._body


class _World:
    """Records every engine call; `reply` is a _Resp, or an Exception to raise."""
    def __init__(self):
        self.posts: list[dict] = []
        self.reads: list[str] = []
        self.reply = _Resp()


@pytest.fixture
def world(monkeypatch):
    w = _World()
    user = type("U", (), {
        "authz_id": "alice@example.com", "id": "sub-alice", "email": "alice@example.com",
        "roles": [], "persona": None, "entitled_domains": [], "is_authenticated": True,
    })()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user

    class _Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

        async def post(self, url, json=None, headers=None, **k):
            w.posts.append(json)
            if isinstance(w.reply, Exception):
                raise w.reply
            return w.reply

    monkeypatch.setattr(gateway.httpx, "AsyncClient", _Client)

    def post(cards, scope=SCOPE, ids=None):
        monkeypatch.setattr(gateway, "neo4j_driver",
                            _Driver({c["id"]: _store_row(c) for c in cards}, w.reads))
        body = {"answers": [{"artifact_id": i} for i in (ids or [c["id"] for c in cards])]}
        if scope is not None:
            body["recipient_scope"] = scope
        with TestClient(gateway.app) as client:
            return client.post("/export/package", json=body)

    w.post = post
    yield w
    gateway.app.dependency_overrides.clear()


def _sent_ids(w):
    return [a["id"] for a in w.posts[0]["params"]["canvas"]["answers"]]


def test_a_cost_only_board_answers_in_todays_shape(world):
    r = world.post([COST1, COST2])
    assert r.status_code == 200, r.text
    body = r.json()
    assert "documents" not in body
    assert set(body) == {
        "export_id", "status", "recipient_scope", "reason", "artifact_uri", "artifact_sha256",
        "artifact_bytes", "artifact_filename", "algorithm_sha", "lots_disclosed", "sections",
        "template_id"}
    assert body["status"] == "exists"
    assert _sent_ids(world) == ["c1", "c2"]


def test_a_fin_only_board_never_calls_engine_cost(world):
    r = world.post([FIN1, FIN2])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "failed"
    assert [d["engine"] for d in body["documents"]] == ["fin"]
    assert body["documents"][0]["answers"] == ["f1", "f2"]
    assert body["documents"][0]["outcome"] == "not_in_model"
    assert world.posts == []


def test_an_engine_cost_refusal_becomes_its_section_not_the_response(world):
    world.reply = _Resp(422, {"detail": {"reason": "lot_not_entitled", "lot": 9}})
    r = world.post([COST1, FIN1])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "failed"
    assert body["reason"] == "2 of 2 engines refused"
    cost = body["documents"][0]
    assert cost["engine"] == "cost" and cost["status"] == "failed"
    assert "lot_not_entitled" in cost["reason"]
    # CONTROL: the same refusal on a COST-ONLY board still raises, as today.
    r2 = world.post([COST1])
    assert r2.status_code == 422
    assert r2.json()["detail"] == {"reason": "lot_not_entitled", "lot": 9}


def test_engine_cost_unreachable_is_an_unavailable_section_on_a_mixed_board(world):
    world.reply = ConnectionError("engine down")
    r = world.post([COST1, FIN1])
    assert r.status_code == 200, r.text
    cost = r.json()["documents"][0]
    assert cost["status"] == "failed" and cost["outcome"] == "unavailable"
    assert "engine down" in cost["reason"]
    assert world.post([COST1]).status_code == 502  # control: cost-only still raises


def test_every_verb_engine_fin_serves_is_split_off_and_no_cost_verb_is():
    from agent_fleet.finance_agent.main import VERB_TO_FN

    def klass(verb):
        parts = gateway._partition_export_answers([{"id": "a", "verb_iri": verb}])
        assert len(parts) == 1
        return parts[0][0]

    assert VERB_TO_FN and C.EXPORTABLE  # positive control: both populations are non-empty
    fin = {k for k in VERB_TO_FN if klass(k) == "fin"}
    cost = {"mesh:" + k for k in C.EXPORTABLE if klass("mesh:" + k) == "cost"}
    assert fin == set(VERB_TO_FN), "an engine-fin verb is not classified fin"
    assert cost == {"mesh:" + k for k in C.EXPORTABLE}, "a cost verb was classified fin"
    assert not (fin & cost)
    for k in VERB_TO_FN:
        assert klass(C.MESH + k.removeprefix("mesh:")) == "fin"  # the full-IRI form


def test_an_unknown_verb_still_goes_to_engine_cost_which_names_it(world):
    foo = _card("x1", "https://example.org/mesh#Foo")
    r = world.post([COST1, foo])
    assert r.status_code == 200 and "documents" not in r.json()
    assert _sent_ids(world) == ["c1", "x1"]
    assert gateway._partition_export_answers(
        [{"id": "n", "verb_iri": None}])[0][0] == "cost"


def test_the_fin_refusal_is_local_only_while_engine_fin_takes_templates():
    """When this reds, engine-fin can take ad-hoc answers and the gateway's local fin refusal
    (`_fin_ad_hoc_refusal_section`) is wrong: forward them instead."""
    from agent_fleet.finance_agent.main import PackageCanvas
    assert PackageCanvas.model_fields["template_id"].is_required()
    assert "answers" not in PackageCanvas.model_fields


def test_a_missing_answer_404s_before_any_engine_on_a_mixed_board(world):
    # the MISSING one is the fin id: resolving only the cost partition would miss it.
    r = world.post([COST1], ids=["c1", "f-missing"])
    assert r.status_code == 404
    assert r.json()["detail"]["artifact_id"] == "f-missing"
    assert world.posts == []


def test_recipient_gates_still_precede_the_split(world):
    r = world.post([COST1, FIN1], scope=None)
    assert r.status_code == 409
    r = world.post([COST1, FIN1], scope="not-a-scope")
    assert r.status_code == 403
    assert world.posts == [] and world.reads == []


def test_documents_follow_board_order(world):
    body = world.post([FIN1, COST1, FIN2, COST2]).json()
    assert [d["engine"] for d in body["documents"]] == ["fin", "cost"]
    assert body["documents"][0]["answers"] == ["f1", "f2"]
    assert body["documents"][1]["answers"] == ["c1", "c2"]
    assert body["status"] == "partial"
    assert body["documents"][1]["status"] == "exists"
