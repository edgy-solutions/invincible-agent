"""IAGENT_TRACE_MODEL_TEXT: model text reaches a Langfuse generation only where a deployment declares it.

The architect (2026-11-24, amending the 11-15 "no model text in any span" ruling): engine O records each
model call as a generation always (model, temperature, effort, token counts, hashes); the rendered prompt
and the reply as TEXT only where this setting is "on". Off by default; the sandbox sets "on".

Run: uv run --frozen python -m pytest tests/perf/test_model_text_reaches_a_trace_only_where_declared_chart.py -v
"""
from __future__ import annotations

import shutil

import pytest
import yaml

from tests.test_oidc_broker_chart import _BROKER_OFF, _SANDBOX, _docs, _render, _set

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")

_KEY = "IAGENT_TRACE_MODEL_TEXT"
_CONFIG = "t-config"


def _config_doc(rendered: str) -> dict:
    found = [d for d in _docs(rendered) if d["kind"] == "ConfigMap" and d["metadata"]["name"] == _CONFIG]
    assert len(found) == 1, f"expected one {_CONFIG} ConfigMap, found {len(found)}"
    return found[0]


def _raw_key_count(rendered: str) -> int:
    """How many times the key is written in the ConfigMap's own YAML text (a duplicate key parses silently)."""
    chunks = [c for c in rendered.split("\n---") if f"name: {_CONFIG}\n" in c and "kind: ConfigMap" in c]
    assert len(chunks) == 1, f"expected one raw {_CONFIG} ConfigMap, found {len(chunks)}"
    return sum(1 for line in chunks[0].splitlines() if line.strip().startswith(f"{_KEY}:"))


def test_the_default_render_is_off():
    assert _config_doc(_render())["data"].get(_KEY) == "off"


def test_the_sandbox_is_on():
    assert _config_doc(_render(*_SANDBOX, *_BROKER_OFF))["data"].get(_KEY) == "on"


def test_the_sandbox_file_declares_it():
    sb = yaml.safe_load(open(_SANDBOX[1], encoding="utf-8"))
    assert sb["agentFleet"]["env"].get(_KEY) == "on"


def test_a_deployment_override_wins_and_the_key_is_written_once():
    rendered = _render(*_SANDBOX, *_BROKER_OFF, *_set(f"agentFleet.env.{_KEY}", "off"))
    assert _config_doc(rendered)["data"].get(_KEY) == "off"
    assert _raw_key_count(rendered) == 1


def test_control_the_sandbox_key_is_also_written_once():
    assert _raw_key_count(_render(*_SANDBOX, *_BROKER_OFF)) == 1
    assert _raw_key_count(_render()) == 1
