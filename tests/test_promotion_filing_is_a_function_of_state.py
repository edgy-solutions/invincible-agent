"""Promotion filing is a FUNCTION OF STATE (Q2b, Q2c; 2026-10-10).

`gateway._file_promotion_if_ready` files `document_promotion:<owner_domain>` iff the ingest row is
at `awaiting_origin` AND an accepted origin exists on the artifact. The accept route, the stage
route and the retry route all call it, so the order the steward's accept and doc-tools'
extraction land in cannot matter (Q2b), and a refused filing is retryable (Q2c).

Harness: an in-memory ingest world (get_row / update_status / get_status_for), recording
human_tasks, and `gateway._read_accepted_origin` patched to read the world's STORE -- never a real
graph. Arm 3 exercises the real reader against a fake driver.

Run: uv run --frozen pytest tests/test_promotion_filing_is_a_function_of_state.py -v
"""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import pytest

httpx = pytest.importorskip("httpx")
fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import content_kinds as ck  # noqa: E402
from src.iagent import gateway  # noqa: E402
from src.iagent import human_tasks as ht  # noqa: E402
from src.iagent import ingest_status as ist  # noqa: E402
from src.iagent import origin_writer  # noqa: E402

_REAL_READ_ACCEPTED_ORIGIN = gateway._read_accepted_origin

_HEX = "b" * 64
_ID = "sha256:" + _HEX
_PREFIX = f"ingress-user/pdf/{_HEX}/"
_REF = f"{_PREFIX}generated/doc_pdf/doc-tools@61f74dc/manifest.json"
ALICE = "alice@example.com"


class World:
    def __init__(self, status="extracting"):
        self.row = {"id": _ID, "status": status, "kind": "pdf", "content_kind": "pdf",
                    "submitted_by": ALICE, "on_behalf_of": None, "object_prefix": _PREFIX,
                    "extraction_ref": _REF if status != "extracting" else None}
        self.origin = None          # the STORE: what _read_accepted_origin reads back
        self.registered = []
        self.status_moves = []
        self.read_raises = None

    def get_row(self, ingest_id):
        return self.row if ingest_id == self.row["id"] else None

    def get_status_for(self, ingest_id, *, caller_id):
        r = self.get_row(ingest_id)
        if r and caller_id in (r["submitted_by"], r["on_behalf_of"]):
            return r
        return None

    def update_status(self, ingest_id, status, **kw):
        self.status_moves.append(status)
        self.row["status"] = status
        if kw.get("extraction_ref"):
            self.row["extraction_ref"] = kw["extraction_ref"]

    def read_origin(self, ingest_id):
        if self.read_raises is not None:
            raise self.read_raises
        if not self.origin:
            return None
        return {"owner_domain": self.origin["owner_domain"], "program": None,
                "resolved_by": "steward"}


@pytest.fixture
def world(monkeypatch):
    w = World()
    monkeypatch.setattr(ist, "get_row", w.get_row)
    monkeypatch.setattr(ist, "get_status_for", w.get_status_for)
    monkeypatch.setattr(ist, "update_status", w.update_status)
    reg = type("Reg", (), {"domain": None, "model_fields_set": frozenset({"domain"})})()
    monkeypatch.setattr(ck, "by_kind", lambda kind: reg)
    manifest = {"doc_id": "N-1", "filename": "doc.pdf", "source_key": _PREFIX + "doc.pdf",
                "pipeline_version": "doc-tools@61f74dc", "ingest_id": _ID,
                "provenance": {"standing": "supervised", "ingest_id": _ID}}
    monkeypatch.setattr(gateway, "_read_extraction_manifest", lambda key: manifest)
    # the zero-row gate reads review.json at REVIEW entry (architect ruling 2026-10-17); one part row
    monkeypatch.setattr(gateway, "_read_review_json", lambda key: {
        "review_items": [{"field_path": "parts[0].affected_mpn", "value": "X"}]})
    monkeypatch.setattr(ht, "task_exists",
                        lambda task_id: any(k["task_id"] == task_id for k in w.registered))

    def _register(**kw):
        w.registered.append(kw)
        return {"task_id": kw["task_id"], "recipients": ["steward"]}

    monkeypatch.setattr(ht, "register_task", _register)
    monkeypatch.setattr(ht, "check_can_view_program", lambda program, who: False)
    monkeypatch.setattr(gateway, "_read_accepted_origin", w.read_origin)
    return w


def _as(authz_id):
    user = type("U", (), {"authz_id": authz_id, "id": authz_id, "sub": authz_id, "email": None,
                          "persona": None, "entitled_domains": [], "is_authenticated": True})()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user
    return TestClient(gateway.app)


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    gateway.app.dependency_overrides.clear()


_BODY = {
    "artifact_id": _ID, "dropped_by": {"authz_id": ALICE},
    "origin": {"owner_domain": "sustainment", "program": "PRG-1",
               "obtained_via": "contract_deliverable"},
    "evidence": {"source": "contract", "citation": "CDRL A001"},
    "approval_chain": [{"step": 1, "role": "steward", "approver_sub": "steward@x",
                        "decision": "approved"}],
}


def _accept(world, *, store_owner=None, body=None):
    """The case runner's `written` step; the fake write records the origin in the world's store
    (`store_owner` overrides what the STORE holds, to differ from the request)."""
    body = body or _BODY

    def _fake(resolution, *, graph_writer, initiator, dropper_is_program_member):
        world.origin = {"owner_domain": store_owner or resolution["origin"]["owner_domain"]}
        return {"status": "written", "reason": None}

    mp = pytest.MonkeyPatch()
    mp.setattr(origin_writer, "write_origin", _fake)
    mp.setattr("agent_fleet.utils.mesh_writers.neo4j_graph.Neo4jGraphWriter",
               lambda **kw: object())
    try:
        r = _as("svc:case-runner").post("/internal/origin/write", json=body)
    finally:
        mp.undo()
    assert r.status_code == 200, r.text
    return r.json()


def _stage_review(world):
    r = _as("svc:doc-tools").post(f"/ingest/{_ID}/stage",
                                  json={"stage": "review", "extraction_ref": _REF})
    assert r.status_code == 200, r.text
    return r.json()


def _retry(world, who=ALICE):
    return _as(who).post(f"/ingest/{_ID}/retry")


# 1 ─ Q2b: the accept lands FIRST ───────────────────────────────────────────────────────────────

def test_q2b_AN_ACCEPT_BEFORE_THE_EXTRACTION_STILL_FILES_WHEN_THE_STAGE_ROUTE_ARRIVES(world):
    world.row["status"] = "extracting"
    out = _accept(world)
    assert out["status"] == "written" and out["promotion"] is None, out
    assert world.registered == []
    resp = _stage_review(world)
    assert resp["stage"] == "review" and resp["task_status"] == "FILED", resp
    assert world.row["status"] == "review"
    [kw] = world.registered
    assert kw["audience"] == "document_promotion:SUSTAINMENT"
    assert kw["requested_by"] == "svc:doc-tools"
    assert world.status_moves == ["awaiting_origin", "review"]


# 2 ─ Q2b control: no accepted origin ───────────────────────────────────────────────────────────

def test_q2b_CONTROL_NO_ACCEPTED_ORIGIN_STAYS_AT_awaiting_origin_WITH_NO_TASK(world):
    world.row["status"] = "extracting"
    resp = _stage_review(world)
    assert resp["stage"] == "awaiting_origin" and resp["task_id"] is None
    assert resp["task_status"] == "NO_TASK_AWAITING_ORIGIN"
    assert world.registered == [] and world.row["status"] == "awaiting_origin"


# 3 ─ the real reader's accepted-origin predicate ───────────────────────────────────────────────

class _Result:
    def __init__(self, row):
        self._row = row

    def single(self):
        return self._row


class _Session:
    def __init__(self, drv):
        self._drv = drv

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, cypher, **kw):
        self._drv.calls.append((cypher, kw))
        return _Result(self._drv.row)


class _Driver:
    def __init__(self, row):
        self.row, self.calls = row, []

    def session(self):
        return _Session(self)


@pytest.mark.parametrize("row", [
    None,
    {"owner_domain": "SUSTAINMENT", "program": "p", "resolved_by": "unresolved"},
    {"owner_domain": "SUSTAINMENT", "program": "p", "resolved_by": None},
    {"owner_domain": "SUSTAINMENT", "program": "p", "resolved_by": ""},
    {"owner_domain": "", "program": "p", "resolved_by": "steward"},
    {"owner_domain": None, "program": "p", "resolved_by": "steward"},
], ids=["no-node", "unresolved", "resolved-none", "resolved-empty", "owner-empty", "owner-none"])
def test_q2_AN_UNRESOLVED_OR_ABSENT_ORIGIN_IS_NOT_AN_ACCEPTED_ONE(monkeypatch, row):
    drv = _Driver(row)
    monkeypatch.setattr(gateway, "neo4j_driver", drv)
    assert _REAL_READ_ACCEPTED_ORIGIN(_ID) is None
    assert drv.calls and drv.calls[0][1] == {"ingest_id": _ID}


def test_q2_CONTROL_A_RESOLVED_ORIGIN_IS_READ_BACK_FROM_THE_NODE_THE_WRITER_WRITES(monkeypatch):
    from src.iagent.promotion_stores import INGEST_FACT_FAMILY
    drv = _Driver({"owner_domain": "SUSTAINMENT", "program": "", "resolved_by": "steward"})
    monkeypatch.setattr(gateway, "neo4j_driver", drv)
    assert _REAL_READ_ACCEPTED_ORIGIN(_ID) == {
        "owner_domain": "SUSTAINMENT", "program": None, "resolved_by": "steward"}
    cypher = drv.calls[0][0]
    assert INGEST_FACT_FAMILY["node_label"] in cypher and INGEST_FACT_FAMILY["node_key"] in cypher


def test_q2_AN_UNCONNECTED_GRAPH_STORE_RAISES_RATHER_THAN_READING_AS_ABSENT(monkeypatch):
    monkeypatch.setattr(gateway, "neo4j_driver", None)
    with pytest.raises(RuntimeError):
        _REAL_READ_ACCEPTED_ORIGIN(_ID)


# 4-6 ─ Q2c: the retry route ────────────────────────────────────────────────────────────────────

def test_q2c_RETRY_ON_awaiting_origin_WITH_AN_ACCEPTED_ORIGIN_FILES_AS_THE_DROPPER(world):
    world.row.update(status="awaiting_origin", extraction_ref=_REF)
    world.origin = {"owner_domain": "sustainment"}
    r = _retry(world)
    assert r.status_code == 200, r.text
    assert r.json()["stage"] == "review" and r.json()["task_status"] == "FILED"
    [kw] = world.registered
    assert kw["requested_by"] == ALICE and kw["audience"] == "document_promotion:SUSTAINMENT"
    assert world.row["status"] == "review"


def test_q2c_RETRY_ON_awaiting_origin_WITH_NO_ACCEPTED_ORIGIN_IS_409_AND_MOVES_NOTHING(world):
    world.row.update(status="awaiting_origin", extraction_ref=_REF)
    r = _retry(world)
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["error"] == "awaiting_origin"
    assert world.registered == [] and world.row["status"] == "awaiting_origin"
    assert world.status_moves == []


def test_q2c_A_REFUSED_FILING_ANSWERS_503_promotion_not_filed_AND_THE_ROW_STAYS(
        world, monkeypatch):
    world.row.update(status="awaiting_origin", extraction_ref=_REF)
    world.origin = {"owner_domain": "sustainment"}

    async def _refuse(*a, **kw):
        raise gateway.HTTPException(status_code=422, detail={"error": "no_entitled_recipients"})

    monkeypatch.setattr(gateway, "_file_or_find_document_promotion_task", _refuse)
    r = _retry(world)
    assert r.status_code == 503, r.text
    d = r.json()["detail"]
    assert d["error"] == "promotion_not_filed" and d["reason"] == "no_entitled_recipients"
    assert world.row["status"] == "awaiting_origin" and world.status_moves == []


# 7 ─ an unreadable origin is not an absent one ─────────────────────────────────────────────────

def test_q2_AN_ORIGIN_READ_THAT_RAISES_FILES_NOTHING_AND_MOVES_NOTHING(world):
    world.row.update(status="awaiting_origin", extraction_ref=_REF)
    world.read_raises = RuntimeError("graph store not connected")
    out = asyncio.run(gateway._file_promotion_if_ready(_ID, requested_by="svc:case-runner"))
    assert out == {"filed": False, "error": "origin_unreadable"}
    assert world.registered == [] and world.row["status"] == "awaiting_origin"
    assert world.status_moves == []


# 8 ─ idempotence ───────────────────────────────────────────────────────────────────────────────

def test_q2_THE_ACCEPT_THEN_A_SECOND_ACCEPT_THEN_ANOTHER_CALL_FILE_ONE_TASK(world):
    world.row.update(status="awaiting_origin", extraction_ref=_REF)
    out = _accept(world)
    assert out["promotion"]["filed"] is True, out
    assert world.row["status"] == "review"
    # (a retry of a review row for a domainless kind 422s `no_declared_domain` in the shared
    # helper -- pre-existing, reported separately; the idempotence under test is the state fn.)
    assert _accept(world)["promotion"] is None, "a row already at review is not touched"
    again = asyncio.run(gateway._file_promotion_if_ready(_ID, requested_by=ALICE))
    assert again is None, "a row already at review is not touched"
    assert len(world.registered) == 1


def test_q2_THE_STAGE_ROUTE_THEN_AN_ACCEPT_FILE_ONE_TASK(world):
    world.row["status"] = "extracting"
    _stage_review(world)                    # no origin yet -> awaiting_origin
    out = _accept(world)                    # the accept arrives second
    assert out["promotion"]["filed"] is True, out
    assert len(world.registered) == 1 and world.row["status"] == "review"


# 10 ─ the audience is what the STORE holds ─────────────────────────────────────────────────────

def test_q2_THE_AUDIENCE_IS_READ_FROM_THE_STORE_NOT_FROM_THE_REQUEST(world):
    world.row.update(status="awaiting_origin", extraction_ref=_REF)
    out = _accept(world, store_owner="finance")      # request says sustainment
    assert out["promotion"]["filed"] is True, out
    [kw] = world.registered
    assert kw["audience"] == "document_promotion:FINANCE"
    assert kw["payload"]["review_pool"] == "FINANCE"


# 9 ─ ONE PREDICATE ─────────────────────────────────────────────────────────────────────────────

def _gateway_tree():
    return ast.parse(Path(gateway.__file__).read_text(encoding="utf-8"))


def _calls_state_function(fn):
    for n in ast.walk(fn):
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "_file_promotion_if_ready":
            return True
    return False


def test_q2_ONE_PREDICATE_THREE_CALLERS_AND_NO_SECOND_COPY():
    tree = _gateway_tree()
    defs = [n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    by_name = {}
    for d in defs:
        by_name.setdefault(d.name, []).append(d)
    assert len(by_name.get("_file_promotion_if_ready", [])) == 1
    assert "_file_promotion_for_accepted_origin" not in by_name
    for name in ("write_origin_route", "update_ingest_stage", "ingest_retry_route"):
        [fn] = by_name[name]
        assert _calls_state_function(fn), f"{name} does not call _file_promotion_if_ready"
