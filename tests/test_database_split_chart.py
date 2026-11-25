"""The database split (databaseSplit.enabled, default OFF): each concern names its own database, none the projections'.

Why: a REPLICATION role (Electric's) can decode every table in its database whatever its SELECT grants say, so the
database Electric reads must hold only what Electric may stream. The census is over three: Dagster's env (every
template that sets DAGSTER_POSTGRES_DB), the LangGraph checkpoint URI, and the projections database (read from
values.yaml). Comparisons are on the whole value, never a substring: `iagent` is a prefix of `iagent_dagster`.

Seals: off by default changes nothing; ON gives each concern its own database and none names the projections';
the gate on electric.enabled; the Job creates exactly the configured databases and revokes PUBLIC CONNECT on each;
a name equal to the projections database fails the render; with Electric's role on, its CONNECT grant names the
projections database and none of the split ones.
"""
from __future__ import annotations

import re
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
_PROJECTIONS = _VALUES["postgresql"]["auth"]["database"]
_SPLIT = _VALUES["databaseSplit"]["databases"]


def _helm(*extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(["helm", "template", "r", str(_CHART), *extra], capture_output=True, text=True,
                          cwd=str(_REPO), timeout=300)


def _render(*extra: str) -> list[dict]:
    r = _helm(*extra)
    assert r.returncode == 0, f"helm template failed:\n{r.stderr[-700:]}"
    return [d for d in yaml.safe_load_all(r.stdout) if d]


def _split(*extra: str) -> list[dict]:
    return _render("--set", "databaseSplit.enabled=true", *extra)


def _containers(doc):
    spec = (doc.get("spec") or {})
    pod = (spec.get("template") or {}).get("spec") or (((spec.get("jobTemplate") or {}).get("spec") or {})
                                                        .get("template") or {}).get("spec") or {}
    return (pod.get("containers") or []) + (pod.get("initContainers") or [])


def _dagster_dbs(docs) -> list[str]:
    out = []
    for d in docs:
        for c in _containers(d):
            out += [e.get("value") for e in c.get("env") or [] if e["name"] == "DAGSTER_POSTGRES_DB"]
    return out


def _checkpoint_db(docs) -> str:
    cm = next(d for d in docs if d.get("kind") == "ConfigMap" and "LANGGRAPH_POSTGRES_URI" in (d.get("data") or {}))
    return urlparse(cm["data"]["LANGGRAPH_POSTGRES_URI"]).path.lstrip("/")


def _job(docs):
    return [d for d in docs if d.get("kind") == "Job" and d["metadata"]["name"] == "r-database-split"]


def _script(job) -> str:
    return "\n".join(job["spec"]["template"]["spec"]["containers"][0]["command"])


def test_off_by_default_every_concern_names_the_shared_database():
    docs = _render()
    dbs = _dagster_dbs(docs)
    assert len(dbs) >= 4, "control: the Dagster census finds its envs"
    assert set(dbs) == {_PROJECTIONS} and _checkpoint_db(docs) == _PROJECTIONS
    assert _job(docs) == []


def test_on_each_concern_names_its_own_database_and_none_names_the_projections():
    docs = _split()
    dbs = _dagster_dbs(docs)
    assert len(dbs) >= 4, "control: the Dagster census finds its envs"
    assert set(dbs) == {_SPLIT["dagster"]}
    assert _checkpoint_db(docs) == _SPLIT["checkpoints"]
    assert _PROJECTIONS not in set(dbs) | {_checkpoint_db(docs)}
    assert _PROJECTIONS not in _SPLIT.values()


def test_the_split_is_gated_on_electric():
    docs = _split("--set", "electric.enabled=false")
    assert set(_dagster_dbs(docs)) == {_PROJECTIONS} and _checkpoint_db(docs) == _PROJECTIONS
    assert _job(docs) == []


def test_the_job_creates_exactly_the_configured_databases_and_revokes_public_connect():
    script = _script(_job(_split())[0])
    created = re.findall(r"WHERE NOT EXISTS \(SELECT 1 FROM pg_database WHERE datname = '([^']+)'\)", script)
    assert sorted(created) == sorted(_SPLIT.values())
    revoked = re.findall(r'REVOKE CONNECT ON DATABASE "([^"]+)" FROM PUBLIC', script)
    assert sorted(revoked) == sorted(_SPLIT.values())
    assert _PROJECTIONS not in created and _PROJECTIONS not in revoked


def test_a_split_database_named_like_the_projections_fails_the_render():
    r = _helm("--set", "databaseSplit.enabled=true", "--set", f"databaseSplit.databases.dagster={_PROJECTIONS}")
    assert r.returncode != 0 and "the split would move nothing" in r.stderr


def test_the_database_names_come_from_values():
    docs = _split("--set", "databaseSplit.databases.dagster=zz_dagster")
    assert set(_dagster_dbs(docs)) == {"zz_dagster"}
    assert "zz_dagster" in _script(_job(docs)[0])


def test_electrics_role_connects_to_the_projections_database_only():
    docs = _split("--set", "electric.db.enabled=true")
    role = next(d for d in docs if d.get("kind") == "Job" and d["metadata"]["name"] == "r-electric-role")
    grants = re.findall(r'GRANT CONNECT ON DATABASE "([^"]+)"', _script(role))
    assert grants == [_PROJECTIONS]


_EVERY = ["-f", str(_REPO / "scripts" / "values-every-workload.yaml")]


def _every(split: bool) -> list[dict]:
    # The census that sees EVERY workload: the image seal's file switches on the optional ones (supervisor among them),
    # which a bare render leaves out. Pinned both ways, so a workload that names its own database fails here.
    return _render("--set", f"databaseSplit.enabled={'true' if split else 'false'}", *_EVERY)


def _dagster_env_owners(docs) -> dict[str, str]:
    out = {}
    for d in docs:
        for c in _containers(d):
            for e in c.get("env") or []:
                if e["name"] == "DAGSTER_POSTGRES_DB":
                    out[d["metadata"]["name"]] = e.get("value")
    return out


def test_with_every_workload_on_the_split_moves_every_dagster_consumer():
    docs = _every(True)
    owners = _dagster_env_owners(docs)
    assert "r-supervisor" in owners, "control: the census reaches the supervisor"
    assert len(owners) >= 5
    assert set(owners.values()) == {_SPLIT["dagster"]}, owners
    assert _checkpoint_db(docs) == _SPLIT["checkpoints"]


def test_with_every_workload_on_and_the_split_off_every_consumer_names_the_shared_database():
    docs = _every(False)
    owners = _dagster_env_owners(docs)
    assert "r-supervisor" in owners, "control: the census reaches the supervisor"
    assert set(owners.values()) == {_PROJECTIONS}, owners
    assert _checkpoint_db(docs) == _PROJECTIONS
    assert _job(docs) == []


@pytest.mark.parametrize("bad", ["Bad-Name", "x;drop", "1abc", "a b"])
def test_a_split_database_name_that_is_not_a_plain_identifier_fails_the_render(bad):
    r = _helm("--set", "databaseSplit.enabled=true", "--set", f"databaseSplit.databases.dagster={bad}")
    assert r.returncode != 0 and "is not a plain lower-case SQL identifier" in r.stderr, r.stderr[-300:]


def test_a_plain_identifier_renders_control_for_the_identifier_check():
    assert _helm("--set", "databaseSplit.enabled=true", "--set", "databaseSplit.databases.dagster=zz_ok1").returncode == 0


def test_the_create_names_the_charts_pg_user_as_owner():
    # PUBLIC's CONNECT is revoked, so a database owned by `postgres` would refuse the app user.
    script = _script(_job(_split("--set", "postgresql.auth.username=zz_owner"))[0])
    for db in _SPLIT.values():
        assert re.search(rf"CREATE DATABASE %I OWNER %I', '{db}', 'zz_owner'\)", script), script
