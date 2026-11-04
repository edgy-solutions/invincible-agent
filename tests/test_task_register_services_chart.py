"""`TASK_REGISTER_SERVICES` is rendered from `keycloak.taskRegisterServices` as a JSON list.

cortex-bff's `_task_register_services()` reads the env var; if the chart renders it differently
(wrong key, a Python repr, no value) every service register is refused 403. Only the ConfigMap is
rendered (`--show-only`), so no Secret is ever rendered.

Run: uv run pytest tests/test_task_register_services_chart.py -q
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")

_REPO = Path(__file__).resolve().parents[1]
_CHART = _REPO / "helm/invincible-agent"


def _config(*args):
    r = subprocess.run(
        ["helm", "template", "t", str(_CHART), "--show-only", "templates/configmap.yaml", *args],
        capture_output=True, text=True, encoding="utf-8", timeout=300)
    assert r.returncode == 0, r.stderr[-1500:]
    for d in yaml.safe_load_all(r.stdout):
        if d and d["kind"] == "ConfigMap" and d["metadata"]["name"] == "t-config":
            return d["data"]
    raise AssertionError("no t-config ConfigMap")


def test_the_env_is_the_values_list_as_json():
    want = yaml.safe_load((_CHART / "values.yaml").read_text(encoding="utf-8"))["keycloak"]["taskRegisterServices"]
    assert want, "the chart lists no register service"
    assert json.loads(_config()["TASK_REGISTER_SERVICES"]) == want


def test_a_changed_list_is_rendered_and_an_emptied_one_is_an_empty_list():
    got = _config("--set-json", 'keycloak.taskRegisterServices=["svc:one"]')
    assert json.loads(got["TASK_REGISTER_SERVICES"]) == ["svc:one"]
    got = _config("--set-json", "keycloak.taskRegisterServices=[]")
    assert json.loads(got["TASK_REGISTER_SERVICES"]) == []


def test_the_env_sits_beside_the_delegate_map():
    data = _config()
    assert {"DELEGATE_ON_BEHALF_OF", "TASK_REGISTER_SERVICES"} <= set(data)
