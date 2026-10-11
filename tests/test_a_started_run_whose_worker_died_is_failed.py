"""A STARTED RUN WHOSE WORKER DIED MUST BE ENDED BY A BOUND, NOT HOLD A QUEUE SLOT FOR EVER.

The sandbox runs Dagster with DefaultRunLauncher and QueuedRunCoordinator(max_concurrent_runs: 2).
When a run's code-location pod dies the run stays STARTED, and two of those hang every question.
DefaultRunLauncher does not support worker health checks, so `monitor_started_run` skips the
health check and FALLS THROUGH to `check_run_timeout(.., run_monitoring_max_runtime_seconds)`,
which cancels, tries to terminate (exceptions caught) and force-marks the run FAILED once it has
been STARTED longer than the bound. The hand-made instance config set `run_monitoring.enabled`
but no `max_runtime_seconds` (default 0 = disabled), so nothing ever ended a zombie.

This file renders the chart's `<release>-dagster-home` ConfigMap and drives REAL dagster with
the rendered launcher / coordinator / monitoring sections.

Run: uv run --frozen pytest tests/test_a_started_run_whose_worker_died_is_failed.py -v
"""
from __future__ import annotations

import copy
import logging
import shutil
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

_REPO = Path(__file__).resolve().parents[1]
_CHART = "helm/invincible-agent"
_SANDBOX_VALUES = f"{_CHART}/values-sandbox.yaml"
_RELEASE = "iagent"

# MEASURED 2026-10-09 on the sandbox run storage, 2742 finished runs: the longest finished run
# was 1930s (process_document_artifact_job SUCCESS, p50 685s). supervisor_query_job max 1396s,
# ingest_ontology_job max 341s. A bound at or under this would fail a legitimate run.
LONGEST_MEASURED_RUN_S = 1930

pytestmark = pytest.mark.skipif(
    shutil.which("helm") is None, reason="helm not installed: the chart cannot be rendered"
)


@pytest.fixture(scope="module")
def docs() -> list[dict]:
    r = subprocess.run(
        ["helm", "template", _RELEASE, _CHART, "-f", _SANDBOX_VALUES],
        capture_output=True, text=True, cwd=str(_REPO), timeout=300,
    )
    assert r.returncode == 0, f"helm template failed:\n{r.stderr[-700:]}"
    out = [d for d in yaml.safe_load_all(r.stdout) if isinstance(d, dict)]
    assert out, "helm rendered nothing and reported success"
    return out


def _find(docs: list[dict], kind: str, name: str) -> dict:
    hits = [d for d in docs if d.get("kind") == kind and d["metadata"]["name"] == name]
    assert len(hits) == 1, f"expected exactly one {kind}/{name}, found {len(hits)}"
    return hits[0]


@pytest.fixture(scope="module")
def instance_config(docs) -> dict:
    cm = _find(docs, "ConfigMap", f"{_RELEASE}-dagster-home")
    cfg = yaml.safe_load(cm["data"]["dagster.yaml"])
    assert isinstance(cfg, dict)
    return cfg


def test_THE_RENDERED_INSTANCE_BOUNDS_A_STARTED_RUN(instance_config):
    """Defends the fix itself: the config the pods mount carries a positive max_runtime_seconds
    above the longest legitimate run, beside the launcher and coordinator it was measured under."""
    cfg = instance_config
    assert cfg["run_launcher"]["class"] == "DefaultRunLauncher"
    assert cfg["run_coordinator"]["class"] == "QueuedRunCoordinator"
    assert cfg["run_coordinator"]["config"]["max_concurrent_runs"] == 2
    mon = cfg["run_monitoring"]
    assert mon["enabled"] is True
    bound = mon["max_runtime_seconds"]
    assert bound > 0
    assert bound > LONGEST_MEASURED_RUN_S, (
        f"max_runtime_seconds {bound} would fail a legitimate {LONGEST_MEASURED_RUN_S}s run"
    )


def test_THE_RENDERED_STORAGE_READS_ENV_REFS_NEVER_LITERALS(instance_config):
    """Defends the secret: username, password, host, db and port are {env: NAME} refs."""
    db = instance_config["storage"]["postgres"]["postgres_db"]
    for key in ("username", "password", "hostname", "db_name", "port"):
        v = db[key]
        assert isinstance(v, dict) and set(v) == {"env"}, f"storage {key} is not an env ref"
        assert v["env"].startswith("DAGSTER_POSTGRES_")


@pytest.mark.parametrize("deployment", ["dagster-webserver", "dagster-daemon", "dagster-user-code"])
def test_EVERY_DAGSTER_CONTROL_POD_MOUNTS_THE_RENDERED_INSTANCE(docs, deployment):
    """Defends the join: a ConfigMap nobody mounts is not a fix. The volume is NAMED
    `dagster-instance` so the strategic merge takes over the hand-patched live volume of that
    name, and the checksum annotation rolls the pod when the config changes."""
    dep = _find(docs, "Deployment", f"{_RELEASE}-{deployment}")
    tpl = dep["spec"]["template"]
    vols = [v for v in tpl["spec"]["volumes"] if v["name"] == "dagster-instance"]
    assert len(vols) == 1
    assert vols[0]["configMap"]["name"] == f"{_RELEASE}-dagster-home"
    mounts = [
        m for c in tpl["spec"]["containers"] for m in c.get("volumeMounts", [])
        if m["name"] == "dagster-instance"
    ]
    assert len(mounts) == 1
    assert mounts[0]["mountPath"] == "/opt/dagster/dagster_home/dagster.yaml"
    assert mounts[0]["subPath"] == "dagster.yaml"
    checksum = tpl["metadata"]["annotations"]["checksum/dagster-instance"]
    assert len(checksum) == 64


# --------------------------------------------------------------------------------------
# BEHAVIOUR against real dagster
# --------------------------------------------------------------------------------------

def _overrides(cfg: dict, *, drop_max_runtime: bool = False) -> dict:
    mon = copy.deepcopy(cfg["run_monitoring"])
    if drop_max_runtime:
        mon.pop("max_runtime_seconds")
    return {
        "run_launcher": copy.deepcopy(cfg["run_launcher"]),
        "run_coordinator": copy.deepcopy(cfg["run_coordinator"]),
        "run_monitoring": mon,
    }


def _started_zombie(instance):
    """A run in STARTED with a recorded start time and no live worker or code server."""
    import logging as _logging

    from dagster import DagsterRunStatus
    from dagster._core.events import DagsterEvent, DagsterEventType
    from dagster._core.test_utils import create_run_for_test

    run = create_run_for_test(instance, job_name="zombie_job", status=DagsterRunStatus.STARTING)
    # The run storage records start_time when it handles the job-start event, exactly as the
    # run worker's first event would have; after that the worker "dies" and nothing follows.
    instance.report_dagster_event(
        DagsterEvent(
            event_type_value=DagsterEventType.PIPELINE_START.value,
            job_name=run.job_name,
            message="started",
        ),
        run_id=run.run_id,
        log_level=_logging.INFO,
    )
    rec = instance.get_run_record_by_id(run.run_id)
    assert rec.dagster_run.status == DagsterRunStatus.STARTED
    assert rec.start_time is not None, "fixture failed to give the run a start time"
    return rec


def _monitor_at(monkeypatch, instance, rec, now: float):
    from dagster._daemon.monitoring import run_monitoring as rm

    monkeypatch.setattr(rm, "get_current_timestamp", lambda: now)
    rm.monitor_started_run(instance, object(), rec, logging.getLogger("zombie-test"))
    return instance.get_run_by_id(rec.dagster_run.run_id)


def test_A_ZOMBIE_PAST_THE_RENDERED_BOUND_IS_FAILED(instance_config, monkeypatch):
    """Defends the fix: STARTED past max_runtime_seconds with a dead worker (no code server for
    DefaultRunLauncher to terminate through) ends FAILURE with the runtime reason, and the
    terminate path does not crash the monitor."""
    from dagster import DagsterRunStatus
    from dagster._core.test_utils import instance_for_test

    bound = instance_config["run_monitoring"]["max_runtime_seconds"]
    with instance_for_test(overrides=_overrides(instance_config)) as instance:
        rec = _started_zombie(instance)
        run = _monitor_at(monkeypatch, instance, rec, rec.start_time + bound + 1)
        assert run.status == DagsterRunStatus.FAILURE
        msgs = [e.message or "" for e in instance.all_logs(run.run_id)]
        assert any("maximum runtime" in m.lower() for m in msgs), msgs[-6:]


def test_CONTROL_A_ZOMBIE_INSIDE_THE_BOUND_IS_LEFT_ALONE(instance_config, monkeypatch):
    """Control 1: same run, same config, one second under the bound -> still STARTED. Proves
    the FAILURE above is the bound firing, not the monitor failing everything it sees."""
    from dagster import DagsterRunStatus
    from dagster._core.test_utils import instance_for_test

    bound = instance_config["run_monitoring"]["max_runtime_seconds"]
    with instance_for_test(overrides=_overrides(instance_config)) as instance:
        rec = _started_zombie(instance)
        run = _monitor_at(monkeypatch, instance, rec, rec.start_time + bound - 1)
        assert run.status == DagsterRunStatus.STARTED


def test_CONTROL_THE_LIVE_HAND_MADE_CONFIG_NEVER_ENDS_A_ZOMBIE(instance_config, monkeypatch):
    """Control 2, differing in exactly one thing (max_runtime_seconds removed, as in the
    hand-made live config): the same zombie nine days on is STILL STARTED. This is the arm that
    proves the bound, and nothing else in the config, is the fix."""
    from dagster import DagsterRunStatus
    from dagster._core.test_utils import instance_for_test

    overrides = _overrides(instance_config, drop_max_runtime=True)
    assert "max_runtime_seconds" not in overrides["run_monitoring"]
    with instance_for_test(overrides=overrides) as instance:
        rec = _started_zombie(instance)
        run = _monitor_at(monkeypatch, instance, rec, rec.start_time + 9 * 86400)
        assert run.status == DagsterRunStatus.STARTED
