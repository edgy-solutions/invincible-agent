"""engine-lg's checkpoints in their own database (graphHost.checkpointsDatabase.enabled, default OFF).

Why: Electric's own role is LOGIN REPLICATION and can decode any database it can CONNECT to; engine-lg's checkpoints sit
in the projections database Electric reads. The new database has CONNECT revoked from PUBLIC. That excludes a role only
when Electric logs in as its OWN role (electric.db.enabled): otherwise Electric is the main user, who owns the database.
So the switch must refuse to render without electric.db.enabled.

Seals: off changes nothing (no Job, the DSN names the projections database); on names the new database in the DSN and
in the Job, the Job creates it OWNED by the chart's pg user and revokes PUBLIC CONNECT, at hook weight -4; the render
refuses without electric.enabled or electric.db.enabled (naming both keys), for a name equal to the projections
database, for a non-identifier, and for a DSN that has no database part to swap; Electric's role Job never names it.
Comparisons are on the whole database name (parsed from the DSN), never a substring.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[1]
_CHART = _REPO / "helm" / "invincible-agent"
pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")

_VALUES = yaml.safe_load((_CHART / "values.yaml").read_text(encoding="utf-8"))
_NEW = _VALUES["graphHost"]["checkpointsDatabase"]["name"]
_DSN_ENV = "GRAPH_HOST_POSTGRES_DSN"
_ON = ["--set", "graphHost.enabled=true", "--set", "electric.db.enabled=true",
       "--set", "graphHost.checkpointsDatabase.enabled=true"]
_OFF = ["--set", "graphHost.enabled=true"]


def _helm(*extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(["helm", "template", "r", str(_CHART), *extra], capture_output=True, text=True,
                          cwd=str(_REPO), timeout=300)


def _render(*extra: str) -> list[dict]:
    r = _helm(*extra)
    assert r.returncode == 0, f"helm template failed:\n{r.stderr[-700:]}"
    return [d for d in yaml.safe_load_all(r.stdout) if d]


def _containers(doc):
    spec = doc.get("spec") or {}
    pod = (spec.get("template") or {}).get("spec") or {}
    return (pod.get("containers") or []) + (pod.get("initContainers") or [])


def _dsns(docs) -> list[str]:
    out = []
    for d in docs:
        for c in _containers(d):
            out += [e.get("value") for e in c.get("env") or [] if e["name"] == _DSN_ENV]
    return out


def _dsn_db(dsn: str) -> str:
    # `$(BPMN_POSTGRES_*)` placeholders are not a valid netloc for urlparse's port; take the path only.
    return dsn.rsplit("/", 1)[1]


def _jobs(docs):
    return [d for d in docs if d.get("kind") == "Job" and d["metadata"]["name"] == "r-checkpoints-database"]


def _script(job) -> str:
    return "\n".join((job["spec"]["template"]["spec"]["containers"][0]).get("command") or [])


def test_off_by_default_no_job_and_the_dsn_names_the_projections_database():
    docs = _render(*_OFF)
    assert not _jobs(docs)
    dsns = _dsns(docs)
    assert len(dsns) == 1, dsns
    assert _dsn_db(dsns[0]) == "$(BPMN_POSTGRES_DB)", dsns[0]


def test_on_the_dsn_names_the_new_database_and_nothing_else_changes():
    off = _dsns(_render(*_OFF))[0]
    on_dsns = _dsns(_render(*_ON))
    assert len(on_dsns) == 1, on_dsns
    on = on_dsns[0]
    assert _dsn_db(on) == _NEW
    assert off.replace("$(BPMN_POSTGRES_DB)", _NEW) == on


def test_on_the_job_creates_the_database_owned_by_the_pg_user_and_revokes_public():
    docs = _render(*_ON)
    [job] = _jobs(docs)
    ann = job["metadata"]["annotations"]
    assert ann["helm.sh/hook"] == "post-install,post-upgrade"
    assert ann["helm.sh/hook-weight"] == "-4"
    sql = _script(job)
    assert "CREATE DATABASE %I OWNER %I" in sql
    assert f"'{_NEW}'" in sql
    assert "'iagent'" in sql or "OWNER" in sql  # the owner argument is the chart's pg user (next assert reads it)
    assert f'REVOKE CONNECT ON DATABASE "{_NEW}" FROM PUBLIC;' in sql
    pg_user = _VALUES["postgresql"]["auth"]["username"]
    assert f"'{pg_user}')" in sql, "the OWNER argument is not the chart's pg user"


def test_a_custom_name_moves_the_job_and_the_dsn_together():
    docs = _render(*_ON, "--set", "graphHost.checkpointsDatabase.name=lg_ckpt")
    assert _dsn_db(_dsns(docs)[0]) == "lg_ckpt"
    [job] = _jobs(docs)
    assert "'lg_ckpt'" in _script(job) and '"lg_ckpt"' in _script(job)


@pytest.mark.parametrize("unset", ["electric.db.enabled=false", "electric.enabled=false"])
def test_the_switch_refuses_to_render_without_electrics_own_role(unset):
    r = _helm("--set", "graphHost.enabled=true", "--set", "electric.db.enabled=true",
              "--set", "graphHost.checkpointsDatabase.enabled=true", "--set", unset)
    assert r.returncode != 0
    assert "graphHost.checkpointsDatabase.enabled" in r.stderr
    assert "electric.db.enabled" in r.stderr and "electric.enabled" in r.stderr


def test_a_name_equal_to_the_projections_database_fails():
    proj = _VALUES["postgresql"]["auth"]["database"]
    r = _helm(*_ON, "--set", f"graphHost.checkpointsDatabase.name={proj}")
    assert r.returncode != 0 and "projections database" in r.stderr


def test_a_name_that_is_not_an_identifier_fails():
    r = _helm(*_ON, "--set", "graphHost.checkpointsDatabase.name=a-b")
    assert r.returncode != 0 and "plain lower-case SQL identifier" in r.stderr


def test_a_dsn_with_no_database_part_to_swap_fails_rather_than_stay_shared():
    r = _helm(*_ON, "--set", f"graphHost.env.{_DSN_ENV}=postgresql://u:p@h:5432/fixed")
    assert r.returncode != 0 and "no $(BPMN_POSTGRES_DB) part to swap" in r.stderr


def test_electrics_role_job_never_names_the_checkpoints_database():
    docs = _render(*_ON)
    roles = [d for d in docs if d.get("kind") == "Job" and d["metadata"]["name"].endswith("electric-role")]
    assert roles, "the electric role Job did not render"
    for job in roles:
        assert _NEW not in yaml.safe_dump(job)
