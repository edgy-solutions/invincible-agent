"""Answers at scale (rev 187): paged summaries, a body by id, a newest-first index, server search,
and an archive that hides but never deletes.

Cortex measured one Electric shape of `answer_artifact_projection` at 6.82 MB for ~816 rows
(`routing` 47%, `rendered_output` 31%); a list row needs ~200 B. Each arm below pins one way the
list could quietly become that shape again, or one way archive could lose provenance.

Arms assert on the REQUEST the route sent (statement text plus params), because a recording double
that returns canned rows cannot see a scope change by row identity alone.

Run: uv run python -m pytest tests/test_answers_at_scale.py -q
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

_SQL = _REPO / "sql" / "create_answer_artifact_projection.sql"
_SQL_CHART = _REPO / "helm" / "invincible-agent" / "files" / "sql" / "create_answer_artifact_projection.sql"

ALICE = "a400f096-d252-49cc-9336-5f47a5b9e4cd"
BOB = "b1111111-2222-4333-8444-555555555555"
ITEM_KEYS = {"id", "ts", "title", "summary", "type", "status", "subject", "archived"}


class _User:
    def __init__(self, uid=ALICE, authz="alice@example.com"):
        self.id = uid
        self.authz_id = authz
        self.email = authz
        self.entitlements = type("E", (), {"cells": []})()


# ── a recording Postgres double ───────────────────────────────────────────────────────────

class _Cur:
    def __init__(self, store):
        self.s = store

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.s.setdefault("calls", []).append((sql, params))

    def fetchall(self):
        return list(self.s.get("rows", []))

    def fetchone(self):
        return (0,)


class _Conn:
    def __init__(self, store):
        self.s = store

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self, cursor_factory=None):
        return _Cur(self.s)


@pytest.fixture()
def pg(monkeypatch):
    from iagent import answer_list

    store: dict = {"rows": []}
    monkeypatch.setattr(answer_list, "_pg_connect", lambda: _Conn(store))
    return store


def _db_row(i=1, **over):
    base = {
        "id": f"a-{i}", "created_at": 1788908472000 + i, "question_text": "what does spend look like",
        "summary": "Portfolio · plan Cost Curve", "kind": "answer", "status": "complete",
        "archived_at": None, "subject_uri": "http://x/idp#Portfolio",
        "subject_instance_label": "", "subject_label": "Portfolio", "total": 1,
    }
    base.update(over)
    return base


@pytest.fixture()
def client(monkeypatch):
    import iagent.gateway as gw
    from fastapi.testclient import TestClient

    state = {"user": _User()}
    gw.app.dependency_overrides[gw.get_current_user] = lambda: state["user"]
    c = TestClient(gw.app)
    c.state = state
    yield c
    gw.app.dependency_overrides.clear()


def _sql(pg):
    assert pg["calls"], "no statement was sent"
    return pg["calls"][-1]


# ── 1. never a body ───────────────────────────────────────────────────────────────────────

def test_1_list_items_carry_exactly_the_summary_keys_and_the_sql_names_no_body_column(client, pg):
    pg["rows"] = [_db_row(1), _db_row(2, archived_at=5)]
    r = client.get("/answers")
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert items and all(set(i) == ITEM_KEYS for i in items), [sorted(i) for i in items]
    assert items[0]["subject"] == {"uri": "http://x/idp#Portfolio", "label": "Portfolio"}
    assert items[1]["archived"] is True and items[0]["archived"] is False
    sql, _ = _sql(pg)
    for col in ("rendered_output", "resolved_intent", "graph_trace", "sources"):
        assert col not in sql, f"list SELECT names {col}"
    assert not re.search(r"\brouting\b(?!\s*->)", sql), "a bare routing select (only the sub-path)"


def test_1b_title_is_cut_server_side():
    from iagent import answer_list

    t = answer_list._title("word " * 100)
    assert len(t) <= answer_list.TITLE_MAX and t.endswith("…")
    assert answer_list._title("short") == "short"


# ── 2. scope is the caller ────────────────────────────────────────────────────────────────

def test_2_scope_is_the_caller_and_is_a_bound_parameter(client, pg):
    client.get("/answers")
    sql, params = _sql(pg)
    assert "produced_for_user_id = %(caller)s" in sql, "the statement carries no user predicate"
    assert params["caller"] == ALICE, "the param is not the caller's id"
    client.state["user"] = _User(BOB, "bob@example.com")
    client.get("/answers")
    assert _sql(pg)[1]["caller"] == BOB
    assert ALICE not in _sql(pg)[0] and BOB not in _sql(pg)[0], "the id is in the statement text"


def test_2b_caller_id_goes_through_the_proxys_uuid_check(client, pg):
    client.state["user"] = _User("x' OR '1'='1", "evil@example.com")
    assert client.get("/answers").status_code == 403
    assert not pg.get("calls")


# ── 3. archived hidden by default ─────────────────────────────────────────────────────────

def test_3_archived_hidden_by_default_and_shown_on_request(client, pg):
    client.get("/answers")
    assert "archived_at IS NULL" in _sql(pg)[0]
    client.get("/answers?include_archived=true")
    assert "archived_at IS NULL" not in _sql(pg)[0]


# ── 4. search is injection-safe ───────────────────────────────────────────────────────────

def test_4_search_builds_a_tsquery_of_word_prefixes_only(client, pg):
    raw = "a | b & !c :* )"
    client.get("/answers", params={"q": raw})
    sql, params = _sql(pg)
    tsq = params["tsq"]
    assert re.fullmatch(r"\w+:\*( & \w+:\*)*", tsq), tsq
    assert tsq == "a:* & b:* & c:*"
    assert "to_tsquery('simple', %(tsq)s)" in sql
    assert raw not in sql and "a | b" not in sql, "raw q reached the statement text"


def test_4b_token_cap_and_empty_q():
    from iagent import answer_list

    assert answer_list.build_tsquery("   ") is None and answer_list.build_tsquery(None) is None
    assert answer_list.build_tsquery(" ".join("t%d" % i for i in range(20))).count(":*") == 8


# ── 5. paging and validation ──────────────────────────────────────────────────────────────

def test_5_validation_and_paging(client, pg):
    assert client.get("/answers?size=201").status_code == 422
    assert client.get("/answers?sort=sideways").status_code == 422
    assert client.get("/answers?page=0").status_code == 422
    assert not pg.get("calls")
    pg["rows"] = [_db_row()]
    client.get("/answers?page=3&size=10")
    sql, params = _sql(pg)
    assert params["offset"] == 20 and params["limit"] == 10
    assert "OFFSET %(offset)s" in sql
    assert "ORDER BY created_at DESC, id DESC" in sql
    client.get("/answers?sort=oldest")
    assert "ORDER BY created_at ASC, id ASC" in _sql(pg)[0]


# ── a fake Neo4j (read_row + the archive writer's transaction) ────────────────────────────

class _Neo:
    def __init__(self, row, archived_at=None):
        self.row = row
        self.node = {"archived_at": archived_at, "archive_history": []}
        self.cyphers: list = []
        self.writer_calls = 0

    def session(self):
        return _NeoSess(self)


class _NeoSess:
    def __init__(self, neo):
        self.n = neo

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, cypher, **params):
        self.n.cyphers.append(cypher)
        n = self.n

        class _R:
            def single(self_inner):
                return n.row

        return _R()

    def execute_write(self, fn):
        return fn(_Tx(self.n))


class _Tx:
    def __init__(self, neo):
        self.n = neo

    def run(self, cypher, **params):
        from iagent import answer_artifact_writer as w

        n = self.n
        n.cyphers.append(cypher)
        if cypher == w._ARCHIVE_STATE_CYPHER:
            n.writer_calls += 1

            class _R:
                def single(self_inner):
                    return {"archived_at": n.node["archived_at"]}

            return _R()
        assert cypher == w._ARCHIVE_SET_CYPHER
        n.node.update(archived_at=params["archived_at"], archived_by=params["archived_by"],
                      archive_reason=params["archive_reason"])
        n.node["archive_history"].append(params["entry"])
        return None


def _row(**over):
    base = {
        "id": "artifact-1", "status": "complete", "summary": "s", "question_text": "q",
        "valid_as_of": 1, "duration_ms": 2, "derived_from": None, "is_owner": True,
        "resolved_intent": json.dumps({"subject_uri": "u"}),
        "routing_inline": json.dumps({"about": {"uri": "u"}}),
        "rendered_output": json.dumps({"components": [{"archetype": "ANSWER_TEXT"}]}),
        "origin_owner_domain": None, "origin_program": None, "seeded_by": None,
    }
    base.update(over)
    return base


@pytest.fixture()
def neo(monkeypatch):
    import iagent.gateway as gw

    def _install(row, archived_at=None):
        n = _Neo(row, archived_at)
        monkeypatch.setattr(gw, "neo4j_driver", n)
        return n

    return _install


# ── 6. the body is entitled ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_6_body_is_entitled_and_artifacts_stays_bodyless(neo):
    import iagent.gateway as gw
    from fastapi import HTTPException

    neo(_row())
    body = await gw.get_answer_body("artifact-1", _User())
    assert set(body) == {"id", "rendered_output", "routing", "resolved_intent"}
    assert body["rendered_output"] == {"components": [{"archetype": "ANSWER_TEXT"}]}
    assert body["routing"] == {"about": {"uri": "u"}} and body["resolved_intent"] == {"subject_uri": "u"}
    art = await gw.get_artifact("artifact-1", _User())
    assert "rendered_output" not in art.model_dump(), "/artifacts/{id} grew a body"

    neo(_row(is_owner=False))
    with pytest.raises(HTTPException) as e_art:
        await gw.get_artifact("artifact-1", _User())
    with pytest.raises(HTTPException) as e_body:
        await gw.get_answer_body("artifact-1", _User())
    assert e_body.value.status_code == e_art.value.status_code == 404
    assert e_body.value.detail == e_art.value.detail


@pytest.mark.asyncio
async def test_6b_an_archived_answer_is_still_readable(neo):
    import iagent.gateway as gw

    neo(_row(), archived_at=123)
    assert (await gw.get_answer_body("artifact-1", _User()))["id"] == "artifact-1"


# ── 7. archive never deletes and is owner-only ────────────────────────────────────────────

def test_7_writer_statements_never_delete():
    from iagent import answer_artifact_writer as w

    for c in (w._ARCHIVE_STATE_CYPHER, w._ARCHIVE_SET_CYPHER):
        assert not re.search(r"\b(DELETE|DETACH|REMOVE)\b", c, re.I), c
    assert "a.watermark" in w._ARCHIVE_SET_CYPHER and "WatermarkSequence" in w._ARCHIVE_SET_CYPHER


def test_7_archive_then_unarchive_leaves_two_history_entries_and_a_repeat_none():
    from iagent import answer_artifact_writer as w

    n = _Neo(_row())
    assert w.set_archive_state(n, "artifact-1", archive=True, by=ALICE, reason="tidy") is True
    assert n.node["archived_at"] is not None and len(n.node["archive_history"]) == 1
    assert w.set_archive_state(n, "artifact-1", archive=True, by=ALICE, reason="again") is False
    assert len(n.node["archive_history"]) == 1, "a repeat archive appended history"
    assert w.set_archive_state(n, "artifact-1", archive=False, by=ALICE, reason=None) is True
    assert n.node["archived_at"] is None and n.node["archived_by"] is None
    hist = [json.loads(h) for h in n.node["archive_history"]]
    assert [h["action"] for h in hist] == ["archive", "unarchive"]
    assert set(hist[0]) == {"action", "by", "at", "reason"}


@pytest.mark.asyncio
async def test_7_only_the_owner_archives(neo, monkeypatch):
    import iagent.gateway as gw
    from fastapi import HTTPException

    # A caller who is ENTITLED but not the owner: the seeding delegate. The generic entitlement
    # helper admits it; the owner check is the only thing between it and the writer.
    monkeypatch.setattr(gw, "_delegate_principals", lambda: {"svc:seeder": frozenset()})
    n = neo(_row(is_owner=False, seeded_by="svc:seeder"))
    delegate = _User("c2222222-3333-4444-8555-666666666666", "svc:seeder")
    with pytest.raises(HTTPException) as e:
        await gw.archive_answer("artifact-1", gw.ArchiveRequest(reason="x"), delegate)
    assert e.value.status_code == 404 and n.writer_calls == 0, "a non-owner reached the writer"

    # and a caller who is simply unentitled gets the /artifacts status
    n = neo(_row(is_owner=False))
    with pytest.raises(HTTPException) as e2:
        await gw.archive_answer("artifact-1", gw.ArchiveRequest(reason="x"), _User())
    assert e2.value.status_code == 404 and n.writer_calls == 0


@pytest.mark.asyncio
async def test_7_owner_archive_is_idempotent_through_the_route(neo):
    import iagent.gateway as gw

    n = neo(_row())
    first = await gw.archive_answer("artifact-1", gw.ArchiveRequest(reason="tidy"), _User())
    again = await gw.archive_answer("artifact-1", gw.ArchiveRequest(reason="tidy"), _User())
    assert first["changed"] is True and again["changed"] is False
    assert len(n.node["archive_history"]) == 1
    assert n.node["archived_by"] == ALICE


def test_7_archive_reason_is_required_and_bounded(client):
    assert client.post("/answers/x/archive", json={}).status_code == 422
    assert client.post("/answers/x/archive", json={"reason": ""}).status_code == 422
    assert client.post("/answers/x/archive", json={"reason": "r" * 501}).status_code == 422


# ── 8. the projector carries the flag ─────────────────────────────────────────────────────

def _apply(art):
    from iagent.projector.apply_loop import ApplyLoop

    calls: list = []

    class _C:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def cursor(self):
            return _Cu()

        def commit(self):
            pass

    class _Cu(_C):
        def execute(self, sql, params=None):
            calls.append((sql, params))

    loop = ApplyLoop.__new__(ApplyLoop)
    loop._pg_connect = lambda: _C()
    loop._last_applied_watermark = 0
    loop._apply_count = 0
    loop._apply_one(art)
    return calls[0]


def _art(**over):
    base = {"id": "a1", "watermark": 5, "valid_as_of": 1, "status": "complete",
            "durability_status": "durable", "message_id": "m", "question_text": "q",
            "created_at": 1, "updated_at": 2}
    base.update(over)
    return base


def test_8_projector_upserts_the_archive_flag():
    sql, params = _apply(_art(archived_at=1788908472999, archived_by=ALICE, archive_reason="tidy"))
    assert params["archived_at"] == 1788908472999
    assert params["archived_by"] == ALICE and params["archive_reason"] == "tidy"
    head, _, tail = sql.partition("ON CONFLICT")
    assert "archived_at" in head and "archived_at = EXCLUDED.archived_at" in tail
    assert "archive_reason = EXCLUDED.archive_reason" in tail


def test_8b_an_unarchived_node_projects_null_so_unarchive_clears_the_row():
    _, params = _apply(_art())
    assert params["archived_at"] is None and params["archived_by"] is None


def test_8c_the_poll_reads_the_archive_properties_off_the_node():
    src = (_SRC / "iagent" / "projector" / "apply_loop.py").read_text(encoding="utf-8")
    for p in (".archived_at", ".archived_by", ".archive_reason"):
        assert p in src
    assert ".archive_history" not in src, "archive_history stays on the node"


# ── 9. migration ──────────────────────────────────────────────────────────────────────────

def _code(sql: str) -> str:
    return "\n".join(re.sub(r"--.*$", "", l) for l in sql.splitlines())


_GENERATED = re.compile(r"\bGENERATED\b", re.I)


def test_9_both_copies_carry_the_columns_and_indexes_and_are_identical():
    a = _SQL.read_bytes()
    assert a == _SQL_CHART.read_bytes(), "the chart copy drifted"
    t = a.decode("utf-8")
    for needle in ("ADD COLUMN IF NOT EXISTS archived_at BIGINT", "ADD COLUMN IF NOT EXISTS archived_by TEXT",
                   "ADD COLUMN IF NOT EXISTS archive_reason TEXT", "idx_aap_user_created",
                   "(produced_for_user_id, created_at DESC)", "idx_aap_search_tsv", "USING GIN"):
        assert needle in t, needle


def test_9a_no_generated_column_electric_refuses_to_replicate_it():
    # positive control: the matcher catches the 06-30 form
    old_form = ("ALTER TABLE t ADD COLUMN produced_for_user_id TEXT "
                "GENERATED ALWAYS AS (produced_for->>'user_id') STORED;")
    assert _GENERATED.search(_code(old_form))
    for p in (_SQL, _SQL_CHART):
        assert not _GENERATED.search(_code(p.read_text(encoding="utf-8"))), p


def _norm(e: str) -> str:
    return re.sub(r"\s+", "", e)


def test_9b_the_query_repeats_the_index_expression_exactly(client, pg):
    client.get("/answers", params={"q": "spend"})
    sql, _ = _sql(pg)
    m = re.search(r"(to_tsvector\(.*?\)) @@ to_tsquery", sql, re.S)
    assert m, "the search predicate is gone from the statement"
    idx = re.search(r"idx_aap_search_tsv\s+ON answer_artifact_projection USING GIN \((.*)\);",
                    _code(_SQL.read_text(encoding="utf-8")), re.S)
    assert idx, "the expression index is not in the migration"
    assert _norm(m.group(1)) == _norm(idx.group(1)), (m.group(1), idx.group(1))


# ── 10. electric ──────────────────────────────────────────────────────────────────────────

async def _proxy_where(monkeypatch, table):
    import httpx

    import iagent.gateway as gw

    seen = {}

    class _Resp:
        headers = {}
        content = b"[]"
        status_code = 200

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, params=None):
            seen.update(params)
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    class _Req:
        class query_params:
            @staticmethod
            def multi_items():
                return [("table", table)] if table else []

    await gw.electric_shape_proxy(_Req(), _User())
    return seen["where"]


@pytest.mark.asyncio
async def test_10_electric_default_view_hides_archived(monkeypatch):
    where = await _proxy_where(monkeypatch, "answer_artifact_projection")
    assert where == f"produced_for_user_id = '{ALICE}' AND archived_at IS NULL"
    assert "archived_at" in await _proxy_where(monkeypatch, None)
    assert "archived_at" not in await _proxy_where(monkeypatch, "human_task_projection")
