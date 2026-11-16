"""The seed CronJob is the ONE pruner of `reader` relations, so its input must include the ledger
(architect, 2026-11-16: D1 one pruner, D3 the seed reads the ledger).

An approved access grant lives in `access_grant_ledger` until a commit carries it into policy.
The seed prunes every reader relation its input does not name; fed committed policy alone it would
revoke each approved grant at its next tick. Doubles only: a stubbed ledger read and a fake
directory; nothing here connects to a database or writes a directory.

  1. SURVIVES   a ledger grant survives a seed tick (control: without the ledger it is pruned).
  2. FAIL CLOSED an unreadable ledger prunes NOTHING and exits 5 (control: no DSN, no ledger read).
  3. STILL PRUNES a grant removed from committed policy and absent from the ledger is pruned.
  4. TABLE      a table that does not exist yet is an empty ledger; any other error raises.
  5. UNION      committed wins a duplicate; a malformed committed entry is kept for load_grants.
  6. CHART      the seed Job carries the DSN (password by secretKeyRef, not envFrom) and the image
                it runs imports psycopg2 (declared in the root dependencies the image installs).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "policy" / "sync"))
sys.path.insert(0, str(ROOT))

import grant_sync as gs  # noqa: E402
from topaz_sync import DirObject, DirRelation  # noqa: E402
from tests.test_grant_sync import _FakeTopaz  # noqa: E402

A = "urn:li:dataset:(a,asset-a,PROD)"
C = "urn:li:dataset:(a,asset-c,PROD)"
COMMITTED = {"grants": [{"subject": "carol", "asset": C, "granted_by": "cnogradi", "reason": "seed"}]}
LEDGER = [{"subject": "alice", "asset": A, "kind": "dataset", "granted_by": "bob", "reason": "r"}]


class _Ctx:
    """The fake directory as TopazClient's context manager."""
    def __init__(self, fake): self.fake = fake
    def __call__(self, url): return self
    def __enter__(self): return self.fake
    def __exit__(self, *a): return False


@pytest.fixture
def seed(tmp_path, monkeypatch):
    import topaz_sync

    fake = _FakeTopaz()
    fake.objects |= {DirObject("dataset", A), DirObject("dataset", C)}
    f = tmp_path / "asset_grants.yaml"
    f.write_text(yaml.safe_dump(COMMITTED), encoding="utf-8")
    monkeypatch.setenv("ASSET_GRANTS_FILE", str(f))
    monkeypatch.delenv("PROJECTOR_POSTGRES_DSN", raising=False)
    constructed = []
    ctx = _Ctx(fake)
    monkeypatch.setattr(topaz_sync, "TopazClient", lambda url: constructed.append(url) or ctx)
    return fake, constructed, monkeypatch


def _reader(subject, asset):
    return DirRelation("dataset", asset, "reader", "user", subject)


# 1. survives ------------------------------------------------------------------------------------

def test_1_a_ledger_grant_survives_a_seed_tick(seed):
    fake, _c, mp = seed
    fake.relations.add(_reader("alice", A))                    # approved at runtime, in the directory
    mp.setenv("PROJECTOR_POSTGRES_DSN", "postgresql://x.invalid/db")
    mp.setattr(gs, "read_ledger", lambda dsn: LEDGER)
    assert gs.main() == 0
    assert _reader("alice", A) in fake.relations and _reader("carol", C) in fake.relations


def test_1_control_without_the_ledger_the_same_tick_revokes_it(seed):
    fake, _c, _mp = seed
    fake.relations.add(_reader("alice", A))
    assert gs.main() == 0                                      # no DSN: committed policy only
    assert _reader("alice", A) not in fake.relations           # why the ledger must be read
    assert _reader("carol", C) in fake.relations


# 2. fail closed ---------------------------------------------------------------------------------

def test_2_an_unreadable_ledger_prunes_nothing_and_exits_5(seed, capsys):
    fake, constructed, mp = seed
    fake.relations |= {_reader("alice", A), _reader("stale", A)}
    before = set(fake.relations)
    mp.setenv("PROJECTOR_POSTGRES_DSN", "postgresql://x.invalid/db")

    def boom(dsn):
        raise ConnectionError("store down")
    mp.setattr(gs, "read_ledger", boom)
    assert gs.main() == gs.EXIT_LEDGER_UNREADABLE == 5
    assert fake.relations == before and not fake.deleted_objects
    assert constructed == []                                   # the directory was never even opened
    assert "nothing pruned" in capsys.readouterr().err


def test_2_control_no_dsn_reads_no_ledger(seed):
    _fake, _c, mp = seed
    mp.setattr(gs, "read_ledger", lambda dsn: pytest.fail("the ledger was read with no DSN"))
    assert gs.main() == 0


# 3. still prunes --------------------------------------------------------------------------------

def test_3_a_grant_in_neither_policy_nor_ledger_is_still_pruned(seed):
    fake, _c, mp = seed
    stale = _reader("mallory", A)
    fake.relations |= {stale, _reader("alice", A)}
    mp.setenv("PROJECTOR_POSTGRES_DSN", "postgresql://x.invalid/db")
    mp.setattr(gs, "read_ledger", lambda dsn: LEDGER)
    assert gs.main() == 0
    assert stale not in fake.relations                         # one pruner, and it still prunes
    assert _reader("alice", A) in fake.relations


def test_3_a_grant_removed_from_committed_policy_is_revoked_even_with_a_ledger(seed):
    fake, _c, mp = seed
    fake.relations.add(_reader("dave", C))                     # was committed, now removed from git
    mp.setenv("PROJECTOR_POSTGRES_DSN", "postgresql://x.invalid/db")
    mp.setattr(gs, "read_ledger", lambda dsn: LEDGER)
    assert gs.main() == 0
    assert _reader("dave", C) not in fake.relations


# 4. table ---------------------------------------------------------------------------------------

class _FakeConn:
    def __init__(self, exc=None, rows=()):
        self.exc, self.rows, self.closed = exc, list(rows), False
    def cursor(self): return self
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, sql):
        assert "access_grant_ledger" in sql
        if self.exc:
            raise self.exc
    def fetchall(self): return self.rows
    def close(self): self.closed = True


def test_4_a_missing_table_is_an_empty_ledger(monkeypatch):
    psycopg2 = pytest.importorskip("psycopg2")
    import psycopg2.errors
    conn = _FakeConn(exc=psycopg2.errors.UndefinedTable("no table"))
    monkeypatch.setattr(psycopg2, "connect", lambda dsn, connect_timeout=0: conn)
    assert gs.read_ledger("postgresql://x.invalid/db") == [] and conn.closed


def test_4_control_any_other_error_raises(monkeypatch):
    psycopg2 = pytest.importorskip("psycopg2")
    conn = _FakeConn(exc=psycopg2.OperationalError("auth failed"))
    monkeypatch.setattr(psycopg2, "connect", lambda dsn, connect_timeout=0: conn)
    with pytest.raises(psycopg2.OperationalError):
        gs.read_ledger("postgresql://x.invalid/db")
    assert conn.closed


def test_4_rows_are_returned_as_dicts(monkeypatch):
    psycopg2 = pytest.importorskip("psycopg2")
    conn = _FakeConn(rows=[("alice", A, "dataset", "bob", "r")])
    monkeypatch.setattr(psycopg2, "connect", lambda dsn, connect_timeout=0: conn)
    assert gs.read_ledger("x") == LEDGER


# 5. union ---------------------------------------------------------------------------------------

def test_5_committed_wins_a_duplicate_and_the_ledger_adds_the_rest():
    dup = {"subject": "carol", "asset": C, "kind": "dataset", "granted_by": "other", "reason": ""}
    out = gs.union_grants(COMMITTED["grants"], [dup, *LEDGER])
    by = {(g["subject"], g["asset"]): g for g in out}
    assert by[("carol", C)]["granted_by"] == "cnogradi"
    assert ("alice", A) in by and len(out) == 2


def test_5_a_malformed_committed_entry_is_kept_so_load_grants_refuses_it():
    bad = {"subject": "x"}                                      # no asset, no granted_by
    out = gs.union_grants([bad], LEDGER)
    assert bad in out                                           # the union does not launder it
    _grants, errors = gs.load_grants({"grants": out})
    assert errors


def test_5_a_non_mapping_committed_entry_is_not_dropped_either():
    assert "not-a-mapping" in gs.union_grants(["not-a-mapping"], LEDGER)


# 6. chart + image -------------------------------------------------------------------------------

@pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")
def test_6_the_seed_job_carries_the_dsn_with_the_password_by_secret_ref():
    r = subprocess.run(["helm", "template", "t", "helm/invincible-agent", "--set",
                        "topazSeed.enabled=true"], capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(ROOT),
                       timeout=300)
    assert r.returncode == 0, r.stderr[-500:]
    docs = [d for d in yaml.safe_load_all(r.stdout) if d]
    (cj,) = [d for d in docs if d.get("kind") == "CronJob" and d["metadata"]["name"] == "t-topaz-seed"]
    (c,) = cj["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"]
    env = {e["name"]: e for e in c["env"]}
    dsn = env["PROJECTOR_POSTGRES_DSN"]["value"]
    assert "$(BPMN_POSTGRES_PASSWORD)" in dsn and "password" not in dsn.lower().replace(
        "$(bpmn_postgres_password)", "")
    ref = env["BPMN_POSTGRES_PASSWORD"]["valueFrom"]["secretKeyRef"]
    assert ref["key"] == "BPMN_POSTGRES_PASSWORD" and ref["name"] == "t-secrets"
    assert "envFrom" not in c                                   # the whole secret is not mounted
    names = [e["name"] for e in c["env"]]                       # $(VAR) refs resolve only if defined first
    assert names.index("BPMN_POSTGRES_PASSWORD") < names.index("PROJECTOR_POSTGRES_DSN")


def test_6_the_seed_image_imports_psycopg2():
    """The seed runs the cortex-bff image (values.yaml topazSeed.image.name), built from the repo
    root by `uv sync --locked --no-dev`: psycopg2-binary must be in the ROOT main dependencies."""
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    deps = pyproject[pyproject.index("dependencies = ["):pyproject.index("[project.optional-dependencies]")]
    assert '"psycopg2-binary"' in deps
    values = yaml.safe_load((ROOT / "helm" / "invincible-agent" / "values.yaml").read_text(encoding="utf-8"))
    assert values["topazSeed"]["image"]["name"] == "cortex-bff"


# 7. the Job: a ledger failure fails it at the END, not at once -------------------------------------

def _seed_script() -> str:
    r = subprocess.run(["helm", "template", "t", "helm/invincible-agent", "--set",
                        "topazSeed.enabled=true"], capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(ROOT),
                       timeout=300)
    assert r.returncode == 0, r.stderr[-500:]
    (cj,) = [d for d in yaml.safe_load_all(r.stdout)
             if d and d.get("kind") == "CronJob" and d["metadata"]["name"] == "t-topaz-seed"]
    (c,) = cj["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"]
    return c["args"][0]


def _run_seed(tmp_path, rcs: dict):
    """Run the rendered seed script with a fake `python` that records which sync ran and exits
    with the code `rcs` names for it (default 0)."""
    import os
    sh = shutil.which("sh")
    if sh is None or shutil.which("helm") is None:
        pytest.skip("sh or helm not available")
    tmp_path.mkdir(parents=True, exist_ok=True)
    work = tmp_path / "app"
    work.mkdir()
    shim = tmp_path / "bin"
    shim.mkdir()
    log = tmp_path / "ran.log"
    fake = shim / "python"
    fake.write_text('#!/bin/sh\nname=$(basename "$1" .py)\necho "$name" >> "$RAN_LOG"\n'
                    'eval "rc=\${RC_$name:-0}"\nexit "$rc"\n', encoding="utf-8", newline="\n")
    fake.chmod(0o755)
    script = _seed_script().replace("cd /app\n", f"cd '{work.as_posix()}'\n", 1)
    env = {**os.environ, "PATH": f"{shim.as_posix()}{os.pathsep}{os.environ['PATH']}",
           "RAN_LOG": str(log), "TOPAZ_DIRECTORY_URL": "http://x.invalid",
           **{f"RC_{k}": str(v) for k, v in rcs.items()}}
    p = subprocess.run([sh, "-c", script], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=120)
    ran = log.read_text(encoding="utf-8").split() if log.exists() else []
    return p, ran


def test_7_a_ledger_failure_lets_the_other_syncs_run_and_the_job_fails_at_the_end(tmp_path):
    p, ran = _run_seed(tmp_path, {"grant_sync": 5})
    assert "task_grant_sync" in ran and "capability_grant_sync" in ran
    assert ran.index("grant_sync") < ran.index("task_grant_sync")
    assert p.returncode == 5                                    # still fails visibly, at the end
    assert "SEED COMPLETE" not in p.stdout
    assert "FAIL: grant_sync could not read the approved-grant ledger" in p.stderr


def test_7_control_any_other_grant_sync_code_still_stops_the_run(tmp_path):
    for rc in (2, 3, 4):
        p, ran = _run_seed(tmp_path / f"rc{rc}", {"grant_sync": rc})
        assert p.returncode == rc
        assert "task_grant_sync" not in ran, rc


def test_7_control_a_clean_run_completes(tmp_path):
    p, ran = _run_seed(tmp_path, {})
    assert p.returncode == 0 and "SEED COMPLETE" in p.stdout
    assert "task_grant_sync" in ran
