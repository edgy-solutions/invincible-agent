"""A declared delegate reads what its workflows produced (ADR-0041 §8.1; ADR-0047 §5.1 as amended).

RULED 2026-10-08 (Chris): `seeded_by` is stamped at `released` by the runner; a `svc:` delegate is
a recipient only as the seeding delegate; GET /artifacts/{id} admits it. THE POPULATION IS EMPTY
TODAY: no workflow writes an AnswerArtifact with a `case_id`, so the stamp matches nothing and the
read path has nobody to admit. This is a PATH WITH NO PRODUCER YET, and the last arm seals that.

Arms:
  runner   a case keeps `seeded_by`; exactly one stamp at the stamp outcome, none otherwise.
  route    POST /internal/cases/{case_id}/seeded-by: caller gate, 422, statement text + params.
  gate     GatewayArtifacts.get: owner / seeding delegate admitted; the rest `empty`.
  contract the SDK's check_mesh_artifacts_entitlement_contract against GatewayArtifacts.
  read     GET /artifacts/{id} answers an unentitled caller exactly as it answers an absent id.
  writer   `case_id` lands on the node only when given (statement text and params).
  seal     no call site of the answer-artifact writer passes `case_id=` yet.

Run: uv run pytest tests/test_a_delegate_reads_what_it_seeded.py -v
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

httpx = pytest.importorskip("httpx")
pytest.importorskip("fastapi")
pytest.importorskip("restate")
from fastapi.testclient import TestClient  # noqa: E402

import restate  # noqa: E402
from iagent_mesh import Initiator, check_mesh_artifacts_entitlement_contract  # noqa: E402
from iagent_mesh.interfaces import MeshArtifacts  # noqa: E402

from src.iagent import answer_artifact_writer as aaw  # noqa: E402
from src.iagent import artifact_reads  # noqa: E402
from src.iagent import gateway  # noqa: E402
# the runner harness: the SAME module objects main/the real executor use (sys.path set there)
from tests.test_a_case_runs_from_trigger_to_terminal import (  # noqa: E402,F401
    DOOR_BLOCK, _Cluster, _answer, _body, _facts, policy, registered, wr, yaml,
)

_REPO = Path(__file__).resolve().parents[1]
DELEGATE = "svc:openddil"
OTHER_DELEGATE = "svc:other"
PERSON = "alice@example.com"
_MAP = json.dumps({DELEGATE: ["operator.atlantia@example.com"], OTHER_DELEGATE: []})


@pytest.fixture(autouse=True)
def _delegates(monkeypatch):
    monkeypatch.setenv("DELEGATE_ON_BEHALF_OF", _MAP)


# =============================================================================================
# runner
# =============================================================================================

async def _start(c, key, *, seeded_by):
    req = {"trigger": "fault", "facts": _facts(key), "provenance": DOOR_BLOCK}
    if seeded_by is not None:
        req["seeded_by"] = seeded_by
    return await _body(wr.run)(c.ctx(key), req)


@pytest.fixture
def stamps(monkeypatch):
    calls: list = []
    monkeypatch.setattr(wr, "_stamp_seeded_by",
                        lambda case_id, seeded_by: calls.append((case_id, seeded_by)) or {})
    return calls


@pytest.mark.asyncio
async def test_a_case_opened_with_seeded_by_keeps_it_on_the_record(policy, registered, stamps):
    c = _Cluster({("E-1~1", "approval_decide"): _answer("ok")})
    await _start(c, "E-1", seeded_by=DELEGATE)
    assert c.case("E-1")["seeded_by"] == DELEGATE


@pytest.mark.asyncio
async def test_a_case_opened_without_seeded_by_records_none(policy, registered, stamps):
    c = _Cluster({("E-1~1", "approval_decide"): _answer("ok")})
    await _start(c, "E-1", seeded_by=None)
    assert c.case("E-1")["seeded_by"] is None


@pytest.mark.asyncio
async def test_the_stamp_outcome_triggers_exactly_one_stamp(policy, registered, stamps, monkeypatch):
    # the harness's own tables speak `ok`; the constant's real value is pinned below
    monkeypatch.setattr(wr, "SEEDED_BY_STAMP_OUTCOME", "ok")
    c = _Cluster({("E-1~1", "approval_decide"): _answer("ok")})
    await _start(c, "E-1", seeded_by=DELEGATE)
    assert stamps == [("E-1", DELEGATE)], stamps
    assert [n for n in c.ctx("E-1").runs if n.startswith("stamp_seeded_by_")] == ["stamp_seeded_by_1"]


@pytest.mark.asyncio
async def test_another_outcome_makes_no_stamp(policy, registered, stamps):
    # the real constant is `released`; this case ends on `ok`
    assert wr.SEEDED_BY_STAMP_OUTCOME == "released"
    c = _Cluster({("E-1~1", "approval_decide"): _answer("ok")})
    await _start(c, "E-1", seeded_by=DELEGATE)
    assert stamps == []


@pytest.mark.asyncio
async def test_no_seeded_by_makes_no_stamp_even_at_the_stamp_outcome(
        policy, registered, stamps, monkeypatch):
    monkeypatch.setattr(wr, "SEEDED_BY_STAMP_OUTCOME", "ok")
    c = _Cluster({("E-1~1", "approval_decide"): _answer("ok")})
    await _start(c, "E-1", seeded_by=None)
    assert stamps == []


@pytest.mark.asyncio
async def test_a_blank_seeded_by_is_refused_at_open(policy, registered, stamps):
    c = _Cluster()
    with pytest.raises(restate.TerminalError):
        await _start(c, "E-1", seeded_by="  ")


def test_the_stamp_outcome_is_the_release_chains_own_outcome():
    path = _REPO / "policy/overlays/openddil-lab/decisions/maint_release_chaining.yaml"
    table = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert wr.SEEDED_BY_STAMP_OUTCOME in table["domain"]["outcome"]
    assert {"outcome": wr.SEEDED_BY_STAMP_OUTCOME} in [
        {k: v for k, v in r["when"].items() if k == "outcome"} for r in table["rows"]]


def test_the_stamp_posts_to_the_internal_route_as_the_case_runner(monkeypatch):
    import spo_step_executor as spo
    sent = {}

    class _R:
        status_code = 200

    monkeypatch.setattr(spo, "mint_case_runner_token", lambda: "tok")
    import requests
    monkeypatch.setattr(requests, "post", lambda url, **kw: sent.update(url=url, **kw) or _R())
    monkeypatch.setenv("CORTEX_BFF_URL", "http://bff:1/")
    wr._stamp_seeded_by("E-1", DELEGATE)
    assert sent["url"] == "http://bff:1/internal/cases/E-1/seeded-by"
    assert sent["json"] == {"seeded_by": DELEGATE}
    assert sent["headers"] == {"Authorization": "Bearer tok"}


def test_a_refused_stamp_is_terminal(monkeypatch):
    import spo_step_executor as spo
    import requests

    class _R:
        status_code = 403

    monkeypatch.setattr(spo, "mint_case_runner_token", lambda: "tok")
    monkeypatch.setattr(requests, "post", lambda url, **kw: _R())
    with pytest.raises(restate.TerminalError):
        wr._stamp_seeded_by("E-1", DELEGATE)


# =============================================================================================
# the stubbed driver
# =============================================================================================

class _Rec(dict):
    pass


class _Session:
    def __init__(self, driver):
        self.d = driver

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, cypher, **params):
        self.d.calls.append((cypher, params))
        return self.d.answer(cypher, params)


class _Driver:
    """`store` maps artifact id -> {fields..., "owners": {actor ids}}. `is_owner` is computed here
    from `owners` and the statement's `$user_id`, standing in for the PRODUCED_FOR match."""

    def __init__(self, store=None, count=0):
        self.store, self.calls, self.count = store or {}, [], count

    def session(self):
        return _Session(self)

    def answer(self, cypher, params):
        outer = self

        class _Out:
            def single(_self):
                if "count(a) AS n" in cypher:
                    return {"n": outer.count}
                row = outer.store.get(params["artifact_id"])
                if row is None:
                    return None
                rec = _Rec({k: v for k, v in row.items() if k != "owners"})
                rec["is_owner"] = params["user_id"] in row["owners"]
                return rec

            def __iter__(_self):
                return iter(())
        return _Out()


def _row(**over):
    base = {"id": "A-1", "status": "complete", "summary": "s", "question_text": "q",
            "valid_as_of": 1, "duration_ms": 1, "resolved_intent": None, "routing_inline": None,
            "derived_from": None, "origin_owner_domain": None, "origin_program": None,
            "seeded_by": None, "owners": {PERSON}}
    base.update(over)
    return base


def _get(driver, subject, id="A-1", **kw):
    arts = artifact_reads.GatewayArtifacts(driver, gateway._delegate_principals)
    return arts.get(Initiator(subject=subject, kind="person"),
                    kind=artifact_reads.ANSWER_ARTIFACT_KIND, id=id, **kw)


# =============================================================================================
# the read gate
# =============================================================================================

def test_the_owner_is_admitted():
    r = _get(_Driver({"A-1": _row()}), PERSON)
    assert r.outcome == "answered" and r.rows[0]["id"] == "A-1"


def test_the_seeding_delegate_is_admitted():
    r = _get(_Driver({"A-1": _row(seeded_by=DELEGATE)}), DELEGATE)
    assert r.outcome == "answered"


def test_a_different_delegate_is_refused():
    r = _get(_Driver({"A-1": _row(seeded_by=DELEGATE)}), OTHER_DELEGATE)
    assert r.outcome == "empty"


def test_a_person_whose_id_equals_seeded_by_is_refused():
    """seeded_by planted equal to a person's id: the person is not in the delegate map."""
    r = _get(_Driver({"A-1": _row(seeded_by=PERSON, owners=set())}), PERSON)
    assert r.outcome == "empty"


def test_an_absent_seeded_by_is_refused():
    assert _get(_Driver({"A-1": _row(seeded_by=None, owners=set())}), DELEGATE).outcome == "empty"
    assert _get(_Driver({"A-1": _row(seeded_by="", owners=set())}), DELEGATE).outcome == "empty"


def test_the_authz_id_extension_separates_the_owner_key_from_the_delegate_identity():
    d = _Driver({"A-1": _row(seeded_by=DELEGATE, owners=set())})
    assert _get(d, "a-uuid-sub", authz_id=DELEGATE).outcome == "answered"
    assert _get(d, "a-uuid-sub").outcome == "empty"


def test_refused_and_absent_are_the_same_result():
    refused = _get(_Driver({"A-1": _row(owners=set())}), "stranger")
    absent = _get(_Driver({}), "stranger")
    assert refused == absent and refused.outcome == "empty"


def test_the_statement_selects_seeded_by_and_the_owner_edge():
    d = _Driver({"A-1": _row()})
    _get(d, PERSON)
    cypher, params = d.calls[0]
    assert "a.seeded_by             AS seeded_by" in cypher
    assert "PRODUCED_FOR" in cypher
    assert params == {"artifact_id": "A-1", "user_id": PERSON}


def test_an_unsupported_kind_raises():
    arts = artifact_reads.GatewayArtifacts(_Driver(), gateway._delegate_principals)
    with pytest.raises(ValueError):
        arts.get(Initiator(subject=PERSON, kind="person"), kind="document", id="A-1")
    with pytest.raises(ValueError):
        arts.list_by_kind(Initiator(subject=PERSON, kind="person"), kind="document")


def test_list_by_kind_scopes_to_owner_or_seeding_delegate():
    d = _Driver()
    arts = artifact_reads.GatewayArtifacts(d, gateway._delegate_principals)
    assert arts.list_by_kind(Initiator(subject=DELEGATE, kind="person"),
                             kind=artifact_reads.ANSWER_ARTIFACT_KIND).outcome == "empty"
    cypher, params = d.calls[0]
    assert "owner IS NOT NULL OR ($is_delegate AND a.seeded_by = $authz_id)" in cypher
    assert params == {"user_id": DELEGATE, "authz_id": DELEGATE, "is_delegate": True}
    arts.list_by_kind(Initiator(subject=PERSON, kind="person"),
                      kind=artifact_reads.ANSWER_ARTIFACT_KIND)
    assert d.calls[1][1]["is_delegate"] is False


def test_the_implementation_satisfies_the_protocol_and_its_contract():
    store = {"A-1": _row(seeded_by=DELEGATE, owners={PERSON})}
    arts = artifact_reads.GatewayArtifacts(_Driver(store), gateway._delegate_principals)
    assert isinstance(arts, MeshArtifacts)
    kind = artifact_reads.ANSWER_ARTIFACT_KIND
    check_mesh_artifacts_entitlement_contract(
        call_get_as_entitled=lambda: arts.get(Initiator(subject=PERSON, kind="person"),
                                              kind=kind, id="A-1"),
        call_get_as_unentitled=lambda: arts.get(Initiator(subject="stranger", kind="person"),
                                                kind=kind, id="A-1"),
        call_get_absent=lambda: arts.get(Initiator(subject=PERSON, kind="person"),
                                         kind=kind, id="never-written"),
    )


# =============================================================================================
# GET /artifacts/{id}
# =============================================================================================

def _login(authz_id):
    user = type("U", (), {"authz_id": authz_id, "id": authz_id, "sub": authz_id,
                          "email": authz_id, "persona": None, "entitled_domains": [],
                          "is_authenticated": True})()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user


@pytest.fixture
def api(monkeypatch):
    def _make(store):
        monkeypatch.setattr(gateway, "neo4j_driver", _Driver(store))
        return TestClient(gateway.app)
    yield _make
    gateway.app.dependency_overrides.clear()


def test_the_route_answers_an_unentitled_caller_as_it_answers_an_absent_id(api):
    c = api({"A-1": _row(owners=set())})
    _login("stranger")
    refused = c.get("/artifacts/A-1")
    absent = c.get("/artifacts/NEVER")
    assert refused.status_code == absent.status_code == 404
    assert refused.json()["detail"].replace("A-1", "X") == absent.json()["detail"].replace("NEVER", "X")


def test_the_route_admits_the_owner_and_the_seeding_delegate(api):
    c = api({"A-1": _row(seeded_by=DELEGATE)})
    _login(PERSON)
    assert c.get("/artifacts/A-1").status_code == 200
    _login(DELEGATE)
    r = c.get("/artifacts/A-1")
    assert r.status_code == 200 and r.json()["id"] == "A-1"
    _login(OTHER_DELEGATE)
    assert c.get("/artifacts/A-1").status_code == 404


# =============================================================================================
# POST /internal/cases/{case_id}/seeded-by
# =============================================================================================

def test_a_caller_that_is_not_the_case_runner_gets_403(api, monkeypatch):
    d = _Driver()
    monkeypatch.setattr(gateway, "neo4j_driver", d)
    c = TestClient(gateway.app)
    _login(DELEGATE)
    r = c.post("/internal/cases/E-1/seeded-by", json={"seeded_by": DELEGATE})
    assert r.status_code == 403 and d.calls == []


def test_an_undeclared_seeded_by_is_422(monkeypatch):
    d = _Driver()
    monkeypatch.setattr(gateway, "neo4j_driver", d)
    c = TestClient(gateway.app)
    _login(gateway._CASE_RUNNER_SERVICE_AUTHZ_ID)
    r = c.post("/internal/cases/E-1/seeded-by", json={"seeded_by": PERSON})
    assert r.status_code == 422
    assert r.json()["detail"] == {"error": "seeded_by_not_a_declared_delegate"}
    assert d.calls == []
    gateway.app.dependency_overrides.clear()


@pytest.mark.parametrize("count", [0, 3])
def test_the_stamp_sends_the_statement_with_case_id_and_seeded_by(monkeypatch, count):
    d = _Driver(count=count)
    monkeypatch.setattr(gateway, "neo4j_driver", d)
    c = TestClient(gateway.app)
    _login(gateway._CASE_RUNNER_SERVICE_AUTHZ_ID)
    r = c.post("/internal/cases/E-1/seeded-by", json={"seeded_by": DELEGATE})
    assert r.status_code == 200, r.text
    assert r.json() == {"case_id": "E-1", "stamped": count}
    assert d.calls == [(
        "MATCH (a:AnswerArtifact {case_id: $case_id}) "
        "SET a.seeded_by = $seeded_by RETURN count(a) AS n",
        {"case_id": "E-1", "seeded_by": DELEGATE},
    )]
    gateway.app.dependency_overrides.clear()


# =============================================================================================
# the writer
# =============================================================================================

class _Tx:
    def __init__(self):
        self.calls = []

    def run(self, cypher, **params):
        self.calls.append((cypher, params))

        class _O:
            def single(_s):
                return {"watermark": 1}

            def __iter__(_s):
                return iter(())
        return _O()


def _bundle(**kw):
    return aaw.AnswerArtifactBundle(
        id="A-9", question_text="q", message_id="m", valid_as_of=1, status="complete",
        produced_by={}, produced_for={}, resolved_intent={}, routing=None, **kw)


def _case_id_statements(tx):
    return [(c, p) for c, p in tx.calls if "a.case_id" in c]


def test_case_id_lands_on_the_node_when_given():
    tx = _Tx()
    aaw.AnswerArtifactWriter._tx_merge(tx, _bundle(case_id="E-1"), "durable")
    assert _case_id_statements(tx) == [(
        "MATCH (a:AnswerArtifact {id: $id}) SET a.case_id = $case_id",
        {"id": "A-9", "case_id": "E-1"},
    )]


def test_case_id_is_absent_when_not_given():
    tx = _Tx()
    aaw.AnswerArtifactWriter._tx_merge(tx, _bundle(), "durable")
    assert _case_id_statements(tx) == []
    assert not any("case_id" in p for _c, p in tx.calls)


# =============================================================================================
# THE NO-PRODUCER SEAL
# =============================================================================================

def test_no_call_site_of_the_answer_artifact_writer_passes_case_id():
    """THIS IS THE "PATH, NO PRODUCER YET" STATE. Today no call site constructs an
    AnswerArtifactBundle with `case_id=`, so the runner's `released` stamp matches nothing and the
    seeding delegate's read path has an empty population. This arm must be INVERTED, NOT DELETED,
    when the first workflow producer lands: it then asserts that exactly the declared producer(s)
    pass `case_id=`, and that the stamp's Cypher still finds them."""
    sites: list[str] = []
    passing: list[str] = []
    for root in ("src", "agent_fleet"):
        for path in (_REPO / root).rglob("*.py"):
            if ".venv" in path.parts or "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if "AnswerArtifactBundle" not in text:
                continue
            for node in ast.walk(ast.parse(text)):
                if not isinstance(node, ast.Call):
                    continue
                f = node.func
                name = f.id if isinstance(f, ast.Name) else getattr(f, "attr", None)
                if name != "AnswerArtifactBundle":
                    continue
                where = f"{path.relative_to(_REPO)}:{node.lineno}"
                sites.append(where)
                if any(k.arg == "case_id" or k.arg is None for k in node.keywords):
                    passing.append(where)
    assert sites, "the scan found no AnswerArtifactBundle call site: the control is void"
    assert passing == [], f"a producer now passes case_id=: invert this arm. {passing}"
