"""Every terminal transition of a case writes its summary to the Postgres case row (ruled
2026-10-16): state, final reason, transitions, seeded_by, artifact ids -- so the record outlives
Restate. A case record is durable evidence, not runtime state.

Arms:
  route   POST /internal/cases/{id}/summary: only svc:case-runner (403 and NOTHING written
          otherwise); the artifact ids come from the graph, by a statement that matches on
          `case_id`; `released` also stamps `released_at` with a coalesce (first release wins),
          any other state does not.
  runner  the normal terminal and the TerminalError handler each post exactly one summary with
          the right state and reason; the TerminalError still propagates; a summary write that
          fails neither fails a released case nor swallows the original error; the journalled
          run is bounded in attempts.
  wire    the runner's POST goes to the internal route as the case runner; a refusal is terminal.
  store   the upsert is ON CONFLICT (case_id) DO UPDATE, and the DDL in the module is the DDL in
          sql/create_case_summary.sql.

Run: uv run pytest tests/test_a_terminal_case_writes_its_summary.py -v
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

pytest.importorskip("httpx")
pytest.importorskip("fastapi")
pytest.importorskip("restate")
from fastapi.testclient import TestClient  # noqa: E402

import restate  # noqa: E402
from src.iagent import case_summary, gateway, ingest_status  # noqa: E402
from tests.test_a_case_runs_from_trigger_to_terminal import (  # noqa: E402,F401
    _answer, _Ctx, _Cluster, _facts, _refused, policy, registered, wr,
)

_REPO = Path(__file__).resolve().parents[1]
RUNNER = gateway._CASE_RUNNER_SERVICE_AUTHZ_ID
_REAL_WRITE = wr._write_case_summary  # the autouse fixture below replaces it per test


@pytest.fixture(autouse=True)
def _no_case_summary_wire(monkeypatch):
    """Overrides tests/conftest.py's no-op of the same name: here the wire is a RECORDER."""
    sent: list = []
    monkeypatch.setattr(wr, "_write_case_summary",
                        lambda case_id, summary: sent.append((case_id, summary)) or {"written": True})
    return sent


@pytest.fixture
def sent(_no_case_summary_wire):
    return _no_case_summary_wire


# =============================================================================================
# route
# =============================================================================================

class _Session:
    def __init__(self, d):
        self.d = d

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, cypher, **params):
        self.d.calls.append((cypher, params))
        return [{"id": i} for i in self.d.ids]


class _Driver:
    def __init__(self, ids):
        self.ids, self.calls = ids, []

    def session(self):
        return _Session(self)


def _login(authz_id):
    user = type("U", (), {"authz_id": authz_id, "id": authz_id, "sub": authz_id,
                          "email": authz_id, "persona": None, "entitled_domains": [],
                          "is_authenticated": True})()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user


@pytest.fixture
def api(monkeypatch):
    upserts: list = []
    monkeypatch.setattr(case_summary, "upsert_summary", lambda **kw: upserts.append(kw))

    def _make(ids=("A-1", "A-2")):
        driver = _Driver(list(ids))
        monkeypatch.setattr(gateway, "neo4j_driver", driver)
        return TestClient(gateway.app), driver, upserts
    yield _make
    gateway.app.dependency_overrides.clear()


_BODY = {"state": "released", "final_reason": "ack", "seeded_by": "svc:openddil",
         "transitions": [{"from": "x", "outcome": "released", "to": "released",
                          "at": "2026-10-16T10:00:00Z"}]}


def test_a_caller_that_is_not_the_case_runner_gets_403_and_nothing_is_written(api):
    c, driver, upserts = api()
    _login("svc:openddil")
    r = c.post("/internal/cases/E-1/summary", json=_BODY)
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "not_case_runner"
    assert driver.calls == [] and upserts == []


def test_a_released_case_upserts_with_the_artifact_ids_from_the_graph(api):
    c, driver, upserts = api(ids=("A-1", "A-2"))
    _login(RUNNER)
    r = c.post("/internal/cases/E-1/summary", json=_BODY)
    assert r.status_code == 200, r.text
    assert r.json() == {"case_id": "E-1", "artifact_ids": ["A-1", "A-2"]}
    assert len(upserts) == 1
    u = upserts[0]
    assert (u["case_id"], u["state"], u["final_reason"], u["seeded_by"]) == (
        "E-1", "released", "ack", "svc:openddil")
    assert u["transitions"] == _BODY["transitions"] and u["artifact_ids"] == ["A-1", "A-2"]


def test_a_released_case_stamps_released_at_and_the_statement_says_so(api):
    c, driver, _ = api()
    _login(RUNNER)
    c.post("/internal/cases/E-1/summary", json=_BODY)
    (cypher, params), = driver.calls
    # a parameter is not a constraint: the TEXT must match on the case and keep the first stamp
    assert "MATCH (a:AnswerArtifact {case_id: $case_id})" in cypher
    assert "SET a.released_at = coalesce(a.released_at, $now_ms)" in cypher
    assert params["case_id"] == "E-1" and isinstance(params["now_ms"], int)


@pytest.mark.parametrize("state", ["failed", "rejected"])
def test_a_case_that_did_not_release_stamps_no_released_at(api, state):
    c, driver, upserts = api()
    _login(RUNNER)
    r = c.post("/internal/cases/E-1/summary", json=dict(_BODY, state=state))
    assert r.status_code == 200, r.text
    (cypher, params), = driver.calls
    assert "released_at" not in cypher and "now_ms" not in params
    assert "MATCH (a:AnswerArtifact {case_id: $case_id})" in cypher
    assert upserts[0]["state"] == state


def test_a_blank_state_is_422_and_writes_nothing(api):
    c, driver, upserts = api()
    _login(RUNNER)
    assert c.post("/internal/cases/E-1/summary", json=dict(_BODY, state=" ")).status_code == 422
    assert driver.calls == [] and upserts == []


# =============================================================================================
# runner
# =============================================================================================

@pytest.mark.asyncio
async def test_the_normal_terminal_posts_one_summary(policy, registered, sent):
    c = _Cluster({("E-1~1", "approval_decide"): _answer("ok")})
    out = await c.start("E-1", "fault", _facts("E-1"))
    assert out["status"] == "CLOSED"
    (case_id, summary), = sent
    case = c.case("E-1")
    assert case_id == "E-1"
    assert summary["state"] == case["terminal"] and summary["state"] != "failed"
    assert summary["final_reason"] == case["transitions"][-1]["reason"]
    assert summary["transitions"] == case["transitions"]
    assert summary["seeded_by"] == case["seeded_by"]
    assert [n for n in c.ctx("E-1").runs if n == "write_case_summary"] == ["write_case_summary"]


@pytest.mark.asyncio
async def test_a_terminal_error_posts_a_failed_summary_and_still_propagates(
        policy, registered, sent):
    c = _Cluster({("E-1~1", "approval_decide"): _answer("weird")})
    msg = await _refused(c.start("E-1", "fault", _facts("E-1")), 422)
    (case_id, summary), = sent
    assert case_id == "E-1" and summary["state"] == "failed"
    assert summary["final_reason"] == msg
    assert summary["transitions"][-1]["outcome"] == "failed"


@pytest.mark.asyncio
async def test_a_failed_summary_write_does_not_swallow_the_original_error(
        policy, registered, monkeypatch):
    def _boom(case_id, summary):
        raise restate.TerminalError("the BFF is gone", status_code=502)
    monkeypatch.setattr(wr, "_write_case_summary", _boom)
    c = _Cluster({("E-1~1", "approval_decide"): _answer("weird")})
    msg = await _refused(c.start("E-1", "fault", _facts("E-1")), 422)
    assert "BFF is gone" not in msg, "the summary's failure replaced the case's own"


@pytest.mark.asyncio
async def test_a_failed_summary_write_does_not_fail_a_released_case(
        policy, registered, monkeypatch):
    def _boom(case_id, summary):
        raise restate.TerminalError("the BFF is gone", status_code=502)
    monkeypatch.setattr(wr, "_write_case_summary", _boom)
    c = _Cluster({("E-1~1", "approval_decide"): _answer("ok")})
    out = await c.start("E-1", "fault", _facts("E-1"))
    assert out["status"] == "CLOSED"
    assert c.case("E-1")["state"] != "failed"
    assert all(t["outcome"] != "failed" for t in c.case("E-1")["transitions"])


@pytest.mark.asyncio
async def test_the_journalled_write_is_bounded_in_attempts(policy, registered, monkeypatch):
    seen: dict = {}
    real = _Ctx.run

    async def _run(self, name, fn, **opts):
        if name == "write_case_summary":
            seen.update(opts)
        return await real(self, name, fn, **opts)
    monkeypatch.setattr(_Ctx, "run", _run)
    c = _Cluster({("E-1~1", "approval_decide"): _answer("ok")})
    await c.start("E-1", "fault", _facts("E-1"))
    assert seen == {"max_attempts": wr.CASE_SUMMARY_MAX_ATTEMPTS}
    assert 1 < wr.CASE_SUMMARY_MAX_ATTEMPTS <= 10


# =============================================================================================
# wire
# =============================================================================================

def test_the_summary_posts_to_the_internal_route_as_the_case_runner(monkeypatch):
    import requests
    import spo_step_executor as spo
    sent: dict = {}

    class _R:
        status_code = 200

    monkeypatch.setattr(spo, "mint_case_runner_token", lambda: "tok")
    monkeypatch.setattr(requests, "post", lambda url, **kw: sent.update(url=url, **kw) or _R())
    monkeypatch.setenv("CORTEX_BFF_URL", "http://bff:1/")
    _REAL_WRITE("E-1", {"state": "released"})
    assert sent["url"] == "http://bff:1/internal/cases/E-1/summary"
    assert sent["json"] == {"state": "released"}
    assert sent["headers"] == {"Authorization": "Bearer tok"}


# =============================================================================================
# store
# =============================================================================================

class _Cur:
    def __init__(self, log):
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.log.append((sql, params))


class _Conn:
    def __init__(self, log):
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return _Cur(self.log)

    def commit(self):
        pass


def test_the_upsert_overwrites_on_conflict(monkeypatch):
    log: list = []
    monkeypatch.setattr(ingest_status, "_pg_connect", lambda: _Conn(log))
    case_summary.upsert_summary(
        case_id="E-1", state="released", final_reason="ack", seeded_by=None,
        transitions=[{"at": "2026-10-16T10:00:00Z"}], artifact_ids=["A-1"])
    (sql, params), = log
    assert "INSERT INTO case_summary" in sql
    assert "ON CONFLICT (case_id) DO UPDATE" in sql
    assert params[0] == "E-1" and params[1] == "released"
    assert params[6].isoformat().startswith("2026-10-16T10:00:00")


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"--[^\n]*", "", text)).strip()


def test_the_module_ddl_is_the_sql_file_ddl():
    file_ddl = _squash((_REPO / "sql" / "create_case_summary.sql").read_text(encoding="utf-8"))
    assert _squash(case_summary._MIGRATION_SQL) == file_ddl


def test_a_refused_summary_is_terminal(monkeypatch):
    import requests
    import spo_step_executor as spo

    class _R:
        status_code = 403

    monkeypatch.setattr(spo, "mint_case_runner_token", lambda: "tok")
    monkeypatch.setattr(requests, "post", lambda url, **kw: _R())
    with pytest.raises(restate.TerminalError):
        _REAL_WRITE("E-1", {"state": "released"})
