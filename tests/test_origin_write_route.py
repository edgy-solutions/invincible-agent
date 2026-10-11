"""POST /internal/origin/write (item B, 2026-10-03) -- the origin_record case's `written`
direct_call step's own transport. Harness mirrors tests/test_gateway_ingest_routes.py:
TestClient(gateway.app) + dependency_overrides[get_current_user]; `origin_writer.write_origin`
is faked so these are tests of the ROUTE's gate and translation, not of the graph write itself
(covered in tests/test_origin_writer.py).

WHAT THESE DEFEND (item B's named mutants, (b)/(c)/(e)):
  (b) the route accepts any caller -- only `svc:case-runner` may call this; every other caller
      gets 403 before `origin_writer.write_origin` is ever reached.
  (c) on_behalf_of not recorded -- the Initiator handed to `write_origin` carries the STEWARD's
      `approver_sub` from `approval_chain`, as a `kind: delegate` write, never the case
      runner's own identity standing in for the steward's.
  (e) the bound check skipped -- an `approval_chain` with no `role: steward` entry (or one with
      no `approver_sub`) is refused 422 before `write_origin` is ever reached.
Plus the two passthrough shapes the spec names explicitly: `written`/`write_refused` both
answer 200 (a refused write is a normal outcome, never an HTTP error).

Q2 (architect ruling 2026-10-10) -- a steward's accept on an `awaiting_origin` row IS the
attestation: a `written` origin files `document_promotion:<origin owner_domain>` and moves the
row to `review` (task first, status second); a filing refusal leaves the row where it was and
the response `written` with `promotion: {"filed": False, "error": ...}`. Arms (a)-(f) at the end.

Run: uv run --frozen pytest tests/test_origin_write_route.py -v
"""
from __future__ import annotations

import pytest

httpx = pytest.importorskip("httpx")
fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import content_kinds as ck  # noqa: E402
from src.iagent import gateway  # noqa: E402
from src.iagent import human_tasks as ht  # noqa: E402
from src.iagent import ingest_status as ist  # noqa: E402
from src.iagent import origin_writer  # noqa: E402

# the SAME workflow_definition module object `main`/the real executor validates with -- see
# tests/test_a_case_runs_from_trigger_to_terminal.py's own import for why (sys.path, not a
# package import: `agent_fleet/restate_analyst` is not itself a package).
from tests.test_a_case_runs_from_trigger_to_terminal import wd  # noqa: E402

BODY = {
    "artifact_id": "ART-9",
    "dropped_by": {"authz_id": "dropper@x"},
    "origin": {"owner_domain": "aviation", "program": "PRG-1",
               "obtained_via": "contract_deliverable"},
    "evidence": {"source": "contract", "citation": "CDRL A001 para 3"},
    "approval_chain": [
        {"step": 1, "role": "steward", "approver_sub": "steward@x", "decision": "approved"},
    ],
}


def _user(authz_id):
    return type("U", (), {"authz_id": authz_id, "id": authz_id, "sub": authz_id,
                          "email": None, "persona": None, "entitled_domains": [],
                          "is_authenticated": True})()


@pytest.fixture
def client():
    def _make(authz_id):
        gateway.app.dependency_overrides[gateway.get_current_user] = lambda: _user(authz_id)
        return TestClient(gateway.app)
    yield _make
    gateway.app.dependency_overrides.clear()


class _IngestFake:
    """In-memory stand-in for `ingest_status.get_row` / `update_status`, recording call order
    into one shared `events` list together with the human_tasks recorders."""

    def __init__(self):
        self.row = None
        self.events = []

    def get_row(self, ingest_id):
        self.events.append(("get_row", ingest_id))
        return self.row

    def update_status(self, ingest_id, status, **kw):
        self.events.append(("update_status", ingest_id, status))
        if self.row is not None:
            self.row["status"] = status


@pytest.fixture(autouse=True)
def ingest_fake(monkeypatch):
    fake = _IngestFake()
    monkeypatch.setattr(ist, "get_row", fake.get_row)
    monkeypatch.setattr(ist, "update_status", fake.update_status)
    monkeypatch.setattr(ht, "check_can_view_program", lambda program, who: False)
    return fake


class _Calls(list):
    """A list of captured `write_origin` calls that can also hold the canned result the fake
    returns -- so a test can flip to `write_refused` without a second fixture."""


@pytest.fixture
def fake_write_origin(monkeypatch):
    """Captures every write_origin call instead of touching Neo4j; returns `written` by
    default. A test that wants `write_refused` calls `.set_result(...)`."""
    calls = _Calls()
    result = {"status": "written", "reason": None}

    def _fake(resolution, *, graph_writer, initiator, dropper_is_program_member):
        calls.append({
            "resolution": resolution, "initiator": initiator,
            "dropper_is_program_member": dropper_is_program_member,
        })
        return result

    monkeypatch.setattr(origin_writer, "write_origin", _fake)

    def _set_result(status, reason=None):
        result["status"], result["reason"] = status, reason

    calls.set_result = _set_result
    return calls


# ── (b) THE CALLER GATE ─────────────────────────────────────────────────────────────────────

def test_A_NON_CASE_RUNNER_CALLER_IS_REFUSED_BEFORE_WRITE_ORIGIN_IS_REACHED(client, fake_write_origin):
    resp = client("alice@example.com").post("/internal/origin/write", json=BODY)
    assert resp.status_code == 403, resp.text
    assert fake_write_origin == [], fake_write_origin


def test_AN_UNAUTHENTICATED_CALLER_IS_ALSO_REFUSED(client, fake_write_origin):
    resp = client("").post("/internal/origin/write", json=BODY)
    assert resp.status_code == 403, resp.text
    assert fake_write_origin == [], fake_write_origin


def test_THE_CASE_RUNNERS_OWN_IDENTITY_PASSES_THE_GATE(client, fake_write_origin):
    resp = client("svc:case-runner").post("/internal/origin/write", json=BODY)
    assert resp.status_code == 200, resp.text
    assert len(fake_write_origin) == 1, fake_write_origin


# ── (c) on_behalf_of IS RECORDED ────────────────────────────────────────────────────────────

def test_ON_BEHALF_OF_IS_THE_STEWARDS_APPROVER_SUB_NOT_THE_CASE_RUNNERS_OWN(client, fake_write_origin):
    resp = client("svc:case-runner").post("/internal/origin/write", json=BODY)
    assert resp.status_code == 200, resp.text
    [call] = fake_write_origin
    initiator = call["initiator"]
    assert initiator.kind == "delegate", initiator
    assert initiator.subject == "svc:case-runner", initiator
    assert initiator.on_behalf_of == "steward@x", initiator


def test_ON_BEHALF_OF_TAKES_THE_LAST_STEWARD_ENTRY_WHEN_SEVERAL_EXIST(client, fake_write_origin):
    body = dict(BODY, approval_chain=[
        {"step": 1, "role": "steward", "approver_sub": "first@x", "decision": "approved"},
        {"step": 2, "role": "steward", "approver_sub": "second@x", "decision": "approved"},
    ])
    resp = client("svc:case-runner").post("/internal/origin/write", json=body)
    assert resp.status_code == 200, resp.text
    [call] = fake_write_origin
    assert call["initiator"].on_behalf_of == "second@x", call["initiator"]


# ── (e) THE BOUND CHECK ─────────────────────────────────────────────────────────────────────

def test_NO_STEWARD_ENTRY_IN_THE_APPROVAL_CHAIN_IS_REFUSED_422(client, fake_write_origin):
    body = dict(BODY, approval_chain=[
        {"step": 1, "role": "requester", "approver_sub": "someone@x", "decision": "approved"},
    ])
    resp = client("svc:case-runner").post("/internal/origin/write", json=body)
    assert resp.status_code == 422, resp.text
    assert fake_write_origin == [], fake_write_origin


def test_A_STEWARD_ENTRY_WITH_NO_APPROVER_SUB_IS_REFUSED_422(client, fake_write_origin):
    body = dict(BODY, approval_chain=[
        {"step": 1, "role": "steward", "approver_sub": "", "decision": "approved"},
    ])
    resp = client("svc:case-runner").post("/internal/origin/write", json=body)
    assert resp.status_code == 422, resp.text
    assert fake_write_origin == [], fake_write_origin


def test_AN_EMPTY_APPROVAL_CHAIN_IS_REFUSED_422(client, fake_write_origin):
    body = dict(BODY, approval_chain=[])
    resp = client("svc:case-runner").post("/internal/origin/write", json=body)
    assert resp.status_code == 422, resp.text
    assert fake_write_origin == [], fake_write_origin


# ── BOTH OUTCOMES ANSWER 200, NEVER AN HTTP ERROR ───────────────────────────────────────────

def test_A_WRITTEN_RESULT_ANSWERS_200(client, fake_write_origin):
    resp = client("svc:case-runner").post("/internal/origin/write", json=BODY)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"status": "written", "reason": None, "promotion": None}, resp.json()


def test_A_WRITE_REFUSED_RESULT_ALSO_ANSWERS_200_NOT_AN_HTTP_ERROR(client, fake_write_origin):
    fake_write_origin.set_result("write_refused", "dropper is not a program member")
    resp = client("svc:case-runner").post("/internal/origin/write", json=BODY)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "status": "write_refused", "reason": "dropper is not a program member",
        "promotion": None,
    }, resp.json()


# ── (d) THE ACCEPT STEP IS direct_call, NOT signal_await ────────────────────────────────────

def test_THE_WRITTEN_STEP_IS_A_GATED_direct_call_NOT_A_signal_await():
    [step] = [s for s in wd.get_workflow_definition("origin_record").steps if s.id == "written"]
    assert step.kind == "direct_call", step
    assert step.capability == "origin.write", step
    assert step.endpoint == "{origin_write_endpoint}", step
    assert set(step.extra_payload) == {
        "artifact_id", "dropped_by", "origin", "evidence", "approval_chain",
    }, step.extra_payload


# ── Q2 (2026-10-10): AN ACCEPTED ORIGIN ON AN awaiting_origin ROW FILES THE PROMOTION ───────

_HEX = "a" * 64
_INGEST_ID = "sha256:" + _HEX
_PREFIX = f"ingress-user/pdf/{_HEX}/"
_REF = f"{_PREFIX}generated/doc_pdf/doc-tools@61f74dc/manifest.json"


def _row(status="awaiting_origin", **over):
    row = {"id": _INGEST_ID, "status": status, "kind": "pdf", "content_kind": "pdf",
           "submitted_by": "alice@example.com", "on_behalf_of": "carol@example.com",
           "object_prefix": _PREFIX, "extraction_ref": _REF}
    row.update(over)
    return row


def _body(owner_domain="sustainment"):
    body = {**BODY, "artifact_id": _INGEST_ID}
    body["origin"] = {**BODY["origin"], "owner_domain": owner_domain}
    return body


@pytest.fixture
def filing(monkeypatch, ingest_fake):
    """A DELIBERATELY DOMAINLESS kind registration (so the old helper path would 422
    `no_declared_domain`), a valid manifest, and recorders for task_exists / register_task that
    share the ingest fake's event list (call order)."""
    reg = type("Reg", (), {"domain": None, "model_fields_set": frozenset({"domain"})})()
    monkeypatch.setattr(ck, "by_kind", lambda kind: reg)
    manifest = {"doc_id": "N-1", "filename": "doc.pdf", "source_key": _PREFIX + "doc.pdf",
                "pipeline_version": "doc-tools@61f74dc", "ingest_id": _INGEST_ID,
                "provenance": {"standing": "supervised", "ingest_id": _INGEST_ID}}
    monkeypatch.setattr(gateway, "_read_extraction_manifest", lambda key: manifest)
    state = type("F", (), {})()
    state.registered = []
    state.exists = False
    state.raises = None

    def _exists(task_id):
        return state.exists

    def _register(**kw):
        ingest_fake.events.append(("register_task", kw["task_id"]))
        if state.raises is not None:
            raise state.raises
        state.registered.append(kw)
        return {"task_id": kw["task_id"], "recipients": ["steward"]}

    monkeypatch.setattr(ht, "task_exists", _exists)
    monkeypatch.setattr(ht, "register_task", _register)
    state.ingest = ingest_fake
    return state


def _post(client, body):
    resp = client("svc:case-runner").post("/internal/origin/write", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_q2_a_AN_ACCEPTED_ORIGIN_FILES_THE_PROMOTION_THEN_MOVES_THE_ROW(
        client, fake_write_origin, filing):
    filing.ingest.row = _row()
    out = _post(client, _body("sustainment"))
    assert out["status"] == "written"
    assert out["promotion"] == {"filed": True, "task_id": f"document_promotion:{_INGEST_ID}",
                                "task_status": "FILED"}, out
    [kw] = filing.registered
    assert kw["kind"] == "document_promotion"
    assert kw["audience"] == "document_promotion:SUSTAINMENT"
    assert kw["payload"]["review_pool"] == "SUSTAINMENT"
    assert kw["payload"]["dropped_by"] == {"authz_id": "alice@example.com",
                                           "on_behalf_of": "carol@example.com"}
    assert filing.ingest.row["status"] == "review"
    names = [e[0] for e in filing.ingest.events if e[0] in ("register_task", "update_status")]
    assert names == ["register_task", "update_status"], filing.ingest.events


def test_q2_b_A_REFUSED_WRITE_READS_NO_ROW_AND_FILES_NOTHING(client, fake_write_origin, filing):
    filing.ingest.row = _row()
    fake_write_origin.set_result("write_refused", "dropper is not a program member")
    out = _post(client, _body())
    assert out["status"] == "write_refused" and out["promotion"] is None
    assert filing.ingest.events == []
    assert filing.registered == []
    assert filing.ingest.row["status"] == "awaiting_origin"


@pytest.mark.parametrize("stage", ["received", "extracting", "review", "promoted", "rejected"])
def test_q2_c_A_ROW_NOT_AT_awaiting_origin_IS_NOT_TOUCHED(client, fake_write_origin, filing, stage):
    filing.ingest.row = _row(status=stage)
    out = _post(client, _body())
    assert out["status"] == "written" and out["promotion"] is None
    assert filing.registered == []
    assert [e for e in filing.ingest.events if e[0] == "update_status"] == []
    assert filing.ingest.row["status"] == stage


def test_q2_c_AN_ABSENT_ROW_IS_NOT_AN_ERROR(client, fake_write_origin, filing):
    filing.ingest.row = None
    out = _post(client, _body())
    assert out["status"] == "written" and out["promotion"] is None
    assert filing.registered == []


def test_q2_d_A_FILING_REFUSAL_LEAVES_THE_ROW_AT_awaiting_origin_AND_THE_WRITE_STANDS(
        client, fake_write_origin, filing):
    filing.ingest.row = _row()
    filing.raises = ht.NoEntitledRecipients("no recipients (stubbed)")
    out = _post(client, _body())
    assert out["status"] == "written"
    assert out["promotion"] == {"filed": False, "error": "no_entitled_recipients"}, out
    assert filing.ingest.row["status"] == "awaiting_origin"
    assert [e for e in filing.ingest.events if e[0] == "update_status"] == []


def test_q2_d_A_ROW_WITH_NO_extraction_ref_IS_REFUSED_BY_NAME_NOT_STRANDED(
        client, fake_write_origin, filing):
    filing.ingest.row = _row(extraction_ref=None)
    out = _post(client, _body())
    assert out["status"] == "written"
    assert out["promotion"] == {"filed": False, "error": "no_extraction_ref"}, out
    assert filing.registered == []
    assert filing.ingest.row["status"] == "awaiting_origin"


def test_q2_e_AN_ALREADY_FILED_TASK_IS_NOT_REFILED_BUT_THE_ROW_MOVES(
        client, fake_write_origin, filing):
    filing.ingest.row = _row()
    filing.exists = True
    out = _post(client, _body())
    assert out["promotion"]["filed"] is True
    assert out["promotion"]["task_status"] == "ALREADY_FILED"
    assert filing.registered == []
    assert filing.ingest.row["status"] == "review"


@pytest.mark.parametrize("owner", ["finance", "FINANCE"])
def test_q2_f_THE_AUDIENCE_COMES_FROM_THE_ORIGIN_NEVER_THE_KIND(
        client, fake_write_origin, filing, owner):
    """The registration is deliberately domainless: the kind-registry path would 422
    `no_declared_domain`. The origin's owner_domain is the audience."""
    filing.ingest.row = _row()
    out = _post(client, _body(owner))
    assert out["promotion"].get("error") != "no_declared_domain", out
    assert out["promotion"]["filed"] is True, out
    [kw] = filing.registered
    assert kw["audience"] == "document_promotion:FINANCE"
    assert kw["payload"]["review_pool"] == "FINANCE"
