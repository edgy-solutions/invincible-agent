"""The register gate's service list is NOT chart config (architect 11-04).

cortex-bff's `_task_register_services()` reads the `door: bff` rows of `policy/gateway_delegates.yaml`.
The chart no longer renders `TASK_REGISTER_SERVICES`: a leftover key would look like the list and
change nothing. Only the ConfigMap is rendered (`--show-only`), so no Secret is ever rendered.

Run: uv run pytest tests/test_the_register_list_is_not_chart_config.py -q
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")

_REPO = Path(__file__).resolve().parents[1]
_CHART = _REPO / "helm/invincible-agent"


def _config():
    r = subprocess.run(
        ["helm", "template", "t", str(_CHART), "--show-only", "templates/configmap.yaml"],
        capture_output=True, text=True, encoding="utf-8", timeout=300)
    assert r.returncode == 0, r.stderr[-1500:]
    for d in yaml.safe_load_all(r.stdout):
        if d and d["kind"] == "ConfigMap" and d["metadata"]["name"] == "t-config":
            return d["data"]
    raise AssertionError("no t-config ConfigMap")


def test_the_configmap_has_no_task_register_services_key():
    data = _config()
    assert "DELEGATE_ON_BEHALF_OF" in data, "positive control: the delegate map is still rendered"
    assert "TASK_REGISTER_SERVICES" not in data
