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
            key = tuple(params[:3])
            if key in self.db.rows:
                self.rowcount = 0
            else:
                self.db.rows[key] = tuple(params)
                self.rowcount = 1
        elif "FROM access_grant_ledger" in sql:
            self._out = sorted(self.db.rows.values(), key=lambda r: (r[7], r[0], r[1]))
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
    monkeypatch.setattr(ht, "_grant_sync_run", lambda raw: sent.append(raw) or 0)
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
    assert "ON CONFLICT (subject, asset, kind) DO NOTHING" in ht._GRANT_INSERT_SQL
    assert "PRIMARY KEY (subject, asset, kind)" in ht._GRANT_LEDGER_SQL


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
