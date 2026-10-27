"""A frontend's render menu survives a graph wipe (architect ruling Q9, 2026-10-19).

"A render menu is a registration like an engine's, and registrations survive prime. The BFF
persists cortex's menu and replays it after any wipe; the login-time post becomes a no-op when
the stored menu matches."

Arms: STORE (SQL shape, twin, unset DSN, a fault is an answer), ROUTE (first post emits and
saves; identical post with the graph holding it is a no-op; wiped graph / unreachable graph /
changed menu / changed version all emit; a save fault does not fail the registration), REPLAY
(emits stored menus absent from the graph, skips present ones, retries while the graph is
unreachable, never raises).
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

httpx = pytest.importorskip("httpx")
pytest.importorskip("fastapi")

from src.iagent import frontend_menu_store as fms  # noqa: E402
from src.iagent import gateway  # noqa: E402

N = 3
FID = "cortex-ui-test"


# ── STORE ──────────────────────────────────────────────────────────────────────────────────────

class Cur:
    def __init__(self, log, rows=None):
        self.log, self.rows = log, rows or []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.log.append((sql, params))

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class Conn:
    def __init__(self, log, rows=None):
        self.log, self.rows = log, rows

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return Cur(self.log, self.rows)

    def commit(self):
        self.log.append(("COMMIT", None))


def test_save_is_an_upsert_keyed_on_frontend_id_and_touches_no_other_table():
    log: list = []
    store = fms.PgFrontendMenuStore(connect=lambda: Conn(log))
    out = store.save(FID, "v1", [{"subject_uri": "a"}], registered_by="u", registered_at=5)
    assert out == {"ok": True}
    sqls = [s for s, _ in log if s != "COMMIT"]
    upsert = [s for s in sqls if "INSERT INTO frontend_menu" in s]
    assert len(upsert) == 1 and "ON CONFLICT (frontend_id) DO UPDATE" in upsert[0]
    for s in sqls:
        assert "UPDATE" not in s.replace("DO UPDATE SET", ""), s
        assert "DELETE" not in s.upper()
        for table in ("document_decision_record", "human_task_projection"):
            assert table not in s
    params = [p for s, p in log if "INSERT INTO frontend_menu" in s][0]
    assert params[0] == FID and params[1] == "v1" and params[2] == fms.menu_digest([{"subject_uri": "a"}])[1]


def test_the_sql_twin_mirrors_the_migration_that_runs():
    twin = Path(__file__).resolve().parents[1] / "sql" / "create_frontend_menu.sql"
    body = "\n".join(l for l in twin.read_text(encoding="utf-8").splitlines()
                     if not l.startswith("--")).strip()
    assert body == fms._MIGRATION_SQL.strip()


def test_an_unset_dsn_is_not_configured_and_refuses_to_connect(monkeypatch):
    monkeypatch.setattr(fms, "_PG_DSN", "")
    assert fms.configured() is False
    with pytest.raises(RuntimeError):
        fms._pg_connect()
    # and the store, built on the default connect, answers rather than raises
    store = fms.PgFrontendMenuStore()
    assert store.save(FID, "", [], registered_by="u", registered_at=1) == {
        "ok": False, "reason": "unreachable"}
    assert store.load(FID) is None and store.load_all() == []


def test_a_store_fault_is_an_answer_never_a_raise():
    def boom():
        raise OSError("down")
    store = fms.PgFrontendMenuStore(connect=boom)
    assert store.save(FID, "v", [], registered_by="u", registered_at=1) == {
        "ok": False, "reason": "unreachable"}
    assert store.load(FID) is None
    assert store.load_all() == []


def test_load_round_trips_the_canonical_menu():
    menu = [{"subject_uri": "a", "archetype": "X"}]
    text, sha = fms.menu_digest(menu)
    row = (FID, "v1", sha, text, "u", 7)
    store = fms.PgFrontendMenuStore(connect=lambda: Conn([], [row]))
    got = store.load(FID)
    assert got["menu"] == menu and got["menu_sha256"] == sha and got["frontend_version"] == "v1"
    assert store.load_all()[0]["frontend_id"] == FID


# ── ROUTE ──────────────────────────────────────────────────────────────────────────────────────

def _user():
    return type("U", (), {"authz_id": "alice@example.com", "id": "alice@example.com",
                          "sub": "alice@example.com", "email": "alice@example.com",
                          "persona": None, "entitled_domains": [],
                          "is_authenticated": True})()


def _body(n=N, version="t1", prefix="mesh:Subject"):
    return {
        "frontend_id": FID,
        "frontend_version": version,
        "capabilities": [
            {"archetype": "KNOWLEDGE_DOCUMENT", "subject_uri": f"{prefix}{i}",
             "object_uri": "mesh:KnowledgeDocument"}
            for i in range(n)
        ],
    }


class FakeStore:
    def __init__(self, save_ok=True):
        self.rows: dict = {}
        self.saves = 0
        self.save_ok = save_ok

    def load(self, fid):
        return self.rows.get(fid)

    def load_all(self):
        return list(self.rows.values())

    def save(self, fid, ver, admitted, *, registered_by, registered_at):
        self.saves += 1
        if not self.save_ok:
            return {"ok": False, "reason": "unreachable"}
        _, sha = fms.menu_digest(admitted)
        self.rows[fid] = {"frontend_id": fid, "frontend_version": ver or "",
                          "menu_sha256": sha, "menu": admitted,
                          "registered_by": registered_by, "registered_at": registered_at}
        return {"ok": True}


class World:
    """The graph, the registrar emitter and the store, all stubbed."""

    def __init__(self):
        self.store = FakeStore()
        self.graph = {}          # entries dict, or None when unreachable
        self.emits: list = []

    def graph_holds(self, admitted_caps, version):
        self.graph = {FID: {"versions": {version or "": {"capabilities": [
            {"subject_uri": c["subject_uri"], "archetype": c["archetype"]}
            for c in admitted_caps]}}}}

    def emit(self, registrar_url, frontend_id, frontend_version, admitted):
        self.emits.append((frontend_id, frontend_version, [c["subject_uri"] for c in admitted]))
        return len(admitted), []


@pytest.fixture
def world(monkeypatch):
    w = World()
    monkeypatch.setenv("MESH_REGISTRAR_URL", "http://registrar.invalid")
    monkeypatch.setattr(gateway, "_frontend_menu_store", lambda: w.store)
    monkeypatch.setattr(gateway, "_fetch_graph_entries", lambda: w.graph)
    monkeypatch.setattr(gateway, "_emit_menu_to_registrar", w.emit)
    gateway.app.dependency_overrides[gateway.get_current_user] = _user
    yield w
    gateway.app.dependency_overrides.clear()


def _post(body):
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app),
                                     base_url="http://t") as c:
            return await c.post("/register_frontend_capabilities", json=body)
    return asyncio.run(run())


def _admitted_of(body):
    from agent_fleet.presentation_agent.capability_admission import validate_registration
    return validate_registration(body["capabilities"])[0]


def test_a_first_post_emits_and_saves(world):
    world.graph = {}
    r = _post(_body())
    assert r.status_code == 200 and r.json()["accepted"] == N and r.json()["unchanged"] is False
    assert len(world.emits) == 1 and len(world.emits[0][2]) == N
    assert world.store.saves == 1 and FID in world.store.rows


def test_an_identical_post_with_the_graph_holding_it_is_a_no_op(world):
    world.graph = {}
    body = _body()
    _post(body)
    world.graph_holds(_admitted_of(body), "t1")
    world.emits.clear()
    r = _post(body)
    assert r.status_code == 200
    assert r.json()["unchanged"] is True and r.json()["accepted"] == N
    assert world.emits == []
    assert world.store.saves == 1


def test_an_identical_post_after_a_wipe_emits_again(world):
    body = _body()
    world.graph = {}
    _post(body)
    world.graph = {}            # the wipe: the row survives, the graph does not
    world.emits.clear()
    r = _post(body)
    assert r.json()["unchanged"] is False and r.json()["accepted"] == N
    assert len(world.emits) == 1


def test_an_unreachable_graph_is_not_a_no_op(world):
    body = _body()
    world.graph = {}
    _post(body)
    world.graph = None
    world.emits.clear()
    r = _post(body)
    assert r.json()["unchanged"] is False
    assert len(world.emits) == 1


def test_a_changed_menu_emits_and_saves_the_new_digest(world):
    body = _body()
    world.graph = {}
    _post(body)
    old_sha = world.store.rows[FID]["menu_sha256"]
    world.graph_holds(_admitted_of(body), "t1")
    world.emits.clear()
    r = _post(_body(n=N + 1))
    assert r.json()["unchanged"] is False and r.json()["accepted"] == N + 1
    assert len(world.emits) == 1
    assert world.store.rows[FID]["menu_sha256"] != old_sha
    assert world.store.saves == 2


def test_a_menu_changed_in_content_only_emits_though_the_graph_holds_every_key(world):
    # same (subject, archetype) keys, different content: only the digest can tell
    body = _body()
    world.graph = {}
    _post(body)
    world.graph_holds(_admitted_of(body), "t1")
    world.emits.clear()
    changed = _body()
    for c in changed["capabilities"]:
        c["persona_fit"] = ["someone-new"]
    r = _post(changed)
    assert r.json()["unchanged"] is False
    assert len(world.emits) == 1


def test_a_partially_wiped_graph_is_not_held(world):
    body = _body()
    world.graph = {}
    _post(body)
    world.graph_holds(_admitted_of(body)[:1], "t1")   # one of N survived
    world.emits.clear()
    r = _post(body)
    assert r.json()["unchanged"] is False
    assert len(world.emits) == 1


def test_a_version_change_with_the_same_capabilities_emits(world):
    body = _body(version="t1")
    world.graph = {}
    _post(body)
    # the graph holds the new version too, and the digest is equal: only the stored version differs
    world.graph_holds(_admitted_of(body), "t2")
    world.emits.clear()
    r = _post(_body(version="t2"))
    assert r.json()["unchanged"] is False
    assert len(world.emits) == 1
    assert world.store.rows[FID]["frontend_version"] == "t2"


def test_a_save_fault_does_not_fail_the_registration(world, caplog):
    world.store.save_ok = False
    world.graph = {}
    with caplog.at_level("ERROR"):
        r = _post(_body())
    assert r.status_code == 200 and r.json()["accepted"] == N
    assert len(world.emits) == 1
    assert any("frontend_menu_save_failed" in rec.getMessage() for rec in caplog.records)


def test_coverage_is_keyed_by_subject_and_archetype_not_count():
    adm = [{"subject_uri": "a", "archetype": "X"}, {"subject_uri": "b", "archetype": "X"}]
    ent = lambda caps: {FID: {"versions": {"v": {"capabilities": caps}}}}  # noqa: E731
    assert gateway._graph_holds_menu(ent(adm), FID, "v", adm) is True
    swapped = [adm[0], {"subject_uri": "zzz", "archetype": "X"}]
    assert gateway._graph_holds_menu(ent(swapped), FID, "v", adm) is False
    assert gateway._graph_holds_menu(None, FID, "v", adm) is False
    assert gateway._graph_holds_menu({}, FID, "v", adm) is False
    assert gateway._graph_holds_menu(ent(adm), FID, "other", adm) is False


def _held(*pairs):
    caps = [{"subject_uri": u, "archetype": a} for u, a in pairs]
    return {FID: {"versions": {"v": {"capabilities": caps}}}}


FIN = "http://invincible-agent/fin#"


def test_a_curie_post_is_held_by_the_expanded_graph_row_and_the_reverse():
    from agent_fleet.presentation_agent.capabilities import canonical_iri_for_lookup
    assert canonical_iri_for_lookup("fin:BurnRateSeries") == FIN + "BurnRateSeries"
    curie = [{"subject_uri": "fin:BurnRateSeries", "archetype": "MULTI_SERIES"}]
    full = [{"subject_uri": FIN + "BurnRateSeries", "archetype": "MULTI_SERIES"}]
    assert gateway._graph_holds_menu(_held((FIN + "BurnRateSeries", "MULTI_SERIES")),
                                     FID, "v", curie) is True
    assert gateway._graph_holds_menu(_held(("fin:BurnRateSeries", "MULTI_SERIES")),
                                     FID, "v", full) is True


def test_canonicalising_does_not_widen_a_different_name_or_archetype():
    curie = [{"subject_uri": "fin:BurnRateSeries", "archetype": "MULTI_SERIES"}]
    assert gateway._graph_holds_menu(_held((FIN + "Other", "MULTI_SERIES")),
                                     FID, "v", curie) is False
    assert gateway._graph_holds_menu(_held((FIN + "BurnRateSeries", "KPI")),
                                     FID, "v", curie) is False


def test_an_unknown_prefix_matches_only_itself_verbatim():
    from agent_fleet.presentation_agent.capabilities import canonical_iri_for_lookup
    assert canonical_iri_for_lookup("zz:Thing") == "zz:Thing"
    adm = [{"subject_uri": "zz:Thing", "archetype": "X"}]
    assert gateway._graph_holds_menu(_held(("zz:Thing", "X")), FID, "v", adm) is True
    assert gateway._graph_holds_menu(_held(("http://invincible-agent/zz#Thing", "X")),
                                     FID, "v", adm) is False


def _expanded_graph(w, body, version):
    w.graph = {FID: {"versions": {version: {"capabilities": [
        {"subject_uri": c["subject_uri"].replace("fin:", FIN, 1), "archetype": c["archetype"]}
        for c in body["capabilities"]]}}}}


def test_an_identical_post_is_unchanged_when_the_graph_holds_the_expanded_form(world):
    world.graph = {}
    body = _body(prefix="fin:Subject")
    _post(body)
    _expanded_graph(world, body, "t1")
    world.emits.clear()
    r = _post(body)
    assert r.status_code == 200
    assert r.json()["unchanged"] is True and r.json()["accepted"] == N
    assert world.emits == []


# ── REPLAY ─────────────────────────────────────────────────────────────────────────────────────

def _stored(w, fid=FID, version="t1", n=N):
    body = _body(n=n, version=version)
    adm = _admitted_of(body)
    w.store.save(fid, version, adm, registered_by="u", registered_at=1)
    return adm


def test_replay_emits_a_stored_menu_the_graph_lacks(world):
    _stored(world)
    world.graph = {}
    assert gateway._replay_frontend_menus_once() is True
    assert len(world.emits) == 1 and world.emits[0][0] == FID


def test_replay_skips_a_menu_the_graph_already_holds(world):
    adm = _stored(world)
    world.graph_holds(adm, "t1")
    assert gateway._replay_frontend_menus_once() is True
    assert world.emits == []


def test_replay_asks_for_a_retry_while_the_graph_is_unreachable(world):
    _stored(world)
    world.graph = None
    assert gateway._replay_frontend_menus_once() is False
    assert world.emits == []


def test_replay_retries_until_the_graph_answers_then_emits(world, monkeypatch):
    _stored(world)
    answers = [None, None, {}]
    monkeypatch.setattr(gateway, "_fetch_graph_entries", lambda: answers.pop(0))
    monkeypatch.setattr(gateway, "_FRONTEND_MENU_REPLAY_DELAYS", (0, 0, 0, 0, 0))
    asyncio.run(gateway._replay_frontend_menus())
    assert answers == [] and len(world.emits) == 1


def test_replay_gives_up_loudly_and_never_raises(world, monkeypatch, caplog):
    _stored(world)

    def boom():
        raise RuntimeError("graph exploded")
    monkeypatch.setattr(gateway, "_fetch_graph_entries", boom)
    monkeypatch.setattr(gateway, "_FRONTEND_MENU_REPLAY_DELAYS", (0, 0))
    with caplog.at_level("WARNING"):
        asyncio.run(gateway._replay_frontend_menus())
    assert any("frontend_menu_replay_gave_up" in r.getMessage() for r in caplog.records)


def test_replay_registers_the_stored_menu_in_process(world, monkeypatch):
    from agent_fleet.presentation_agent import capability_registry as reg
    seen = []
    monkeypatch.setattr(reg, "register", lambda fid, ver, menu: seen.append((fid, ver, len(menu))))
    _stored(world, fid="replay-fe")
    world.graph = {}
    gateway._replay_frontend_menus_once()
    assert seen == [("replay-fe", "t1", N)]


def test_replay_skips_a_menu_whose_graph_copy_is_in_expanded_form(world):
    body = _body(prefix="fin:Subject")
    world.store.save(FID, "t1", _admitted_of(body), registered_by="u", registered_at=1)
    _expanded_graph(world, body, "t1")
    assert gateway._replay_frontend_menus_once() is True
    assert world.emits == []
