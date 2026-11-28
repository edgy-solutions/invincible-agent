"""The chart writes the two routing limits, and refuses to render them in the wrong order.

`ROUTE_INTENT_TIMEOUT_S` (outer, cortex-bff's wait for /route_intent, 180 s) and
`ROUTE_INTENT_MODEL_TIMEOUT_S` (inner, engine O's limit on the routing model call, 150 s) are in
the shared ConfigMap both services read. The inner must be shorter: a pair in the wrong order, or a
value that is not a positive number, stops the render with a message naming both settings.

Run: uv run pytest tests/perf/test_the_routing_limits_are_ordered_chart.py -q
"""
from __future__ import annotations

import shutil

import pytest

from tests.test_oidc_broker_chart import _BROKER_OFF, _SANDBOX, _docs, _render, _render_fails, _set

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")

OUTER, INNER = "ROUTE_INTENT_TIMEOUT_S", "ROUTE_INTENT_MODEL_TIMEOUT_S"
_CONFIG = "t-config"


def _data(rendered: str) -> dict:
    found = [d for d in _docs(rendered) if d["kind"] == "ConfigMap" and d["metadata"]["name"] == _CONFIG]
    assert len(found) == 1, f"expected one {_CONFIG} ConfigMap, found {len(found)}"
    return found[0]["data"]


def _count(rendered: str, key: str) -> int:
    """How many times the key is written in the ConfigMap's own text (a duplicate parses silently)."""
    chunks = [c for c in rendered.split("\n---") if f"name: {_CONFIG}\n" in c and "kind: ConfigMap" in c]
    assert len(chunks) == 1
    return sum(1 for line in chunks[0].splitlines() if line.strip().startswith(f"{key}:"))


def _env(**kv) -> list[str]:
    return [a for k, v in kv.items() for a in _set(f"agentFleet.env.{k}", v)]


def test_the_defaults_are_written_in_order():
    data = _data(_render())
    assert (data[OUTER], data[INNER]) == ("180", "150")


def test_the_sandbox_renders_the_same_defaults():
    rendered = _render(*_SANDBOX, *_BROKER_OFF)
    assert (_data(rendered)[OUTER], _data(rendered)[INNER]) == ("180", "150")
    assert _count(rendered, OUTER) == 1 and _count(rendered, INNER) == 1


def test_an_override_in_order_wins_and_each_key_is_written_once():
    rendered = _render(*_env(ROUTE_INTENT_TIMEOUT_S="240", ROUTE_INTENT_MODEL_TIMEOUT_S="200"))
    assert (_data(rendered)[OUTER], _data(rendered)[INNER]) == ("240", "200")
    assert _count(rendered, OUTER) == 1 and _count(rendered, INNER) == 1


@pytest.mark.parametrize("env", [
    {INNER: "200"},                       # inner above the outer default
    {OUTER: "120"},                       # outer below the inner default
    {INNER: "180"},                       # equal is not shorter
    {OUTER: "300", INNER: "300"},
    {INNER: "0"},
    {OUTER: "soon"},
    {INNER: "-1"},
])
def test_a_pair_out_of_order_or_not_a_positive_number_does_not_render(env):
    err = _render_fails(*_env(**env))
    assert OUTER in err and INNER in err, err[-600:]
    assert "shorter than" in err, err[-600:]


def test_control_one_second_apart_renders():
    data = _data(_render(*_env(ROUTE_INTENT_TIMEOUT_S="151")))
    assert (data[OUTER], data[INNER]) == ("151", "150")
