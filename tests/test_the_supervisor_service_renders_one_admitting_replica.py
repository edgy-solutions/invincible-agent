"""THE DURABLE ANSWER SERVICE RENDERS AS ONE REPLICA, WITH ITS ADMISSION VALUES AS ENV.

invincible-agent ADR-0072 §3: `src/iagent/supervisor_service.py` runs as its own Deployment,
on the cortex-bff image, one replica, with dagster user-code's env, behind
`supervisorService.enabled`, and registered with the Restate admin like the engines.
§5: a FIFO semaphore of K answers, which counts once per replica.

`IAGENT_ANSWER_LIMIT` (K) and `IAGENT_ANSWER_QUEUE_MAX` are chart values on that
Deployment. Each overlay sets them from its model-server measurement. The queue max (a count:
a request at a full queue is refused "busy" at once, with no wait ceiling) has
no ruled default, so an enabled render without one must FAIL rather than ship a number
nobody measured.

Every assertion reads the render (or values.yaml), never a restated number, and every
absence is paired with the same render turned on.

Run: uv run pytest tests/test_the_supervisor_service_renders_one_admitting_replica.py -q
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[1]
_CHART = "helm/invincible-agent"
_RELEASE = "t"

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")

_ON = ("--set", "supervisorService.enabled=true", "--set", "supervisorService.queueMax=7")


def _helm(*extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["helm", "template", _RELEASE, _CHART, *extra],
        capture_output=True, text=True, cwd=str(_REPO), timeout=300,
    )


def _render(*extra: str) -> list[dict]:
    r = _helm(*extra)
    assert r.returncode == 0, f"helm template failed:\n{r.stderr[-700:]}"
    docs = [d for d in yaml.safe_load_all(r.stdout) if d]
    assert docs, "helm rendered nothing and reported success"
    return docs


def _one(docs: list[dict], kind: str, name: str) -> dict:
    found = [d for d in docs if d.get("kind") == kind and d["metadata"]["name"] == name]
    assert len(found) == 1, f"{kind}/{name}: {len(found)} rendered"
    return found[0]


def _named(docs: list[dict], kind: str, name: str) -> list[dict]:
    return [d for d in docs if d.get("kind") == kind and d["metadata"]["name"] == name]


def _container(deploy: dict) -> dict:
    (c,) = deploy["spec"]["template"]["spec"]["containers"]
    return c


def _env(container: dict) -> dict:
    return {e["name"]: e for e in container.get("env", [])}


def _restate_init_script(docs: list[dict]) -> str:
    job = _one(docs, "Job", f"{_RELEASE}-restate-init")
    spec = job["spec"]["template"]["spec"]
    parts = []
    for c in spec.get("initContainers", []) + spec["containers"]:
        parts.extend(c.get("command", []) + c.get("args", []))
    return "\n".join(parts)


def _defaults() -> dict:
    values = yaml.safe_load((_REPO / _CHART / "values.yaml").read_text(encoding="utf-8"))
    return values["supervisorService"]


def test_off_by_default_and_on_when_enabled():
    off = _render()
    on = _render(*_ON)
    name = f"{_RELEASE}-supervisor"
    assert _defaults()["enabled"] is False
    assert not _named(off, "Deployment", name) and not _named(off, "Service", name)
    assert f"{name}." not in _restate_init_script(off)
    # The control: the same render, gate on.
    _one(on, "Deployment", name)
    _one(on, "Service", name)


def test_an_enabled_render_without_a_queue_max_fails():
    assert _defaults()["queueMax"] is None, "a default queue max was added: it needs a ruling"
    r = _helm("--set", "supervisorService.enabled=true")
    assert r.returncode != 0
    assert "supervisorService.queueMax is required" in r.stderr
    # The control: the same render with the value set succeeds.
    assert _helm(*_ON).returncode == 0


def test_the_admission_values_reach_the_process_as_env():
    env = _env(_container(_one(_render(*_ON), "Deployment", f"{_RELEASE}-supervisor")))
    assert env["IAGENT_ANSWER_LIMIT"]["value"] == str(_defaults()["answerLimit"])
    assert env["IAGENT_ANSWER_QUEUE_MAX"]["value"] == "7"
    # K is a value, not a constant: an overlay's number reaches the env.
    env3 = _env(_container(_one(
        _render(*_ON, "--set", "supervisorService.answerLimit=3"),
        "Deployment", f"{_RELEASE}-supervisor")))
    assert env3["IAGENT_ANSWER_LIMIT"]["value"] == "3"


def test_one_replica_and_no_value_raises_it():
    for extra in ((), ("--set", "supervisorService.replicas=3")):
        deploy = _one(_render(*_ON, *extra), "Deployment", f"{_RELEASE}-supervisor")
        assert deploy["spec"]["replicas"] == 1


def test_it_runs_the_bff_image_with_user_codes_env():
    docs = _render(*_ON)
    sup = _container(_one(docs, "Deployment", f"{_RELEASE}-supervisor"))
    bff = _container(_one(docs, "Deployment", f"{_RELEASE}-cortex-bff"))
    uc = _container(_one(docs, "Deployment", f"{_RELEASE}-dagster-user-code"))
    assert sup["image"] == bff["image"]
    assert sup["envFrom"] == uc["envFrom"]
    sup_env = {k: v for k, v in _env(sup).items() if not k.startswith("IAGENT_ANSWER_")}
    assert sup_env == _env(uc)
    assert sup["volumeMounts"] == uc["volumeMounts"]
    assert "src.iagent.supervisor_service:app" in sup["command"]


def test_the_app_the_command_names_serves_the_paths_the_chart_calls():
    src = (_REPO / "src" / "iagent" / "supervisor_service.py").read_text(encoding="utf-8")
    assert "\napp = FastAPI(" in src
    assert '@app.get("/healthz")' in src
    assert 'app.mount("/restate"' in src
    sup = _container(_one(_render(*_ON), "Deployment", f"{_RELEASE}-supervisor"))
    assert sup["readinessProbe"]["httpGet"]["path"] == "/healthz"


def test_restate_init_waits_for_and_registers_the_service_on_its_port():
    docs = _render(*_ON)
    svc = _one(docs, "Service", f"{_RELEASE}-supervisor")
    (port,) = [p["port"] for p in svc["spec"]["ports"]]
    sup = _container(_one(docs, "Deployment", f"{_RELEASE}-supervisor"))
    assert [p["containerPort"] for p in sup["ports"]] == [port]
    assert f"--port\n{port}" in "\n".join(sup["command"])
    script = _restate_init_script(docs)
    assert f"{_RELEASE}-supervisor." in script
    assert f":{port}/healthz" in script
    assert f':{port}/restate", "force": true' in script
