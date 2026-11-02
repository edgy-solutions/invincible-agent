"""engine-fin's verbs (`/measure/{fn}`, `/package_export`) refuse a program the caller cannot view.

Architect ruling 2026-10-27: the verbs check program visibility by the same filter as
enumerate/resolve, deny by default, 403 with the refusal envelope. ONE predicate (`_can_view`)
serves four routes; the membership check is replaced at the name `main` uses
(`engine.can_view_program`) with a recording double that ALSO admits `svc:supervisor`, so the
service arms prove the ENGINE refuses even when Topaz would say yes.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "src", REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from agent_fleet.finance_agent import main as engine  # noqa: E402
from agent_fleet.finance_agent import measures  # noqa: E402
from iagent.canvas_template import load_template, panel_dispatch  # noqa: E402

PROGRAM = "NP-MERIDIAN"
SCOPE = "program_office." + PROGRAM
ALICE = "alice@example.com"
BOB = "bob@example.com"
SVC = "svc:supervisor"
SHA64 = "sha256:" + "a" * 64

ENVELOPE = {
    "error": "program_not_visible",
    "refusal": {
        "policy_id": "program_members",
        "missing_binding": "can_view_program(program)",
        "candidates": [],
    },
    "message": "You are not a member of the program this request names.",
}


class Double:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []
        self.raises: Exception | None = None

    def __call__(self, program, caller_id, **kw):
        self.calls.append((program, caller_id))
        if self.raises is not None:
            raise self.raises
        return (program, caller_id) in {(PROGRAM, ALICE), (PROGRAM, SVC)}


@pytest.fixture
def double(monkeypatch):
    d = Double()
    monkeypatch.setattr(engine, "can_view_program", d)
    return d


@pytest.fixture
def measured(monkeypatch):
    """Record every `_measure_envelope` call; delegate to the real one."""
    calls: list[tuple[str, dict]] = []
    real = engine._measure_envelope

    def spy(fn, params):
        calls.append((fn, dict(params)))
        return real(fn, params)

    monkeypatch.setattr(engine, "_measure_envelope", spy)
    return calls


@pytest.fixture
def built(monkeypatch):
    """A stub builder that records; the package route needs no real duckdb/pyodide here."""
    out: list[dict] = []

    class _Builder:
        @staticmethod
        def build(**kw):
            out.append(kw)
            return {"manifest": {"panels": kw["panels"], "as_of": "2026-01-01",
                                 "recipient_scope": kw["recipient_scope"],
                                 "algorithm_sha": kw["sha"],
                                 "template_id": kw["template_id"],
                                 "template_hash": kw["template_hash"]},
                    "html_sha256": SHA64, "html_bytes": 1, "duckdb_sha256": SHA64}

    monkeypatch.setattr(engine, "_repo_root", lambda: REPO)
    monkeypatch.setitem(sys.modules, "build_fin_package", _Builder)
    monkeypatch.setattr("build_cost_package.algorithm_sha", lambda: "0" * 40)
    return out


@pytest.fixture
def client():
    with TestClient(engine.app) as c:
        yield c


def _params(fn, program=PROGRAM):
    p = {"program_id": program}
    if fn == "fin_eac_calculation":
        p["method"] = "CPI"
    return p


def _canvas(n=None):
    t = load_template("program_finance")
    panels = []
    for i in range(len(t.panels)):
        verb, _s, p = panel_dispatch(t, i, {"program": PROGRAM})
        panels.append({"panel": i, "verb": verb, "params": dict(p)})
    return {"template_id": "program_finance", "template_hash": "h",
            "panels": panels[:n] if n else panels}


def _pkg(client, user, scope=SCOPE, canvas=None, **kw):
    body = {"recipient_scope": scope, "canvas": canvas or _canvas(), **kw}
    if user is not None:
        body["user_email"] = user
    return client.post("/package_export", json=body)


def _assert_envelope(r):
    assert r.status_code == 403, r.text
    d = r.json()["detail"]
    assert d == ENVELOPE, d
    assert "grantable_by" not in d["refusal"], "the engine holds no grantor map"


def test_1_member_runs_every_verb_non_member_is_refused(double, measured, client):
    fns = sorted(measures.OUTPUT_URI)
    assert fns, "the verb table is empty"
    for fn in fns:
        r = client.post(f"/measure/{fn}", json={"params": _params(fn), "user_email": ALICE})
        assert r.status_code == 200, f"{fn}: {r.text[:200]}"
    assert [c[0] for c in measured] == fns
    measured.clear()
    for fn in fns:
        r = client.post(f"/measure/{fn}", json={"params": _params(fn), "user_email": BOB})
        _assert_envelope(r)
    assert measured == [], "a refused caller reached _measure_envelope"


def test_2_deny_by_default(double, measured, client):
    fn = "fin_burn_rate"

    def post(params, **kw):
        return client.post(f"/measure/{fn}", json={"params": params, **kw})

    _assert_envelope(post(_params(fn)))  # no user_email at all
    n = len(double.calls)
    _assert_envelope(post(_params(fn), user_email=SVC))
    assert len(double.calls) == n, "a service caller reached the membership double"
    n = len(double.calls)
    _assert_envelope(post({}, user_email=ALICE))  # program_id absent
    _assert_envelope(post({"program_id": 7}, user_email=ALICE))  # non-string
    _assert_envelope(post({"program_id": ""}, user_email=ALICE))
    # No lookup for a non-program: in production a non-string would reach Topaz and come back
    # a 503, not a 403.
    assert len(double.calls) == n, double.calls[n:]
    assert measured == []
    assert post(_params(fn), user_email=ALICE).status_code == 200  # control


def test_3_absent_and_ungranted_programs_read_alike(double, client):
    fn = "fin_burn_rate"
    a = client.post(f"/measure/{fn}", json={"params": _params(fn), "user_email": BOB})
    b = client.post(f"/measure/{fn}",
                    json={"params": _params(fn, "NP-DOES-NOT-EXIST"), "user_email": BOB})
    _assert_envelope(a)
    assert a.status_code == b.status_code and a.json() == b.json()
    assert a.content == b.content


def test_4_outage_is_a_503_on_both_routes(double, measured, built, client):
    double.raises = httpx.ConnectError("topaz down")
    r = client.post("/measure/fin_burn_rate",
                    json={"params": _params("fin_burn_rate"), "user_email": ALICE})
    assert r.status_code == 503 and "program membership check failed" in r.text
    r = _pkg(client, ALICE)
    assert r.status_code == 503 and "program membership check failed" in r.text
    assert measured == [] and built == []


def test_5_package_export(double, measured, built, client):
    r = _pkg(client, ALICE)
    assert r.status_code == 200, r.text
    assert len(built) == 1 and len(measured) == 6
    measured.clear()
    built.clear()
    _assert_envelope(_pkg(client, BOB))
    assert measured == [] and built == []
    # Refusal 1 still comes first, and asks nothing of the membership service.
    n = len(double.calls)
    r = _pkg(client, BOB, scope="program_office.NOPE")
    assert r.status_code == 403 and isinstance(r.json()["detail"], str), r.text
    assert len(double.calls) == n
    assert measured == [] and built == []


def test_6_one_check_per_package(double, built, client):
    r = _pkg(client, ALICE, canvas=_canvas(3))
    assert r.status_code == 200, r.text
    assert len(built[0]["panels"]) == 3
    assert double.calls == [(PROGRAM, ALICE)]


# ── the BFF half ─────────────────────────────────────────────────────────────
class _User:
    id = "a400f096-d252-49cc-9336-5f47a5b9e4cd"
    authz_id = "alice@example.com"
    email = "alice@example.com"


class _Req:
    headers = {"authorization": "Bearer t"}


class _Resp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def test_7_bff_relays_the_refusal(monkeypatch):
    import iagent.gateway as gw
    from iagent.authz.refusal import grantors

    sent: list[dict] = []
    envelope = json.loads(json.dumps(ENVELOPE))  # `json` is shadowed by post()'s kwarg

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None, headers=None):
            sent.append({"url": url, "json": json})
            return _Resp(403, {"detail": envelope})


    monkeypatch.setattr(gw.httpx, "AsyncClient", _Client)
    body = gw.ExportPackageRequest(template_id="program_finance",
                                   bindings={"program": PROGRAM})
    with pytest.raises(HTTPException) as ei:
        asyncio.run(gw.export_package(body, _Req(), _User()))
    assert len(sent) == 1 and sent[0]["url"].endswith("/package_export")
    assert sent[0]["json"]["user_email"] == _User.authz_id
    exc = ei.value
    assert exc.status_code == 403
    g = grantors()["program_members"]
    d = exc.detail
    assert d["refusal"]["grantable_by"] == f"{g.who}; {g.how}"
    assert d["refusal"]["policy_id"] == ENVELOPE["refusal"]["policy_id"]
    assert d["refusal"]["missing_binding"] == ENVELOPE["refusal"]["missing_binding"]
    assert d["error"] == ENVELOPE["error"] and d["message"] == ENVELOPE["message"]


# ── one predicate, four routes ───────────────────────────────────────────────
@pytest.mark.parametrize("route", ["enumerate", "resolve", "measure", "package_export"])
def test_8_svc_sees_nothing_on_every_route(route, double, built, client):
    if route == "enumerate":
        r = client.post("/enumerate_instances",
                        json={"class_uri": engine.FIN + "ControlAccount", "limit": 100,
                              "user_email": SVC})
        assert r.status_code == 200 and r.json()["members"] == []
    elif route == "resolve":
        r = client.post("/resolve_instance",
                        json={"identifier": engine.STATE.programs[0].name, "user_email": SVC})
        assert r.status_code == 200 and r.json()["candidates"] == []
    elif route == "measure":
        r = client.post("/measure/fin_burn_rate",
                        json={"params": _params("fin_burn_rate"), "user_email": SVC})
        _assert_envelope(r)
    else:
        _assert_envelope(_pkg(client, SVC))
        assert built == []
    assert double.calls == [], "a service caller reached the membership double"


# ── the caller is the bearer first ───────────────────────────────────────────
class _Caller:
    def __init__(self, authz_id):
        self.authz_id = authz_id


@pytest.fixture
def as_caller(monkeypatch):
    """Patch the engine's view of the caller, as tests/cost/test_the_export_round_trips.py does
    for cost's `/artifact` (line 64): what is under test is the decision, not the mint."""
    def _run(authz_id):
        monkeypatch.setattr(engine, "_current_caller",
                            lambda: _Caller(authz_id) if authz_id is not None else None)
    return _run


@pytest.mark.parametrize("route", ["measure", "package_export"])
@pytest.mark.parametrize("bearer, body, status", [
    (ALICE, None, 200),   # a user bearer is the caller; no body needed
    (BOB, None, 403),
    (SVC, ALICE, 200),    # a service bearer: the body is its delegation
    (BOB, ALICE, 403),    # a user bearer is never overridden by the body
])
def test_9_the_bearer_is_the_caller(route, bearer, body, status, double, built, as_caller, client):
    as_caller(bearer)
    if route == "measure":
        payload = {"params": _params("fin_burn_rate")}
        if body:
            payload["user_email"] = body
        r = client.post("/measure/fin_burn_rate", json=payload)
    else:
        r = _pkg(client, body)
    assert r.status_code == status, r.text
    if status == 403:
        _assert_envelope(r)
    expected = ALICE if status == 200 else BOB
    assert double.calls == [(PROGRAM, expected)], double.calls
