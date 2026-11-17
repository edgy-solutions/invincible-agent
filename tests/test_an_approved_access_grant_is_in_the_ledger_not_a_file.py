"""An approved access request no longer writes a file in the pod (architect, 2026-11-15).

The grant is recorded in the decision ledger (requester, approver, time, reason), applied to the
directory FROM that record, and re-applied from the ledger at startup. A report lists the grants
that enforce but are not in committed policy. Doubles only: a fake ledger store and a replaced
`grant_sync` seam, so no test here writes the directory.

  1. RECORD     the row names BOTH people, the time and the reason; no file is written or changed.
  2. RESTART    a fresh process (empty directory, same ledger) re-applies the approved grant.
  3. TRAVEL     the ledger travels with committed policy (the sync prunes what it does not name).
  4. FIRST      a second approval of the same grant keeps the first approver on record.
  5. REPORT     grants absent from committed policy are listed, in the ledger and in the directory.
  6. NO RECORD  a store that cannot record the grant applies nothing.
  7. SOURCE     the writer holds no file write; the gateway names the requester and re-applies.
  8. ADD-ONLY   the BFF never prunes (one pruner, the seed).
  9. REVOKE     a revocation is a row, never a deletion; the grant it names is gone after the next
                sync and stays gone; both acts stay on record; who may revoke is a capability row.
 10. EXISTS     an approval that names an asset the directory lacks is refused, nothing recorded.
 11. DANGLING   a ledger row whose asset has since gone is skipped alone and reported.
 12. STREAMS    two applies at once keep their own output (no process-stream redirect).
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

pytest.importorskip("psycopg2")
from src.iagent import human_tasks as ht  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
COMMITTED = "grants:\n- subject: carol\n  asset: asset-c\n  granted_by: cnogradi\n  reason: seed\n"


class FakeLedgerDb:
    """Stands for the Postgres `access_grant_ledger`: the same keys, ON CONFLICT DO NOTHING."""

    def __init__(self):
        self.rows: dict = {}
        self.down = False
        self.prunes: list = []          # the `prune` each directory apply was called with
        self.missing: set = set()       # assets the directory does not have

    def __call__(self):
        if self.down:
            raise RuntimeError("ledger store down")
        return _Conn(self)


class _Conn:
    def __init__(self, db): self.db = db
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def cursor(self, **k): return _Cur(self.db)
    def commit(self): pass


class _Cur:
    def __init__(self, db): self.db, self.rowcount, self._out = db, 0, []
    def __enter__(self): return self
    def __exit__(self, *a): return False

    def execute(self, sql, params=()):
        if "INSERT INTO access_grant_ledger" in sql:
            key = tuple(params[:4])         # (subject, asset, kind, entry)
            if key in self.db.rows:
                self.rowcount = 0
            else:
                self.db.rows[key] = tuple(params)
                self.rowcount = 1
        elif "FROM access_grant_ledger" in sql:
            self._out = sorted(self.db.rows.values(), key=lambda r: (r[8], r[0], r[1]))
        # `CREATE TABLE` and anything else: nothing to do

    def fetchall(self): return list(self._out)


@pytest.fixture
def world(tmp_path, monkeypatch):
    policy = tmp_path / "policy"
    policy.mkdir()
    committed = policy / "asset_grants.yaml"
    committed.write_text(COMMITTED, encoding="utf-8")
    db = FakeLedgerDb()
    sent: list = []
    monkeypatch.setattr(ht, "_ASSET_GRANTS_FILE", str(committed))
    monkeypatch.setattr(ht, "_TOPAZ_DIRECTORY_URL", "http://directory.invalid")
    monkeypatch.setattr(ht, "_pg_connect", db)
    monkeypatch.setattr(ht, "_GRANT_SYNC", str(ROOT / "policy" / "sync" / "grant_sync.py"))
    # `prune` defaults to True HERE, so a call that forgets to say add-only records True (red)
    monkeypatch.setattr(ht, "_grant_sync_run",
                        lambda raw, prune=True, **kw: sent.append(raw) or db.prunes.append(prune) or 0)
    monkeypatch.setattr(ht, "asset_exists", lambda asset, kind="dataset": asset not in db.missing)
    return db, sent, committed, policy


def _approve(**over):
    kw = dict(subject="alice", asset="asset-a", granted_by="bob", reason="needs it",
              requested_by="alice", task_id="access-1")
    kw.update(over)
    return ht.write_grant_and_sync(**kw)


# 1. record ------------------------------------------------------------------------------------

def test_1_the_record_names_requester_and_approver_with_time_and_reason(world):
    db, sent, _c, _p = world
    out = _approve(requested_by="req-person", granted_by="approver-person", reason="because")
    assert out["ok"]
    (row,) = ht.ledger_grants()
    assert row["requested_by"] == "req-person" and row["granted_by"] == "approver-person"
    assert row["subject"] == "alice" and row["asset"] == "asset-a" and row["reason"] == "because"
    assert row["task_id"] == "access-1" and row["granted_at"] > 0


def test_1_no_file_is_written_or_changed(world):
    _db, sent, committed, policy = world
    before = committed.read_bytes()
    _approve()
    assert committed.read_bytes() == before
    assert sorted(p.name for p in policy.iterdir()) == ["asset_grants.yaml"]
    assert sent and {"subject": "alice", "asset": "asset-a", "kind": "dataset",
                     "granted_by": "bob", "reason": "needs it"} in sent[-1]["grants"]


def test_1_control_the_record_is_refused_without_a_requester_or_approver(world):
    for bad in ({"requested_by": " "}, {"granted_by": ""}):
        with pytest.raises(ValueError):
            ht.record_grant(**{**dict(subject="a", asset="b", requested_by="r", granted_by="g",
                                      reason=""), **bad})


def test_1_the_audit_line_arrives_naming_both_people(world, caplog):
    caplog.set_level(logging.INFO, logger="iagent.audit.grant_write")
    _approve(requested_by="req-person", granted_by="approver-person")
    (line,) = [r.getMessage() for r in caplog.records if r.name == "iagent.audit.grant_write"]
    assert "granted_by=approver-person" in line and "requested_by=req-person" in line


# 2. restart -----------------------------------------------------------------------------------

def test_2_a_restart_keeps_an_approved_grant(world):
    db, sent, _c, _p = world
    _approve()
    sent.clear()                                  # the pod restarts: the directory has lost it
    out = ht.reapply_ledger_grants()
    assert out["ok"] and len(sent) == 1
    assert ("alice", "asset-a") in {(g["subject"], g["asset"]) for g in sent[0]["grants"]}


def test_2_control_an_empty_ledger_re_applies_nothing(world):
    _db, sent, _c, _p = world
    assert ht.reapply_ledger_grants()["skipped"] == "empty ledger" and sent == []


def test_2_control_no_directory_configured_re_applies_nothing(world, monkeypatch):
    _db, sent, _c, _p = world
    _approve()
    sent.clear()
    monkeypatch.setattr(ht, "_TOPAZ_DIRECTORY_URL", "")
    assert ht.reapply_ledger_grants()["skipped"] == "no directory" and sent == []


# 3. travel ------------------------------------------------------------------------------------

def test_3_the_ledger_travels_with_committed_policy(world):
    _db, sent, _c, _p = world
    _approve()
    keys = {(g["subject"], g["asset"]) for g in sent[-1]["grants"]}
    assert keys == {("carol", "asset-c"), ("alice", "asset-a")}     # nothing committed is pruned


def test_3_committed_policy_wins_a_duplicate(world):
    _db, sent, _c, _p = world
    _approve(subject="carol", asset="asset-c", granted_by="someone-else")
    (g,) = [g for g in sent[-1]["grants"] if g["subject"] == "carol"]
    assert g["granted_by"] == "cnogradi"


# 4. first -------------------------------------------------------------------------------------

def test_4_a_second_approval_keeps_the_first_approver(world):
    _approve(granted_by="first")
    _approve(granted_by="second")
    (row,) = ht.ledger_grants()
    assert row["granted_by"] == "first"


# 5. report ------------------------------------------------------------------------------------

def test_5_the_report_lists_ledger_and_directory_grants_absent_from_policy(world):
    _approve()
    live = {("carol", "asset-c", "dataset"), ("alice", "asset-a", "dataset"),
            ("mallory", "asset-m", "dataset")}
    rep = ht.grants_absent_from_policy(live)
    assert [(r["subject"], r["asset"]) for r in rep["ledger"]] == [("alice", "asset-a")]
    assert rep["directory"] == [("mallory", "asset-m", "dataset")]


def test_5_control_a_grant_in_committed_policy_is_not_reported(world):
    _approve(subject="carol", asset="asset-c")
    assert ht.grants_absent_from_policy({("carol", "asset-c", "dataset")}) == {
        "ledger": [], "directory": []}


# 6. no record ---------------------------------------------------------------------------------

def test_6_a_store_that_cannot_record_the_grant_applies_nothing(world):
    db, sent, _c, _p = world
    db.down = True
    with pytest.raises(RuntimeError):
        _approve()
    assert sent == []


# 7. source ------------------------------------------------------------------------------------

def _body(src, start, end):
    return src[src.index(start):src.index(end)]


def test_7_the_writer_holds_no_file_write_and_no_subprocess():
    src = (ROOT / "src" / "iagent" / "human_tasks.py").read_text(encoding="utf-8")
    body = _body(src, "def record_grant(", "def get_task_resolution(")
    for banned in ("safe_dump", "open(_ASSET_GRANTS_FILE, \"w\"", "subprocess", "\"w\")"):
        assert banned not in body, banned
    assert body.count("open(") == 1                      # the one READ of committed policy


def test_7_the_gateway_names_the_requester_and_re_applies_at_startup():
    src = (ROOT / "src" / "iagent" / "gateway.py").read_text(encoding="utf-8")
    assert 'requested_by=str(match.get("requested_by") or subject)' in src
    assert "human_tasks.reapply_ledger_grants" in src


def test_7_the_cli_and_the_in_process_apply_are_one_function():
    import sys
    sys.path.insert(0, str(ROOT / "policy" / "sync"))
    import grant_sync
    assert grant_sync.run({"grants": [{"subject": "a", "asset": "b"}]}, "http://x.invalid") == 2
    assert "return run(raw, topaz_url)" in (ROOT / "policy" / "sync" / "grant_sync.py").read_text(
        encoding="utf-8")


def test_4_the_insert_is_do_nothing_on_conflict_in_the_real_sql():
    assert "ON CONFLICT (subject, asset, kind, entry) DO NOTHING" in ht._GRANT_INSERT_SQL
    assert "PRIMARY KEY (subject, asset, kind, entry)" in ht._GRANT_LEDGER_SQL


def test_5_the_report_script_prints_both_people_and_exits_1_while_anything_is_absent(
        world, monkeypatch, capsys):
    import importlib.util
    _approve(requested_by="req-person", granted_by="approver-person")
    spec = importlib.util.spec_from_file_location("report_access_grants",
                                                  ROOT / "scripts" / "report_access_grants.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setenv("TOPAZ_DIRECTORY_URL", "http://directory.invalid")
    monkeypatch.setattr(mod, "_live", lambda url: {("carol", "asset-c", "dataset"),
                                                    ("mallory", "asset-m", "dataset")})
    assert mod.main() == 1
    out = capsys.readouterr().out
    assert "asked by req-person, approved by approver-person" in out and "mallory" in out
    assert "carol" not in out                              # committed policy: not reported


# 8. add-only: the BFF is never the pruner (ruled 2026-11-16) ------------------------------------

def test_8_the_approval_apply_and_the_startup_re_apply_are_add_only(world):
    db, sent, _c, _p = world
    _approve()
    assert db.prunes == [False]                              # approval path
    ht.reapply_ledger_grants()
    assert db.prunes == [False, False]                       # startup path


def _load_grant_sync():
    import importlib.util
    import sys
    sys.path.insert(0, str(ROOT / "policy" / "sync"))
    spec = importlib.util.spec_from_file_location("_gs_seal", ROOT / "policy" / "sync" / "grant_sync.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_gs_seal"] = mod
    spec.loader.exec_module(mod)
    return mod


def _stub_run_world(mod, monkeypatch, seen):
    import topaz_sync

    class _Client:
        def __init__(self, url): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False

    class _Plan:
        add_relations: list = []
        del_relations: list = []

    monkeypatch.setattr(topaz_sync, "TopazClient", _Client)
    monkeypatch.setattr(mod, "find_dangling", lambda c, g, **kw: [])
    monkeypatch.setattr(mod, "sync_grants", lambda c, g, *, prune=True: seen.append(prune) or _Plan())
    monkeypatch.setattr(mod, "readback_grants", lambda c, g: (0, 0))


RAW = {"grants": [{"subject": "a", "asset": "b", "granted_by": "g"}]}


def test_8_run_passes_prune_through_to_the_sync(monkeypatch):
    mod, seen = _load_grant_sync(), []
    _stub_run_world(mod, monkeypatch, seen)
    assert mod.run(RAW, "http://x.invalid", prune=False) == 0
    assert seen == [False]


def test_8_control_the_seed_cli_still_prunes(monkeypatch, tmp_path):
    mod, seen = _load_grant_sync(), []
    _stub_run_world(mod, monkeypatch, seen)
    import yaml
    f = tmp_path / "g.yaml"
    f.write_text(yaml.safe_dump(RAW), encoding="utf-8")
    monkeypatch.setenv("ASSET_GRANTS_FILE", str(f))
    assert mod.main() == 0
    assert seen == [True]                                    # the one pruner


def test_8_the_real_seam_calls_run_add_only(monkeypatch, tmp_path):
    fake = tmp_path / "fake_gs.py"
    fake.write_text(
        "SEEN = []; run = lambda raw, url, prune=True, **kw: (SEEN.append(prune), 0)[1]",
        encoding="utf-8")
    import importlib.util
    monkeypatch.setattr(ht, "_GRANT_SYNC", str(fake))
    captured = []
    real = importlib.util.module_from_spec

    def spy(spec):
        m = real(spec)
        captured.append(m)
        return m
    monkeypatch.setattr(importlib.util, "module_from_spec", spy)
    assert ht._grant_sync_run(RAW) == 0
    assert captured[-1].SEEN == [False]


# 9. revoke ------------------------------------------------------------------------------------
# Revocation is RECORDED, never a deletion (architect, 2026-11-16). Effective access = committed
# policy + ledger grants - ledger revocations; the ledger is append-only.

def _revoke(**over):
    kw = dict(subject="alice", asset="asset-a", revoked_by="rev-person", reason="left the team")
    kw.update(over)
    return ht.record_revocation(**kw)


def _keys(grants):
    return {(g["subject"], g["asset"]) for g in grants}


def test_9_a_revocation_is_a_row_naming_the_revoker_the_time_and_the_reason(world):
    _approve()
    assert _revoke() is True
    grant, revoke = ht.ledger_entries()
    assert grant["entry"] == "grant" and grant["granted_by"] == "bob"          # untouched
    assert revoke["entry"] == "revoke" and revoke["granted_by"] == "rev-person"
    assert revoke["reason"] == "left the team" and revoke["granted_at"] > 0
    assert (revoke["subject"], revoke["asset"], revoke["kind"]) == ("alice", "asset-a", "dataset")


def test_9_the_revoked_grant_is_gone_after_the_next_sync_and_stays_gone(world):
    db, sent, _c, _p = world
    _approve()
    _approve(subject="dave", asset="asset-d")
    assert ("alice", "asset-a") in _keys(sent[-1]["grants"])
    _revoke()
    for apply in (ht.apply_ledger_to_directory, ht.reapply_ledger_grants,
                  lambda: _approve(subject="erin", asset="asset-e")):
        sent.clear()
        apply()
        assert ("alice", "asset-a") not in _keys(sent[-1]["grants"])     # gone, and stays gone
    # the record of BOTH acts remains: nothing was deleted or rewritten
    assert [(r["entry"], r["subject"]) for r in ht.ledger_entries()
            if r["subject"] == "alice"] == [("grant", "alice"), ("revoke", "alice")]


def test_9_control_the_other_grants_stay(world):
    _db, sent, _c, _p = world
    _approve()
    _approve(subject="dave", asset="asset-d")
    _revoke()
    sent.clear()
    ht.apply_ledger_to_directory()
    assert _keys(sent[-1]["grants"]) == {("carol", "asset-c"), ("dave", "asset-d")}


def test_9_a_committed_grant_is_revoked_by_a_row_too(world):
    _db, sent, committed, _p = world
    before = committed.read_bytes()
    _revoke(subject="carol", asset="asset-c")
    ht.apply_ledger_to_directory()
    assert ("carol", "asset-c") not in _keys(sent[-1]["grants"])
    assert committed.read_bytes() == before                  # no file was changed to do it


def test_9_a_later_approval_does_not_revive_a_revoked_grant(world):
    _db, sent, _c, _p = world
    _approve()
    _revoke()
    _approve(granted_by="someone-else")                       # same grant, approved again
    assert ("alice", "asset-a") not in _keys(sent[-1]["grants"])
    assert len([r for r in ht.ledger_entries() if r["entry"] == "grant"]) == 1   # no new row


def test_9_a_second_revocation_keeps_the_first_revoker(world):
    _approve()
    assert _revoke(revoked_by="first") is True
    assert _revoke(revoked_by="second") is False
    (row,) = [r for r in ht.ledger_entries() if r["entry"] == "revoke"]
    assert row["granted_by"] == "first"


def test_9_control_a_grant_that_is_not_in_effect_cannot_be_revoked(world):
    with pytest.raises(ht.NoSuchGrant):
        _revoke(subject="nobody", asset="asset-z")
    assert ht.ledger_entries() == []                          # nothing written


def test_9_control_a_revocation_needs_a_revoker_and_a_reason(world):
    _approve()
    for bad in ({"revoked_by": " "}, {"reason": ""}):
        with pytest.raises(ValueError):
            _revoke(**bad)
    assert [r["entry"] for r in ht.ledger_entries()] == ["grant"]


def test_9_the_report_does_not_list_a_revoked_grant_as_enforcing(world):
    _approve()
    assert [r["subject"] for r in ht.grants_absent_from_policy()["ledger"]] == ["alice"]
    _revoke()
    assert ht.grants_absent_from_policy()["ledger"] == []


def test_9_the_seed_and_the_bff_compute_the_effective_set_with_one_function(world):
    src = (ROOT / "src" / "iagent" / "human_tasks.py").read_text(encoding="utf-8")
    body = _body(src, "def desired_grants(", "def _grant_sync_run(")
    assert "union_grants(" in body                            # the grant_sync function, not a copy
    assert "revoke" not in body.replace("revocations", "")    # the rule is not restated here


def test_9_who_may_revoke_is_a_capability_row_and_the_code_names_no_group():
    import yaml
    rows = yaml.safe_load((ROOT / "policy" / "capability_grants.yaml").read_text(
        encoding="utf-8"))["capabilities"]
    row = rows["mesh:revokeAccessGrant"]
    assert row["granted_by"] and row["reason"] and row["grant_to_groups"]
    assert "grant_to" not in row                              # a group, never a person
    src = (ROOT / "src" / "iagent" / "gateway.py").read_text(encoding="utf-8")
    assert '_MESH_REVOKE_ACCESS = "mesh:revokeAccessGrant"' in src
    for group in row["grant_to_groups"]:
        assert group not in src                               # config names the case, not code


# the route, through TestClient

@pytest.fixture
def route(world, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from src.iagent import gateway
    state = {"allowed": True}
    monkeypatch.setattr(ht, "check_can_invoke", lambda cap, who: state.update(asked=(cap, who))
                        or state["allowed"])
    user = type("U", (), {"authz_id": "rev-person", "id": "rev-person", "sub": "rev-person",
                          "email": "r@x", "roles": [], "persona": None,
                          "entitled_domains": [], "is_authenticated": True})()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user
    with TestClient(gateway.app) as c:
        yield c, state
    gateway.app.dependency_overrides.clear()


_BODY = {"subject": "alice", "asset": "asset-a", "reason": "left the team"}


def test_9_the_route_refuses_a_caller_without_the_capability_and_records_nothing(route):
    c, state = route
    _approve()
    state["allowed"] = False
    r = c.post("/access_grants/revoke", json=_BODY)
    assert r.status_code == 403 and r.json()["detail"]["capability"] == "mesh:revokeAccessGrant"
    assert [e["entry"] for e in ht.ledger_entries()] == ["grant"]


def test_9_control_the_route_records_the_revocation_for_a_caller_with_it(route):
    c, state = route
    _approve()
    r = c.post("/access_grants/revoke", json=_BODY)
    assert r.status_code == 200 and r.json()["revoked"] is True
    assert r.json()["effective"] == "at the next seed sync"   # it does not claim the reader is gone
    assert state["asked"] == ("mesh:revokeAccessGrant", "rev-person")
    (row,) = [e for e in ht.ledger_entries() if e["entry"] == "revoke"]
    assert row["granted_by"] == "rev-person"                  # the revoker is the authenticated caller
    again = c.post("/access_grants/revoke", json=_BODY)
    assert again.status_code == 200 and again.json()["already_revoked"] is True


def test_9_the_route_answers_404_for_a_grant_that_is_not_in_effect(route):
    c, _state = route
    r = c.post("/access_grants/revoke", json={**_BODY, "subject": "nobody"})
    assert r.status_code == 404 and r.json()["detail"]["error"] == "no_such_grant"
    assert ht.ledger_entries() == []


def test_9_the_route_answers_503_when_the_ledger_cannot_record(route, world):
    c, _state = route
    db = world[0]
    _approve()
    db.down = True
    r = c.post("/access_grants/revoke", json=_BODY)
    assert r.status_code == 503 and r.json()["detail"]["error"] == "ledger_unavailable"


# 10. an approval names an asset that exists ----------------------------------------------------

def test_10_an_approval_for_an_asset_the_directory_lacks_is_refused_and_nothing_is_recorded(world):
    db, sent, _c, _p = world
    db.missing.add("ghost-asset")
    with pytest.raises(ht.UnknownAsset):
        _approve(asset="ghost-asset")
    assert ht.ledger_entries() == [] and sent == []           # no row, no apply


def test_10_control_an_asset_the_directory_has_is_recorded_and_applied(world):
    _db, sent, _c, _p = world
    assert _approve(asset="real-asset")["recorded"] is True
    assert [r["asset"] for r in ht.ledger_grants()] == ["real-asset"] and sent


def test_10_a_directory_that_cannot_be_asked_records_nothing(world, monkeypatch):
    _db, sent, _c, _p = world

    def down(asset, kind="dataset"):
        raise ht.DirectoryUnavailable("ConnectError")
    monkeypatch.setattr(ht, "asset_exists", down)
    with pytest.raises(ht.DirectoryUnavailable):
        _approve()
    assert ht.ledger_entries() == [] and sent == []


def test_10_a_document_is_not_asked_about(monkeypatch):
    monkeypatch.setattr(ht, "_grant_sync_module",
                        lambda: (_ for _ in ()).throw(AssertionError("asked the directory")))
    assert ht.asset_exists("some-doc-id", "document") is True


def _act_world(monkeypatch, world, asset):
    """`/human_tasks/<id>/act` for an access_request, through the real handler."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from src.iagent import gateway
    calls = {"resolved": []}
    task = {"task_id": "access-1", "kind": "access_request", "audience": "access_grant:X",
            "workflow_id": None, "requested_by": "alice",
            "payload": {"subject": "alice", "asset": asset, "domain": "X"}}
    monkeypatch.setattr(ht, "list_tasks_for", lambda caller, status="pending": [task])
    from tests.viewer_double import route_viewer_tasks_through
    route_viewer_tasks_through(monkeypatch)
    monkeypatch.setattr(ht, "check_can_act", lambda audience, caller: True)
    monkeypatch.setattr(ht, "get_task_resolution", lambda tid, *, caller_id: None)
    monkeypatch.setattr(ht, "mark_task_resolved",
                        lambda tid, **kw: calls["resolved"].append(tid) or 1)
    user = type("U", (), {"authz_id": "bob", "sub": "bob", "id": "bob", "email": "bob@x",
                          "persona": None, "entitled_domains": [], "roles": [],
                          "is_authenticated": True})()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user
    return TestClient(gateway.app), calls, gateway


def test_10_the_approval_route_refuses_before_resolving_when_the_asset_is_not_there(
        world, monkeypatch, register_rail):
    register_rail(["bob"])
    db, sent, _c, _p = world
    db.missing.add("ghost-asset")
    client, calls, gateway = _act_world(monkeypatch, world, "ghost-asset")
    try:
        with client as c:
            r = c.post("/human_tasks/access-1/act", json={"decision": "approved", "comment": "ok"})
    finally:
        gateway.app.dependency_overrides.clear()
    assert r.status_code == 422 and r.json()["detail"]["error"] == "asset_not_in_directory"
    assert calls["resolved"] == []                            # the task stays pending: reject it instead
    assert ht.ledger_entries() == [] and sent == []


def test_10_control_the_approval_route_records_and_applies_when_the_asset_is_there(
        world, monkeypatch, register_rail):
    register_rail(["bob"])
    client, calls, gateway = _act_world(monkeypatch, world, "asset-a")
    try:
        with client as c:
            r = c.post("/human_tasks/access-1/act", json={"decision": "approved", "comment": "ok"})
    finally:
        gateway.app.dependency_overrides.clear()
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["grant_written"] is True
    assert [r["asset"] for r in ht.ledger_grants()] == ["asset-a"]
    assert calls["resolved"] == ["access-1"]


def test_10_a_recorded_grant_whose_apply_failed_stands_in_the_ledger(world, monkeypatch,
                                                                    register_rail):
    register_rail(["bob"])
    monkeypatch.setattr(ht, "_grant_sync_run", lambda raw, prune=True, **kw: 4)   # apply fails
    client, calls, gateway = _act_world(monkeypatch, world, "asset-a")
    try:
        with client as c:
            r = c.post("/human_tasks/access-1/act", json={"decision": "approved", "comment": "ok"})
    finally:
        gateway.app.dependency_overrides.clear()
    assert r.json()["grant_written"] is False                  # the directory does not have it yet
    assert [x["asset"] for x in ht.ledger_grants()] == ["asset-a"]   # but the record stands: repaired at startup


# 11. a ledger row whose asset has gone ----------------------------------------------------------

class _DirClient:
    def __init__(self, present): self.present = set(present)
    def object_exists(self, kind, asset): return asset in self.present


def _grants(mod, *rows):
    return [mod.GrantRecord(subject=s, asset=a, granted_by="g") for s, a in rows]


def test_11_a_dangling_ledger_row_is_skipped_alone_and_reported():
    mod = _load_grant_sync()
    grants = _grants(mod, ("alice", "gone"), ("bob", "here"))
    skipped = []
    out = mod.find_dangling(_DirClient({"here"}), grants,
                            forgive=frozenset({("alice", "gone", "dataset")}), skipped=skipped)
    assert out == [] and [(g.subject, g.asset) for g in skipped] == [("alice", "gone")]


def test_11_control_a_dangling_committed_row_still_refuses():
    mod = _load_grant_sync()
    grants = _grants(mod, ("alice", "gone"), ("bob", "here"))
    out = mod.find_dangling(_DirClient({"here"}), grants, forgive=frozenset(), skipped=[])
    assert len(out) == 1 and "gone" in out[0]
    # and the default (no forgiveness asked for) is the old behaviour: refuse
    assert len(mod.find_dangling(_DirClient({"here"}), grants)) == 1


def _run_world(mod, monkeypatch, present, synced):
    import topaz_sync

    class _Client(_DirClient):
        def __init__(self, url): super().__init__(present)
        def __enter__(self): return self
        def __exit__(self, *a): return False

    class _Plan:
        add_relations: list = []
        del_relations: list = []

    monkeypatch.setattr(topaz_sync, "TopazClient", _Client)
    monkeypatch.setattr(mod, "sync_grants",
                        lambda c, g, *, prune=True: synced.append([x.asset for x in g]) or _Plan())
    monkeypatch.setattr(mod, "readback_grants", lambda c, g: (len(g), 0))


def test_11_run_applies_every_other_grant_when_one_ledger_row_has_gone(monkeypatch):
    import io
    mod, synced, skipped, out = _load_grant_sync(), [], [], io.StringIO()
    _run_world(mod, monkeypatch, {"here"}, synced)
    raw = {"grants": [{"subject": "alice", "asset": "gone", "granted_by": "g"},
                      {"subject": "bob", "asset": "here", "granted_by": "g"}]}
    code = mod.run(raw, "http://x.invalid", prune=False,
                   ledger_keys=frozenset({("alice", "gone", "dataset")}), skipped=skipped, out=out)
    assert code == 0 and synced == [["here"]]
    assert [g.asset for g in skipped] == ["gone"] and "SKIPPED ledger grant" in out.getvalue()


def test_11_control_a_dangling_committed_grant_applies_nothing(monkeypatch):
    import io
    mod, synced, err = _load_grant_sync(), [], io.StringIO()
    _run_world(mod, monkeypatch, {"here"}, synced)
    raw = {"grants": [{"subject": "alice", "asset": "gone", "granted_by": "g"},
                      {"subject": "bob", "asset": "here", "granted_by": "g"}]}
    code = mod.run(raw, "http://x.invalid", prune=False, ledger_keys=frozenset(),
                   out=io.StringIO(), err=err)
    assert code == 3 and synced == [] and "DANGLING" in err.getvalue()


def test_11_the_bff_tells_the_sync_which_rows_came_from_the_ledger(world, monkeypatch):
    seen = {}

    def seam(raw, prune=True, **kw):
        seen.update(kw)
        kw["skipped"].append(type("G", (), {"subject": "alice", "asset": "asset-a"})())
        return 0
    monkeypatch.setattr(ht, "_grant_sync_run", seam)
    _approve()
    out = ht.apply_ledger_to_directory()
    assert seen["ledger_keys"] == frozenset({("alice", "asset-a", "dataset")})   # not carol: committed
    assert out["skipped"] == [{"subject": "alice", "asset": "asset-a"}]          # and it is reported


def test_11_the_real_apply_loads_the_real_grant_sync(monkeypatch):
    """The module the BFF loads from its file must LOAD: it defines a dataclass, which needs its
    module registered while the class is made. (A seam test with a fake file never saw this.)"""
    monkeypatch.setattr(ht, "_GRANT_SYNC", str(ROOT / "policy" / "sync" / "grant_sync.py"))
    mod = ht._grant_sync_module()
    assert callable(mod.run) and callable(mod.union_grants)


# 12. the console output of two applies at once --------------------------------------------------

def test_12_run_writes_to_the_streams_it_is_given_and_not_to_the_process_streams(capsys):
    import io
    mod = _load_grant_sync()
    out, err = io.StringIO(), io.StringIO()
    assert mod.run({"grants": [{"subject": "a", "asset": "b"}]}, "http://x.invalid",
                   out=out, err=err) == 2
    assert "malformed" in err.getvalue()
    seen = capsys.readouterr()
    assert seen.out == "" and seen.err == ""


def test_12_control_without_streams_run_still_writes_the_process_streams(capsys):
    mod = _load_grant_sync()
    assert mod.run({"grants": [{"subject": "a", "asset": "b"}]}, "http://x.invalid") == 2
    assert "malformed" in capsys.readouterr().err


def test_12_two_approvals_at_once_each_keep_their_own_output(world, monkeypatch):
    import threading
    both_inside = threading.Barrier(2, timeout=10)

    def seam(raw, prune=True, *, out=None, err=None, **kw):
        n = len(raw["grants"])
        print(f"applying {n} grants", file=out)
        both_inside.wait()                      # BOTH applies are mid-run at the same moment
        print(f"done {n}", file=out)
        return 0
    monkeypatch.setattr(ht, "_grant_sync_run", seam)
    results = {}

    def work(name):
        results[name] = ht.apply_ledger_to_directory()
    threads = [threading.Thread(target=work, args=(n,)) for n in ("one", "two")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)
    assert set(results) == {"one", "two"}
    for r in results.values():                  # each caller got its OWN complete report
        assert "applying 1 grants" in r["output"] and "done 1" in r["output"]


def test_12_the_apply_redirects_no_process_stream():
    src = (ROOT / "src" / "iagent" / "human_tasks.py").read_text(encoding="utf-8")
    assert "redirect_stdout" not in src and "redirect_stderr" not in src
