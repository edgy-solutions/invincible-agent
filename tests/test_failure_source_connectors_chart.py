"""saf B2: the chart carries FAILURE_SOURCE_CONNECTORS to engine-safety, and only when chosen.

`agent_fleet/safety_agent/failure_source.py` reads the variable: ABSENT means the sandbox fixture,
SET means ONLY the named connectors. So the chart must render the key exactly when a deployment
names connectors, never as an empty string, and the sandbox must not name any -- no connector
module ships in an image yet, and a value would refuse every FRACAS question.

The render is `helm template`, the same instrument tests/test_oidc_broker_chart.py uses.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

_CHART = str(Path(__file__).resolve().parents[1] / "helm" / "invincible-agent")
_SANDBOX = str(Path(_CHART) / "values-sandbox.yaml")
_KEY = "FAILURE_SOURCE_CONNECTORS"

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not on PATH")


def _config(*args: str) -> str:
    """The shared `-config` ConfigMap's text, from a real render."""
    out = subprocess.run(
        ["helm", "template", "t", _CHART, "--show-only", "templates/configmap.yaml", *args],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert out.returncode == 0, out.stderr
    docs = [d for d in out.stdout.split("\n---") if re.search(r"name: t-config\b", d)]
    assert len(docs) == 1, f"expected one t-config ConfigMap, found {len(docs)}"
    return docs[0]


def _values(doc: str) -> list:
    return re.findall(rf"^\s+{_KEY}:\s*(.*)$", doc, re.M)


def test_the_base_render_names_no_connectors():
    assert _values(_config()) == []


def test_the_sandbox_render_names_no_connectors():
    """The sandbox keeps the fixture. A value here is the B1 overlay image's to justify."""
    assert _values(_config("-f", _SANDBOX)) == []


def test_a_named_connector_reaches_the_configmap_verbatim(tmp_path):
    """Through a VALUES FILE, as a deployment sets it: `--set` splits on the comma the format uses."""
    v = "sor=acme.sor:build,rel=acme.relyence:build"
    f = tmp_path / "values-connectors.yaml"
    f.write_text(f'engineSafety:\n  failureSourceConnectors: "{v}"\n', encoding="utf-8")
    assert _values(_config("-f", str(f))) == [f'"{v}"']


def test_an_explicit_agent_fleet_env_entry_wins_and_the_key_is_rendered_once():
    doc = _config(
        "--set-string", "engineSafety.failureSourceConnectors=a=m:f",
        "--set-string", f"agentFleet.env.{_KEY}=b=n:g",
    )
    assert _values(doc) == ['"b=n:g"']
