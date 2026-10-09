"""The cost export seam's BFF routes (relay item 3) — GET /export/package/recipients,
POST /export/package, and GET /export/package/artifact/{filename}.

Harness mirrors tests/test_gateway_ingest_routes.py and tests/planning/test_gateway_plan_routes.py:
TestClient(gateway.app) + dependency_overrides[get_current_user], and the cost engine is faked
via a recording httpx.AsyncClient stand-in rather than hit for real — these are tests of the
ROUTE's translation and gate, not of engine-cost's own package_export (covered in tests/cost).

WHAT THESE DEFEND:
  * ADR-0047 §1: no default recipient — a blank recipient_scope is a 409 naming the options
    the CALLER actually reads, never the full recipient catalogue.
  * the production gate and the download gate both key on authz_id via
    seed.readers_for_recipient, and both run BEFORE anything downstream is touched (the
    engine on production, the answer-store lookup on production, the engine on download).
  * a canvas answer id that does not resolve is REFUSED (404), never silently dropped — an
    export missing an answer nobody asked to drop would look complete while disclosing less
    than intended.
  * the caller's own bearer crosses to the engine on BOTH routes — never a service identity
    (the confused-deputy argument seed.py's RECIPIENT_READERS comment makes).
  * artifact_uri in the production response is always the GATEWAY's own path, never the
    engine's `out["artifact_uri"]` — a link that bypassed this file's download gate would
    make the gate decorative.
  * the download route's closed-set + recipient check is structural: an unproducible
    filename never reaches the engine at all.
"""
from __future__ import annotations

import pytest

httpx = pytest.importorskip("httpx")
fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import gateway  # noqa: E402


ALICE_TOKEN = "alice-token"

#: A syntactically valid sha256 locator (engine-cost's own artifact_sha256 shape).
GOOD_SHA = "sha256:" + "a" * 64
ALPHA_HTML = "cost-validation-notional-customer-alpha.html"
BETA_HTML = "cost-validation-notional-customer-beta.html"


class _Resp:
    def __init__(self, status: int, body=None, headers=None, content: bytes = b""):
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self.content = content

    def json(self):
        return self._body


@pytest.fixture
def client():
    user = type("U", (), {
        "authz_id": "alice@example.com", "id": "sub-alice", "email": "alice@example.com",
        "roles": [], "persona": None, "entitled_domains": [], "is_authenticated": True,
    })()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user
    with TestClient(gateway.app) as c:
        yield c
    gateway.app.dependency_overrides.clear()


@pytest.fixture
def stub_engine(monkeypatch):
    """Records what the BFF sends to engine-cost and lets a test control what it returns.
    Defaults to a normal 200 success/artifact so a test only sets `calls["_post_resp"]` /
    `calls["_get_resp"]` when it needs a different shape."""
    calls: dict = {"post": None, "get": None}

    class _Client:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

        async def post(self, url, json=None, headers=None, **k):
            calls["post"] = {"url": url, "json": json, "headers": headers}
            return calls.get("_post_resp") or _Resp(200, {
                "artifact_sha256": GOOD_SHA,
                "artifact_filename": ALPHA_HTML,
                "artifact_bytes": 4096,
                "algorithm_sha": "deadbeef",
                "lots_disclosed": [1, 2, 3],
                "sections": ["cost_lot_breakdown"],
            })

        async def get(self, url, headers=None, **k):
            calls["get"] = {"url": url, "headers": headers}
            return calls.get("_get_resp") or _Resp(
                200, content=b"<html>ok</html>", headers={"content-type": "text/html"})

    monkeypatch.setattr(gateway.httpx, "AsyncClient", _Client)
    return calls


# ─────────────────────────────────────────────────────────────────────────────
# POST /export/package
# ─────────────────────────────────────────────────────────────────────────────

def test_missing_recipient_scope_refuses_with_alices_own_options(client, stub_engine):
    r = client.post("/export/package", json={"answers": []})
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail["reason"] == "recipient_required"
    assert detail["options"] == [
        {"value": "notional-customer-alpha", "label": "notional-customer-alpha"}
    ], "alice reads alpha only"
    assert stub_engine["post"] is None


def test_recipient_alice_may_not_export_to_refuses_before_answer_lookup(
    client, stub_engine, monkeypatch,
):
    called = {"resolve": False}

    def _resolve(ids, user_id):
        called["resolve"] = True
        return []

    monkeypatch.setattr(gateway, "_resolve_export_answers", _resolve)
    r = client.post("/export/package", json={
        "recipient_scope": "notional-customer-beta",
        "answers": [{"artifact_id": "a1"}],
    })
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["reason"] == "not_a_recipient_you_may_export_to"
    assert r.json()["detail"]["recipient_scope"] == "notional-customer-beta"
    assert stub_engine["post"] is None
    assert called["resolve"] is False, "an unentitled recipient must never reach answer lookup"


def test_unknown_answer_id_refuses_before_the_engine(client, stub_engine, monkeypatch):
    def _resolve(ids, user_id):
        raise gateway.HTTPException(
            status_code=404, detail={"reason": "answer_not_found", "artifact_id": ids[0]})

    monkeypatch.setattr(gateway, "_resolve_export_answers", _resolve)
    r = client.post("/export/package", json={
        "recipient_scope": "notional-customer-alpha",
        "answers": [{"artifact_id": "missing-1"}],
    })
    assert r.status_code == 404, r.text
    assert r.json()["detail"]["reason"] == "answer_not_found"
    assert stub_engine["post"] is None


def test_happy_path_builds_canvas_and_forwards_the_callers_own_bearer(
    client, stub_engine, monkeypatch,
):
    monkeypatch.setattr(
        gateway, "_resolve_export_answers",
        lambda ids, user_id: [
            {"id": ids[0], "verb_iri": "mesh#Foo", "subject_instance_id": "inst-1"},
            {"id": ids[1], "verb_iri": "mesh#Bar", "subject_instance_id": "inst-2"},
        ],
    )
    r = client.post(
        "/export/package",
        json={"recipient_scope": "notional-customer-alpha",
              "answers": [{"artifact_id": "a1"}, {"artifact_id": "a2"}]},
        headers={"Authorization": f"Bearer {ALICE_TOKEN}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "exists"
    assert body["export_id"] == GOOD_SHA
    assert body["artifact_uri"] == f"/export/package/artifact/{ALPHA_HTML}"
    assert "iagent-engine-cost" not in body["artifact_uri"]
    assert "http" not in body["artifact_uri"]

    post = stub_engine["post"]
    assert post is not None
    assert post["url"].endswith("/measure/package_export")
    assert post["headers"]["Authorization"] == f"Bearer {ALICE_TOKEN}"
    assert post["json"]["params"]["recipient_scope"] == "notional-customer-alpha"
    canvas = post["json"]["params"]["canvas"]
    assert [a["id"] for a in canvas["answers"]] == ["a1", "a2"]
    assert canvas["answers"][0]["verb_iri"] == "mesh#Foo"
    assert canvas["answers"][0]["subject_instance_id"] == "inst-1"
    assert canvas["answers"][1]["verb_iri"] == "mesh#Bar"
    assert canvas["answers"][1]["subject_instance_id"] == "inst-2"


def test_empty_answers_omits_the_canvas_key_entirely(client, stub_engine):
    r = client.post("/export/package",
                    json={"recipient_scope": "notional-customer-alpha", "answers": []})
    assert r.status_code == 200, r.text
    assert "canvas" not in stub_engine["post"]["json"]["params"]


def test_engine_refusal_passes_through_as_a_failed_export(client, stub_engine):
    stub_engine["_post_resp"] = _Resp(200, {
        "refused": True, "outcome": "unentitled", "reason": "not an entitled recipient",
    })
    r = client.post("/export/package",
                    json={"recipient_scope": "notional-customer-alpha", "answers": []})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "failed"
    assert body["export_id"] is None
    assert body["reason"] == "not an entitled recipient"
    assert body["outcome"] == "unentitled"
    assert body["recipient_scope"] == "notional-customer-alpha"


def test_malformed_sha_reports_a_failed_export(client, stub_engine):
    stub_engine["_post_resp"] = _Resp(200, {
        "artifact_sha256": "abc", "artifact_filename": ALPHA_HTML,
    })
    r = client.post("/export/package",
                    json={"recipient_scope": "notional-customer-alpha", "answers": []})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "failed"
    assert body["export_id"] is None


def test_engine_unreachable_on_production_is_502(client, monkeypatch):
    class _Boom:
        def __init__(self, *a, **k): ...
        async def __aenter__(self):
            raise RuntimeError("no route to host")
        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(gateway.httpx, "AsyncClient", _Boom)
    r = client.post("/export/package",
                    json={"recipient_scope": "notional-customer-alpha", "answers": []})
    assert r.status_code == 502, r.text
    assert r.json()["detail"]["error"] == "cost_engine_unreachable"


# ─────────────────────────────────────────────────────────────────────────────
# GET /export/package/artifact/{filename}
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("filename", ["..%2Fetc%2Fpasswd", "cost-validation-gamma.html"])
def test_artifact_outside_the_closed_set_is_404(client, stub_engine, filename):
    r = client.get(f"/export/package/artifact/{filename}")
    assert r.status_code == 404, r.text
    assert stub_engine["get"] is None


def test_artifact_betas_file_for_alice_is_403(client, stub_engine):
    r = client.get(f"/export/package/artifact/{BETA_HTML}")
    assert r.status_code == 403, r.text
    assert stub_engine["get"] is None


def test_artifact_alphas_file_streams_bytes_and_forwards_the_bearer(client, stub_engine):
    stub_engine["_get_resp"] = _Resp(
        200, content=b"<html>alpha package</html>", headers={"content-type": "text/html"})
    r = client.get(f"/export/package/artifact/{ALPHA_HTML}",
                   headers={"Authorization": f"Bearer {ALICE_TOKEN}"})
    assert r.status_code == 200, r.text
    assert r.content == b"<html>alpha package</html>"
    assert r.headers["content-type"].startswith("text/html")
    assert f'attachment; filename="{ALPHA_HTML}"' in r.headers["content-disposition"]

    get_call = stub_engine["get"]
    assert get_call is not None
    assert get_call["url"].endswith(f"/artifact/{ALPHA_HTML}")
    assert get_call["headers"]["Authorization"] == f"Bearer {ALICE_TOKEN}"


def test_artifact_engine_404_is_forwarded_verbatim(client, stub_engine):
    stub_engine["_get_resp"] = _Resp(404, {
        "detail": "this deployment holds no artifacts: the package builder and the pinned "
                  "runtime live in the repository checkout and are not in this image",
    })
    r = client.get(f"/export/package/artifact/{ALPHA_HTML}")
    assert r.status_code == 404, r.text
    assert r.json()["detail"] == (
        "this deployment holds no artifacts: the package builder and the pinned runtime "
        "live in the repository checkout and are not in this image"
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /export/package/recipients
# ─────────────────────────────────────────────────────────────────────────────

def test_recipients_route_lists_only_what_alice_reads(client):
    r = client.get("/export/package/recipients")
    assert r.status_code == 200, r.text
    assert r.json()["recipients"] == [
        {"value": "notional-customer-alpha", "label": "notional-customer-alpha"}
    ]


# ─────────────────────────────────────────────────────────────────────────────
# seed.artifact_filenames / scope_of_artifact — the one naming rule
# ─────────────────────────────────────────────────────────────────────────────

def test_seed_artifact_filenames_round_trips_through_scope_of_artifact():
    from agent_fleet.cost_agent import seed

    for scope in seed.RECIPIENT_SCOPES:
        for filename in seed.artifact_filenames(scope):
            assert seed.scope_of_artifact(filename) == scope


def test_producible_artifact_names_is_the_union_of_artifact_filenames():
    from agent_fleet.cost_agent import seed
    from agent_fleet.cost_agent.main import _producible_artifact_names

    expected = set()
    for scope in seed.RECIPIENT_SCOPES:
        expected.update(seed.artifact_filenames(scope))
    assert _producible_artifact_names() == expected


# ─────────────────────────────────────────────────────────────────────────────
# A CANVAS OF ALL CARDS, end to end across the join
# ─────────────────────────────────────────────────────────────────────────────

def test_a_canvas_of_every_cost_card_reaches_the_engine_whole_and_discloses_every_section(
    client, stub_engine, monkeypatch,
):
    """The gateway forwards ALL the canvas's answers, in order, and the engine's own
    `canvas.resolve` reads exactly that forwarded canvas into every page section and every
    lot the recipient is entitled to. The two halves are each tested alone elsewhere; the
    JOIN (what one emits is what the other accepts) is asserted only here.

    The verbs are derived from the engine's EXPORTABLE table, not typed, so a ninth card added
    there is a ninth answer this test sends."""
    from agent_fleet.cost_agent import canvas as C
    from agent_fleet.cost_agent.seed import lots_for_recipient

    scope = "notional-customer-alpha"
    verbs = list(C.EXPORTABLE)
    lots = list(lots_for_recipient(scope))

    def _resolved(ids, user_id):
        out = []
        for i, (aid, verb) in enumerate(zip(ids, verbs)):
            spans = C.EXPORTABLE[verb]["spans"]
            out.append({"id": aid, "verb_iri": f"mesh:{verb}",
                        "subject_instance_id": str(lots[i % len(lots)]) if spans == "lot" else None})
        return out

    monkeypatch.setattr(gateway, "_resolve_export_answers", _resolved)
    ids = [f"card-{i}" for i in range(len(verbs))]
    r = client.post("/export/package", json={
        "recipient_scope": scope, "answers": [{"artifact_id": i} for i in ids]})
    assert r.status_code == 200, r.text

    sent = stub_engine["post"]["json"]["params"]["canvas"]
    assert [a["id"] for a in sent["answers"]] == ids        # none dropped, order kept
    composed = C.resolve(sent, recipient_scope=scope, entitled_lots=lots)
    assert composed["sections"] == C.SECTIONS               # every card's section is on the page
    assert composed["lots"] == tuple(lots)
    assert composed["answers"] == ids
