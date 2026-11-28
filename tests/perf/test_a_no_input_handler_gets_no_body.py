"""Restate's ingress answers 400 to a body sent to a handler that declares no input.

The doubles used to accept any body, so `json={}` on reserve/release/snapshot/withdraw was never
caught. The census reads durable_answers.py's own calls; the control proves the double refuses.
"""
from __future__ import annotations

import ast
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.perf import _restate_wire as wire  # noqa: E402
from tests.perf.test_answer_admission import Mesh  # noqa: E402

SRC = ROOT / "src" / "iagent" / "durable_answers.py"
BODY_KWARGS = {"json", "content", "data"}


def _handler_of(url_node):
    """The handler segment after `{answer_id}/` in a `/SupervisorAnswer/` f-string, else None."""
    if not isinstance(url_node, ast.JoinedStr):
        return None
    text = "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in url_node.values)
    if "/SupervisorAnswer/" not in text:
        return None
    tail = text.split("/SupervisorAnswer/", 1)[1].partition("/")[2]
    return tail[: -len("/send")] if tail.endswith("/send") else tail


def _calls():
    found = []
    for node in ast.walk(ast.parse(SRC.read_text(encoding="utf-8"))):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "post" and node.args):
            handler = _handler_of(node.args[0])
            if handler is not None:
                found.append((handler, any(k.arg in BODY_KWARGS for k in node.keywords), node.lineno))
    return found


def test_every_supervisor_answer_call_matches_its_handlers_input():
    calls = _calls()
    assert {h for h, _, _ in calls} >= {"reserve", "release", "snapshot", "withdraw", "run"}, calls
    for handler, has_body, line in calls:
        assert has_body == wire.handler_declares_input(handler), (
            f"handler {handler!r} (durable_answers.py:{line}): body sent={has_body}, "
            f"declares input={wire.handler_declares_input(handler)}")


def test_the_double_refuses_a_body_like_the_ingress():
    mesh = Mesh()
    url = "http://r:8080/SupervisorAnswer/a1/snapshot"
    assert asyncio.run(mesh.post(url, json={})).status_code == 400
    assert asyncio.run(mesh.post(url)).status_code != 400
