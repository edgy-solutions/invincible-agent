"""A restricted content kind is dropped only by its grantees (2026-10-28 ruling: pcn and pdn are
droppable by the alert-processors group only).

A kind K is GATED iff the Topaz object `capability:can_drop:K` EXISTS; a gated kind needs
`can_invoke(can_drop:K)` for the DROPPER OF RECORD (the row's `on_behalf_of`). Every site that sets
a row's kind makes the one check (`gateway._can_drop_or_refuse`): POST /ingest, POST /ingest/events,
POST /ingest/{id}/title_leaf, POST /ingest/{id}/leaf, and the BFF leaf backstop. `GET /me/entitlements`
reports `droppable_kinds`.

The doubles sit at the `human_tasks` boundary (`capability_object_exists`, `check_can_invoke`) except
the a4/a5 arms, which drive the real `capability_object_exists` through an httpx transport: the control
for "False means OPEN" is that a failed read is a 503, never an accept.

Run:  uv run python -m pytest tests/security/test_a_restricted_kind_is_dropped_only_by_its_grantees.py -q
"""
from __future__ import annotations

import asyncio
import re
import types
from pathlib import Path

import pytest

httpx = pytest.importorskip("httpx")
fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import content_kinds as ck  # noqa: E402
from src.iagent import gateway  # noqa: E402
from src.iagent import human_tasks as ht  # noqa: E402
from src.iagent import ingest_status as ist  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
JOB = ROOT / "helm" / "invincible-agent" / "templates" / "task-grant-sync-job.yaml"

GRANTED = "alice@example.com"
NOT_GRANTED = "bob@example.com"
GATED = {"can_drop:pcn", "can_drop:pdn"}
POLICY_ID = "capability_grants:can_drop:pcn"
MISSING = "can_invoke(can_drop:pcn)"
ID = "sha256:" + "a" * 64


def _reg(kind, branch="document", domain="maintenance", seeds=None):
    return types.SimpleNamespace(kind=kind, branch=branch, domain=domain, seeds_workflow=seeds,
                                 identity_field="event_id" if branch == "event" else None,
                                 passes=("p",))


_REGISTRY = (_reg("pdf", domain=None), _reg("pcn"), _reg("pdn"), _reg("work-instruction"),
             _reg("fault-event", branch="event", seeds="no-such-trigger"))


def _user(authz):
    return types.SimpleNamespace(
        authz_id=authz, id=authz, sub=authz, email=authz, persona=None, entitled_domains=[],
        is_authenticated=True,
        entitlements=types.SimpleNamespace(cells=[], default=None, source="test"))


@pytest.fixture
def as_user():
    def _as(authz):
        gateway.app.dependency_overrides[gateway.get_current_user] = lambda: _user(authz)
        return TestClient(gateway.app, raise_server_exceptions=False)
    yield _as
    gateway.app.dependency_overrides.clear()


@pytest.fixture
def gate(monkeypatch):
    """Registry + the `human_tasks` boundary. `gate.gated` is the set of existing objects."""
    g = types.SimpleNamespace(gated=set(GATED), granted={GRANTED}, object_reads=[], invoke_reads=[])

    def _exists(cap):
        g.object_reads.append(cap)
        return cap in g.gated

    def _invoke(cap, who):
        g.invoke_reads.append((cap, who))
        return who in g.granted

    monkeypatch.setattr(ck, "registrations", lambda: _REGISTRY)
    monkeypatch.setattr(ck, "by_kind", lambda k: next((r for r in _REGISTRY if r.kind == k), None) if k else None)
    monkeypatch.setattr(ht, "capability_object_exists", _exists)
    monkeypatch.setattr(ht, "check_can_invoke", _invoke)
    return g


@pytest.fixture
def writes(monkeypatch):
    """Write doubles for POST /ingest: nothing real is touched. No gate doubles: the a4 arms drive
    the real object read."""
    r = types.SimpleNamespace(s3=[], recorded=[])

    class _S3:
        def put_object(self, **kw):
            r.s3.append(kw)

    monkeypatch.setattr(gateway, "_build_s3_client", lambda: _S3())
    monkeypatch.setattr(gateway, "_create_ingest_node", lambda **kw: None)
    monkeypatch.setattr(ist, "find_primary_by_sha", lambda sha: None)
    monkeypatch.setattr(ist, "record_received",
                        lambda **kw: r.recorded.append(kw) or {"id": kw["ingest_id"], "status": "received"})
    return r


@pytest.fixture
def rig(writes, gate):
    return writes


def _drop(client, who, kind="pcn", **extra):
    return client.post("/ingest", files={"file": ("f.pdf", b"%PDF-1.4 door bytes", "application/pdf")},
                       data={"kind": "pdf", "content_kind": kind, "on_behalf_of": who, **extra})


def _detail(resp) -> dict:
    return resp.json()["detail"]


# ---- a: POST /ingest ---------------------------------------------------------------------------

def test_a1_an_ungated_kind_is_accepted_for_anyone(as_user, gate, rig):
    gate.gated = set()                                   # no capability:can_drop:* object exists
    r = _drop(as_user(NOT_GRANTED), NOT_GRANTED)
    assert r.status_code == 200, r.text
    assert [x["content_kind"] for x in rig.recorded] == ["pcn"]
    assert gate.invoke_reads == []                       # an open kind asks no one


def test_a2_a_gated_kind_is_accepted_for_a_granted_dropper(as_user, gate, rig):
    r = _drop(as_user(GRANTED), GRANTED)
    assert r.status_code == 200, r.text
    assert gate.invoke_reads == [("can_drop:pcn", GRANTED)]
    assert len(rig.recorded) == 1


def test_a3_a_gated_kind_is_refused_403_for_a_dropper_not_granted_and_nothing_is_recorded(as_user, gate, rig):
    r = _drop(as_user(NOT_GRANTED), NOT_GRANTED)
    assert r.status_code == 403, r.text
    d = _detail(r)
    assert d["error"] == "not_entitled_to_drop"
    assert d["refusal"]["policy_id"] == POLICY_ID
    assert d["refusal"]["missing_binding"] == MISSING
    assert rig.recorded == [] and rig.s3 == []


def test_a3b_a_leaf_at_the_drop_is_the_effective_kind(as_user, gate, rig):
    """The composer sends `leaf=pcn` with content_kind `pdf`: the effective kind is the leaf."""
    r = _drop(as_user(NOT_GRANTED), NOT_GRANTED, kind="pdf", leaf="pcn")
    assert r.status_code == 403, r.text
    assert _detail(r)["refusal"]["missing_binding"] == MISSING
    assert rig.recorded == []


_REAL_CLIENT = httpx.Client


def _real_read(monkeypatch, handler):
    """Drive the REAL `capability_object_exists` through an httpx transport, with the object read
    below the `human_tasks` boundary (check_can_invoke stays doubled: granted)."""
    real = _REAL_CLIENT
    monkeypatch.setattr(ht, "_TOPAZ_DIRECTORY_URL", "http://topaz.test")
    monkeypatch.setattr(ht.httpx, "Client",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))


@pytest.mark.parametrize("failure", ["transport", "http500"])
def test_a4_a_failed_object_read_is_503_and_never_accepted(as_user, writes, monkeypatch, failure):
    rig = writes
    monkeypatch.setattr(ck, "registrations", lambda: _REGISTRY)
    monkeypatch.setattr(ck, "by_kind", lambda k: next((r for r in _REGISTRY if r.kind == k), None) if k else None)
    monkeypatch.setattr(ht, "check_can_invoke", lambda cap, who: True)   # even a granted dropper

    def handler(request):
        if failure == "transport":
            raise httpx.ConnectError("topaz is down", request=request)
        return httpx.Response(500, json={"error": "boom"})

    _real_read(monkeypatch, handler)
    r = _drop(as_user(GRANTED), GRANTED)
    assert r.status_code == 503, r.text
    assert _detail(r)["error"] == "authorization_unavailable"
    assert rig.recorded == [] and rig.s3 == []


def test_a4b_a_404_from_the_real_read_is_open_and_a_200_is_gated(as_user, writes, monkeypatch):
    """The two answers the real read distinguishes, so the 503 arm above is not a blanket."""
    monkeypatch.setattr(ck, "registrations", lambda: _REGISTRY)
    monkeypatch.setattr(ck, "by_kind", lambda k: next((r for r in _REGISTRY if r.kind == k), None) if k else None)
    seen = []
    monkeypatch.setattr(ht, "check_can_invoke", lambda cap, who: seen.append(cap) or False)
    _real_read(monkeypatch, lambda req: httpx.Response(404, json={}))
    assert _drop(as_user(NOT_GRANTED), NOT_GRANTED).status_code == 200
    assert seen == []
    _real_read(monkeypatch, lambda req: httpx.Response(200, json={"result": {}}))
    assert _drop(as_user(NOT_GRANTED), NOT_GRANTED).status_code == 403
    assert seen == ["can_drop:pcn"]


def test_a5_an_unset_directory_url_raises_instead_of_reading_open(monkeypatch):
    monkeypatch.setattr(ht, "_TOPAZ_DIRECTORY_URL", "")
    with pytest.raises((ht.AuthorizationUnconfigured, ht.AuthorizationUnavailable)):
        ht.capability_object_exists("can_drop:pcn")


# ---- b: POST /ingest/events --------------------------------------------------------------------

def _event(client, who):
    return client.post("/ingest/events", json={"content_kind": "fault-event", "on_behalf_of": who,
                                               "payload": {"event_id": "e1"}})


def test_b1_the_events_door_refuses_a_gated_event_kind_for_a_dropper_not_granted(as_user, gate, rig):
    gate.gated = {"can_drop:fault-event"}
    r = _event(as_user(NOT_GRANTED), NOT_GRANTED)
    assert r.status_code == 403, r.text
    assert _detail(r)["refusal"]["policy_id"] == "capability_grants:can_drop:fault-event"
    assert rig.recorded == []


def test_b2_an_ungated_event_kind_gets_past_the_gate(as_user, gate, rig):
    """Past the gate = neither the 403 nor an authorization 503. (The fixture's trigger is unknown,
    so the route stops later, at `trigger_unconfigured`: proof the check let it through.)"""
    gate.gated = set()
    r = _event(as_user(NOT_GRANTED), NOT_GRANTED)
    assert r.status_code != 403, r.text
    assert _detail(r).get("error") not in ("not_entitled_to_drop", "authorization_unavailable",
                                           "authorization_unconfigured")
    assert gate.invoke_reads == []


# ---- c / d / e: the row-level sites ------------------------------------------------------------

def _row(dropper, **kw):
    return {"id": ID, "kind": "pdf", "content_kind": "pdf", "status": "received",
            "on_behalf_of": dropper, "submitted_by": "svc:delegate", "leaf_source": None,
            "leaf_set_by": None, "run_id": None, **kw}


@pytest.fixture
def rows(monkeypatch, gate):
    """Doubles for the row writes. Records `set_leaf` and `hold_for_kind` calls."""
    s = types.SimpleNamespace(row=None, set_leaf=[], holds=[], events=[])

    monkeypatch.setattr(ist, "get_row", lambda i: dict(s.row) if s.row else None)
    monkeypatch.setattr(ist, "get_status_unscoped", lambda i: dict(s.row) if s.row else None)

    def _set_leaf(i, leaf, source, **kw):
        s.set_leaf.append((leaf, source, kw.get("set_by")))
        s.row = {**s.row, "content_kind": leaf, "leaf_source": source}
        return dict(s.row)

    def _hold(i, **kw):
        s.holds.append(kw)
        s.row = {**s.row, "status": ist.AWAITING_KIND}
        return True

    monkeypatch.setattr(ist, "set_leaf", _set_leaf)
    monkeypatch.setattr(ist, "hold_for_kind", _hold)

    async def _access(ingest_id, current_user, route):
        return dict(s.row), "dropped_by"

    async def _body(row, user):
        return {"id": row["id"], "content_kind": row["content_kind"]}

    monkeypatch.setattr(gateway, "_ingest_review_access", _access)
    monkeypatch.setattr(gateway, "_ingest_status_body", _body)
    monkeypatch.setattr(gateway, "_apply_leaf_to_sidecar", lambda row, leaf: True)
    monkeypatch.setattr(gateway, "_DOC_TOOLS_SERVICE_AUTHZ_ID", "svc:doc-tools")
    return s


def _title_leaf(client):
    return client.post(f"/ingest/{ID}/title_leaf",
                       json={"doc_type": "PCN", "doc_type_source": "title"})


def test_c1_title_leaf_for_a_dropper_not_granted_sets_no_leaf_holds_the_row_and_is_403(as_user, rows):
    rows.row = _row(NOT_GRANTED)
    r = _title_leaf(as_user("svc:doc-tools"))
    assert r.status_code == 403, r.text
    assert _detail(r)["error"] == "not_entitled_to_drop"
    assert rows.set_leaf == []                           # the leaf was NOT set
    assert len(rows.holds) == 1                          # the row waits for a kind
    assert rows.row["status"] == ist.AWAITING_KIND


def test_c2_title_leaf_for_a_granted_dropper_sets_the_leaf(as_user, rows):
    rows.row = _row(GRANTED)
    r = _title_leaf(as_user("svc:doc-tools"))
    assert r.status_code == 200, r.text
    assert rows.set_leaf == [("pcn", "title", "svc:doc-tools")]
    assert rows.holds == []


def test_d1_leaf_checks_the_rows_dropper_not_the_caller(as_user, rows):
    """The caller IS granted; the row's dropper is not. The check reads the dropper."""
    rows.row = _row(NOT_GRANTED)
    r = as_user(GRANTED).post(f"/ingest/{ID}/leaf", json={"leaf": "pcn"})
    assert r.status_code == 403, r.text
    assert _detail(r)["refusal"]["policy_id"] == POLICY_ID
    assert rows.set_leaf == []
    assert rows.row == _row(NOT_GRANTED)                 # unchanged


@pytest.mark.ingest_v1_unconformant(reason="_ingest_status_body is doubled to a stub dict")
def test_d2_leaf_for_a_granted_dropper_sets_the_leaf(as_user, rows):
    rows.row = _row(GRANTED)
    r = as_user(NOT_GRANTED).post(f"/ingest/{ID}/leaf", json={"leaf": "pcn"})   # the caller is NOT
    assert r.status_code == 200, r.text
    assert rows.set_leaf == [("pcn", "corrected", NOT_GRANTED)]


def _backstop(row):
    manifest = {"leaf": {"leaf": "pcn", "outcome": "title", "candidates": []}}
    return asyncio.run(gateway._apply_manifest_leaf_block(row, "k", manifest))


def test_e1_the_backstop_with_a_dropper_not_granted_sets_no_leaf_and_holds_the_row(rows, caplog):
    rows.row = _row(NOT_GRANTED, status="extracting")
    with caplog.at_level("WARNING"):
        decision, ok = _backstop(rows.row)
    assert rows.set_leaf == []
    assert len(rows.holds) == 1 and ok is True and decision == "awaiting_kind"
    assert any("can_drop" in m and ID in m and "pcn" in m and "not_entitled_to_drop" in m
               for m in caplog.messages)


def test_e1b_the_backstop_with_a_granted_dropper_sets_the_leaf(rows):
    rows.row = _row(GRANTED, status="extracting")
    decision, ok = _backstop(rows.row)
    assert ok is True and decision == "title:pcn"
    assert rows.set_leaf == [("pcn", "title", gateway._LEAF_BACKSTOP_ACTOR)]


def test_e2_the_backstop_with_topaz_unavailable_leaves_the_row_untouched(rows, gate, monkeypatch):
    rows.row = _row(NOT_GRANTED, status="extracting")
    before = dict(rows.row)

    def _down(cap):
        raise ht.AuthorizationUnavailable("ConnectError")

    monkeypatch.setattr(ht, "capability_object_exists", _down)
    decision, ok = _backstop(rows.row)
    assert ok is False
    assert rows.set_leaf == [] and rows.holds == [] and rows.row == before


# ---- f: GET /me/entitlements -------------------------------------------------------------------

def test_f1_droppable_kinds_lists_every_kind_for_a_granted_caller_and_omits_the_gated_for_another(as_user, gate):
    every = [r.kind for r in _REGISTRY]
    r = as_user(GRANTED).get("/me/entitlements")
    assert r.status_code == 200, r.text
    assert r.json()["droppable_kinds"] == every
    r = as_user(NOT_GRANTED).get("/me/entitlements")
    assert r.status_code == 200, r.text
    assert r.json()["droppable_kinds"] == [k for k in every if k not in ("pcn", "pdn")]


def test_f2_an_object_read_error_is_503_for_the_whole_response(as_user, gate, monkeypatch):
    def _down(cap):
        raise ht.AuthorizationUnavailable("ConnectError")

    monkeypatch.setattr(ht, "capability_object_exists", _down)
    r = as_user(GRANTED).get("/me/entitlements")
    assert r.status_code == 503, r.text
    assert "droppable_kinds" not in r.text


# ---- g: the Job leg ----------------------------------------------------------------------------

def test_g1_the_task_grant_sync_job_runs_capability_grant_sync_and_propagates_its_exit():
    text = JOB.read_text(encoding="utf-8")
    m = re.search(r"(?m)^(?P<i>\s+)python policy/sync/capability_grant_sync\.py\s*$", text)
    assert m, "the Job's command does not run policy/sync/capability_grant_sync.py"
    head, tail = text[:m.start()], text[m.end():]
    assert re.search(r"(?m)^\s+set -e\s*$", head), "the command is not under `set -e`"
    assert "set +e" not in head[head.rindex("set -e"):], "set -e is switched off before the leg"
    assert not re.match(r"[ \t]*(\|\||;)", tail), "the leg's exit is swallowed"

def test_h1_the_ungated_stub_is_opt_in_and_never_ambient():
    """The shared 'every kind is ungated' stub must stay explicit: not autouse anywhere, not in
    conftest.py, not used by this seal. An ambient stub would mask the door in every ingest test."""
    import ast

    name = "can_drop" + "_open"
    tests_dir = Path(__file__).resolve().parents[1]
    assert name not in (tests_dir / "conftest.py").read_text(encoding="utf-8")
    me = Path(__file__).resolve()
    own = me.read_text(encoding="utf-8")
    body = own[own.index("def test_h1_"):]
    assert name not in own.replace(body, ""), "the seal itself must run the real door, not the stub"
    ambient = []
    for path in tests_dir.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "capability_object_exists" not in text or "autouse" not in text:
            continue
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call) and any(
                    k.arg == "autouse" and isinstance(k.value, ast.Constant) and k.value.value is True
                    for k in dec.keywords
                ):
                    if "capability_object_exists" in (ast.get_source_segment(text, node) or ""):
                        ambient.append(f"{path.name}:{node.lineno}")
    assert not ambient, f"an autouse fixture patches capability_object_exists: {ambient}"
