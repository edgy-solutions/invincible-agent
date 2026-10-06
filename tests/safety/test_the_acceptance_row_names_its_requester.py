"""THE ACCEPTANCE ROW NAMES ITS REQUESTER — the person whose turn's answer carried the review_request.

RULED 2026-10-05: `requested_by` on the acceptance row is that person's authz_id, passed from the
answer's envelope by the consumer, and a row with no requester is refused, not registered.

Measured before the ruling, on HAZ-1003's `~1` row: `requested_by` was `""`. Three layers each
passed the blank on. The consumer posted no identity. The `acceptance` step declares no
`requested_by`, so the runner fell back to an identity built from nothing. And the register
model and the NOT NULL column both accepted `""`. The case could name the turn that opened it
only by matching log timestamps.

The path this file seals, one arm per hop:

    stream `user_email` (CARRIES authz_id) -> envelope `produced_for.authz_id`      [wiring, AST]
    envelope -> consumer -> facts `authz_id`                     [run path, direct path, behaviour]
    facts `authz_id` -> the case's registered row `requested_by`         [real case runner]
    no requester -> refused by the builder, the store and the BFF's register        [behaviour]

Run: uv run --frozen pytest tests/safety/test_the_acceptance_row_names_its_requester.py -v
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import iagent.gateway as gw  # noqa: E402
from iagent import human_tasks  # noqa: E402
from iagent_pure import acceptance_request as ar  # noqa: E402

_GATEWAY_SRC = _SRC / "iagent" / "gateway.py"
_HAZARD = "HAZ-1003"
_REQUESTER = "requester@example.org"
_BLANKS = ["", "   ", None]


@pytest.fixture
def draft():
    """The REAL engine body: the review_request is the producer's, not a hand-written block."""
    from agent_fleet.safety_agent import matrix, measures
    matrix.reset_cache()
    try:
        yield measures.draft_risk_assessment(hazard_id=_HAZARD)
    finally:
        matrix.reset_cache()


@pytest.fixture
def rr(draft):
    got = ar.review_request_of(draft)
    assert got, f"FIXTURE VOID: the {_HAZARD} draft asks for no review"
    return got


# ── 1. THE BUILDER: the requester rides the facts under the runner's identity key ──────────────

def test_the_requester_rides_the_facts_as_authz_id_and_the_drafter_keeps_its_own_fact(rr):
    facts = ar.acceptance_trigger(rr, authz_id=f"  {_REQUESTER} ")
    assert facts.get("authz_id") == _REQUESTER, facts
    # The review_request's own `requested_by` names the engine that DRAFTED. It stays a separate
    # fact; the ruling is about the row, and the row reads `authz_id`.
    assert facts["requested_by"] == str(rr.get("requested_by") or ""), facts
    assert facts["requested_by"] != _REQUESTER


@pytest.mark.parametrize("blank", _BLANKS, ids=["empty", "whitespace", "none"])
def test_a_trigger_with_no_requester_is_refused(rr, blank):
    with pytest.raises(ar.AcceptanceRequestError, match="no requester"):
        ar.acceptance_trigger(rr, authz_id=blank)


# ── 2. THE CONSUMER: it passes the ENVELOPE's person, and refuses to open without one ──────────

class _Client:
    """`httpx.AsyncClient` for both the Restate ingress and Engine F's render. Records every POST."""

    def __init__(self, payload=None):
        self.posts, self.payload = [], payload or {}

    def __call__(self, *a, **k):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, **kw):
        self.posts.append({"url": url, "json": json})
        return self

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload

    @property
    def headers(self):
        return {}

    def runner_posts(self):
        return [p for p in self.posts if "/WorkflowRunner/" in p["url"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("who", [_REQUESTER, "someone-else@example.org"])
async def test_the_consumer_passes_the_envelopes_person(monkeypatch, rr, who):
    """Two people, two facts: the value comes FROM the envelope, not from a constant."""
    fake = _Client()
    monkeypatch.setattr(gw.httpx, "AsyncClient", fake)
    bundle = {"id": "urn:li:answerArtifact:t", "resolved_intent": {},
              "produced_for": {"user_id": "sub-123", "authz_id": who}}
    err = await gw._open_safety_acceptance(bundle, rr, path="run", stage_kind="x")
    assert err is None, err
    posts = fake.runner_posts()
    assert len(posts) == 1, posts
    post = posts[0]
    assert post["json"]["facts"].get("authz_id") == who, post["json"]
    # NOT the sub: `user_id` names nobody Topaz knows.
    assert post["json"]["facts"].get("authz_id") != "sub-123"


@pytest.mark.asyncio
@pytest.mark.parametrize("envelope", [
    {"user_id": "sub-123"},
    {"user_id": "sub-123", "authz_id": ""},
    {"user_id": "sub-123", "authz_id": "   "},
    None,
], ids=["absent", "empty", "whitespace", "no-produced_for"])
async def test_an_envelope_with_no_person_opens_no_case_and_says_so(monkeypatch, rr, envelope):
    fake = _Client()
    monkeypatch.setattr(gw.httpx, "AsyncClient", fake)
    bundle = {"id": "urn:li:answerArtifact:t", "resolved_intent": {}}
    if envelope is not None:
        bundle["produced_for"] = envelope
    err = await gw._open_safety_acceptance(bundle, rr, path="run", stage_kind="x")
    assert fake.runner_posts() == [], "a case was opened with no requester"
    assert err and "acceptance_not_opened" in err, err
    rec = bundle["resolved_intent"]["acceptance_not_opened"]
    assert rec["exception"] == "AcceptanceRequestError" and "no requester" in rec["message"], rec
    assert "acceptance_dispatched" not in bundle["resolved_intent"]


def _direct():
    from tests.routing import test_the_direct_path_stream_actually_runs as dp
    return dp


@pytest.mark.asyncio
async def test_the_direct_path_carries_the_envelopes_person_into_the_case(monkeypatch, draft):
    dp = _direct()
    fake = _Client(payload=dp._PAYLOAD)
    monkeypatch.setattr(gw.httpx, "AsyncClient", fake)
    bundle = dp._bundle()
    bundle["produced_for"]["authz_id"] = _REQUESTER
    async for _ in gw._stream_direct_outcome(
        outcome=dp._outcome(engine_response=draft), bundle=bundle, session_id="sess-1",
        frontend_id="cortex-ui-desktop", user_persona="SAFETY_ENGINEER",
    ):
        pass
    posts = fake.runner_posts()
    assert len(posts) == 1, posts
    post = posts[0]
    assert post["json"]["facts"].get("authz_id") == _REQUESTER, post["json"]
    assert bundle["resolved_intent"]["acceptance_dispatched"][0]["path"] == "direct"


@pytest.mark.asyncio
async def test_the_direct_path_with_no_person_opens_no_case_and_the_turn_shows_it(monkeypatch, draft):
    dp = _direct()
    fake = _Client(payload=dp._PAYLOAD)
    monkeypatch.setattr(gw.httpx, "AsyncClient", fake)
    bundle = dp._bundle()  # produced_for carries a sub and no authz_id
    events = [ev async for ev in gw._stream_direct_outcome(
        outcome=dp._outcome(engine_response=draft), bundle=bundle, session_id="sess-1",
        frontend_id="cortex-ui-desktop", user_persona="SAFETY_ENGINEER",
    )]
    assert fake.runner_posts() == []
    assert bundle["resolved_intent"]["acceptance_not_opened"]["where"] == "direct/review_request_consumer"
    assert any("acceptance_not_opened" in ev for ev in events)


# ── 3. THE WIRING: the stream's authz_id reaches the envelope both consumers read ──────────────

def _tree():
    return ast.parse(_GATEWAY_SRC.read_text(encoding="utf-8"))


def _fn(tree, name):
    hits = [n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
    assert len(hits) == 1, (name, len(hits))
    return hits[0]


def _names(node):
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def test_the_envelope_names_the_turns_person_from_the_streams_authz_id():
    inner = _fn(_tree(), "_generate_dagster_stream_inner")
    produced_for = [v for d in ast.walk(inner) if isinstance(d, ast.Dict)
                    for k, v in zip(d.keys, d.values)
                    if isinstance(k, ast.Constant) and k.value == "produced_for"]
    assert len(produced_for) == 1, len(produced_for)
    pf = produced_for[0]
    assert isinstance(pf, ast.Dict)
    vals = {k.value: v for k, v in zip(pf.keys, pf.values) if isinstance(k, ast.Constant)}
    assert "authz_id" in vals, sorted(vals)
    assert "user_email" in _names(vals["authz_id"]), ast.unparse(vals["authz_id"])
    assert "user_id" not in _names(vals["authz_id"]), "the sub names nobody Topaz knows"


def test_the_stream_is_handed_the_callers_authz_id_as_user_email():
    calls = [c for c in ast.walk(_tree()) if isinstance(c, ast.Call)
             and isinstance(c.func, ast.Name) and c.func.id == "generate_dagster_stream"]
    assert calls, "no caller of generate_dagster_stream"
    for c in calls:
        kw = {k.arg: ast.unparse(k.value) for k in c.keywords}
        assert kw.get("user_email") == "current_user.authz_id", kw


def test_both_consumers_read_the_turns_own_envelope():
    """The run path hands `_artifact_bundle` positionally, the direct path by keyword."""
    tree = _tree()
    run = [c for c in ast.walk(tree) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
           and c.func.id == "_open_acceptances_from_run"]
    assert [ast.unparse(c.args[1]) for c in run] == ["_artifact_bundle"], [ast.unparse(c) for c in run]
    direct = [c for c in ast.walk(tree) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
              and c.func.id == "_stream_direct_outcome"]
    assert [{k.arg: ast.unparse(k.value) for k in c.keywords}.get("bundle") for c in direct] \
        == ["_artifact_bundle"]
    opener = _fn(tree, "_open_safety_acceptance")
    builds = [c for c in ast.walk(opener) if isinstance(c, ast.Call)
              and ast.unparse(c.func) == "acceptance_request.acceptance_trigger"]
    assert len(builds) == 1
    kw = {k.arg: ast.unparse(k.value) for k in builds[0].keywords}
    assert "bundle" in kw.get("authz_id", "") and "produced_for" in kw["authz_id"], kw


# ── 4. THE CASE RUNNER: the facts' authz_id IS the registered row's requested_by ───────────────

@pytest.fixture
def rows(monkeypatch):
    from tests.safety.test_safety_acceptance_runs_as_a_case import main
    got: list = []
    monkeypatch.setattr(main, "_register_human_task",
                        lambda wf, task, kind="workflow_ack": got.append(
                            (kind, task["requested_by"])) or {})
    for k in ("CASE_TRIGGER_DIR", "DECISION_TABLE_DIR", "WORKFLOW_DEFINITIONS_DIR"):
        monkeypatch.delenv(k, raising=False)
    return got


@pytest.mark.asyncio
@pytest.mark.parametrize("who", [_REQUESTER, "someone-else@example.org"])
async def test_every_row_the_case_registers_names_the_requester(rows, who):
    """High chains concurrence -> acceptance: two rows, both the requester's. A second person
    gives a second value, so the row is bound to the fact rather than agreeing with it."""
    from tests.safety.test_safety_acceptance_runs_as_a_case import _run
    rr = {"kind": "risk_acceptance_high", "subject_ref": "HAZ-9001", "requested_by": "engine-safety",
          "payload": {"hazard_id": "HAZ-9001", "risk_level": "High", "risk_level_slug": "high"}}
    out, _case = await _run(ar.acceptance_trigger(rr, authz_id=who),
                            [("concurrence", "concurred"), ("acceptance", "accepted")])
    assert out["terminal"] == "risk_accepted", out
    assert rows == [("risk_acceptance_concurrence_high", who), ("risk_acceptance_high", who)], rows


# ── 5. THE STORE AND THE BFF: a row with no requester is refused, not registered ───────────────

def _no_db():
    raise AssertionError("a refused row reached the database")


@pytest.mark.parametrize("blank", _BLANKS, ids=["empty", "whitespace", "none"])
def test_the_store_refuses_a_row_with_no_requester_before_anything_else(monkeypatch, blank):
    resolved: list = []
    monkeypatch.setattr(human_tasks, "_resolve_audience_actors",
                        lambda aud: resolved.append(aud) or ["bob"])
    monkeypatch.setattr(human_tasks, "_pg_connect",
                        _no_db)
    with pytest.raises(human_tasks.NoRequester):
        human_tasks.register_task(kind="workflow_ack", task_id="t", audience="aud:x",
                                  title="t", summary="s", requested_by=blank)
    assert resolved == [], "the requester check ran after the audience was resolved"


def test_control_a_named_requester_passes_the_check(monkeypatch):
    """Same call, one difference: past the requester check, the next refusal is the audience's."""
    monkeypatch.setattr(human_tasks, "_resolve_audience_actors", lambda aud: [])
    with pytest.raises(human_tasks.NoEntitledRecipients):
        human_tasks.register_task(kind="workflow_ack", task_id="t", audience="aud:x",
                                  title="t", summary="s", requested_by=_REQUESTER)


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setattr(human_tasks, "_resolve_audience_actors", lambda aud: [])
    user = type("U", (), {"authz_id": "svc:case-runner", "sub": "svc", "email": "",
                          "persona": None, "entitled_domains": [], "is_authenticated": True})()
    gw.app.dependency_overrides[gw.get_current_user] = lambda: user
    try:
        with TestClient(gw.app, raise_server_exceptions=False) as c:
            yield c
    finally:
        gw.app.dependency_overrides.clear()


def _register(c, requested_by):
    return c.post("/internal/human_tasks/register", json={
        "kind": "risk_acceptance_medium", "task_id": "risk-acceptance-HAZ-1003-medium~1:acceptance",
        "audience": "risk_acceptance_medium:SUSTAINMENT", "title": "t", "summary": "s",
        "requested_by": requested_by, "workflow_id": "risk-acceptance-HAZ-1003-medium~1",
        "workflow_service": "WorkflowRunner", "promise_name": "acceptance",
    })


@pytest.mark.parametrize("blank", ["", "   "], ids=["empty", "whitespace"])
def test_the_register_route_refuses_a_blank_requester_with_a_terminal_422(client, blank):
    resp = _register(client, blank)
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["error"] == "no_requester", resp.text


def test_control_the_register_route_with_a_requester_reaches_the_audience(client):
    resp = _register(client, _REQUESTER)
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["error"] == "no_entitled_recipients", resp.text


def _no_requester_handlers(try_node):
    return [h for h in try_node.handlers
            if isinstance(h.type, ast.Attribute) and h.type.attr == "NoRequester"]


def _maps_to_no_requester_422(handler):
    raised = [n for n in ast.walk(handler) if isinstance(n, ast.Raise)]
    calls = [n.exc for n in raised if isinstance(n.exc, ast.Call)
             and getattr(n.exc.func, "id", None) == "HTTPException"]
    for c in calls:
        status = [k.value for k in c.keywords if k.arg == "status_code"]
        consts = {n.value for n in ast.walk(c) if isinstance(n, ast.Constant)}
        if status and getattr(status[0], "value", None) == 422 and "no_requester" in consts:
            return True
    return False


#: The in-process callers of `register_task` measured on 2026-10-05: the internal register, the
#: access request, the triage task and the ingest promotion. A RATCHET, not a census: a caller
#: deleted shrinks the population this arm walks, and that should be a decision someone records.
_REGISTER_CALLERS_FLOOR = 4


def test_every_bff_register_call_maps_the_refusal_to_a_terminal_422():
    """Derived from the calls, not listed: every `human_tasks.register_task(...)` in the BFF sits
    inside a `try` whose `NoRequester` handler raises HTTPException(422, no_requester). Without
    one the refusal escapes as a 500, which a case runner retries instead of failing."""
    tree = _tree()
    parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and n.func.attr == "register_task"
             and getattr(n.func.value, "id", None) == "human_tasks"]
    assert len(calls) >= _REGISTER_CALLERS_FLOOR, (
        f"{len(calls)} register_task calls in the BFF, floor {_REGISTER_CALLERS_FLOOR}")
    unguarded = []
    for call in calls:
        node, ok = call, False
        while node in parents:
            node = parents[node]
            if isinstance(node, ast.Try) and any(
                    _maps_to_no_requester_422(h) for h in _no_requester_handlers(node)):
                ok = True
                break
        if not ok:
            unguarded.append(call.lineno)
    assert not unguarded, f"register_task calls with no NoRequester -> 422 handler: gateway.py:{unguarded}"
