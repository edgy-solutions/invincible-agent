"""`/workflow/start` is disabled by default, and the refusal EXPLAINS ITSELF.

THE DECISION THIS PINS (2026-08-11). An ungated action route with no consumer is withdrawn rather
than classified. The gate on doing it was *verify no consumer across ALL repos, THEN disable* —
never disable-and-discover, which manufactures the silent-refusal class this arc spent a week
removing. The condition was met at 5 of 5 repos, with the doc-tools and dag-tools negatives
established by ENDPOINT ENUMERATION rather than call-site grep, which is what makes "zero" a
bound rather than a hope.

WHY 410 AND NOT DELETION, and why the body matters. Verification bounds the risk of disabling; a
self-explaining refusal bounds the cost of having been WRONG about it. A 404 is indistinguishable
from a bad ingress, a typo, or a routing mistake — it sends a caller hunting the wrong problem. A
410 naming the ruling, the packet and the re-enable switch turns "the sweep missed me" from a
mystery into a one-line report.

THE PINS ARE SOURCE-LEVEL FIRST. `main.py` pulls smolagents/baml/orchestrator, and an import
failure would make these pass-by-vacuum in exactly the environments that matter least. The source
pins hold regardless; the behavioural test runs when the module imports.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_MAIN = _ROOT / "agent_fleet" / "restate_analyst" / "main.py"


def _src() -> str:
    return _MAIN.read_text(encoding="utf-8")


def _route_body() -> str:
    src = _src()
    m = re.search(r"async def start_workflow\(.*?(?=\n# ---|\n@app\.)", src, re.S)
    assert m, "start_workflow not found — this pin is measuring nothing"
    return m.group(0)


# ---------------------------------------------------------------------------
# The disable itself
# ---------------------------------------------------------------------------
def test_the_route_is_gated_on_the_flag():
    assert "if not ENABLE_WORKFLOW_START:" in _route_body(), (
        "the route no longer checks the disable flag"
    )


def test_the_default_is_OFF():
    """Default-off is the decision. A default-on flag would leave the route live everywhere
    nobody set it, which is every environment that matters."""
    src = _src()
    m = re.search(r'ENABLE_WORKFLOW_START\s*=\s*os\.getenv\(\s*"ENABLE_WORKFLOW_START"\s*,\s*"([^"]+)"',
                  src)
    assert m, "the flag is no longer read from ENABLE_WORKFLOW_START with an explicit default"
    assert m.group(1).lower() in ("false", "0", "no"), (
        f"default is {m.group(1)!r} — /workflow/start must be OFF unless explicitly enabled"
    )


def test_the_refusal_is_410_not_404():
    """404 is indistinguishable from a routing mistake and sends the caller after the wrong
    problem. 410 says: this existed, it was withdrawn on purpose."""
    body = _route_body()
    assert "status_code=410" in body, "the disabled refusal must be 410 GONE"
    assert "status_code=404" not in body


def test_the_refusal_NAMES_the_decision_and_the_way_back():
    """A disabled route that cannot explain itself is the silent refusal this decision exists to
    avoid, wearing a different status code."""
    body = _route_body()
    assert "endpoint-gating-undeclared-routes-recommendation" in body, (
        "the refusal must cite the packet that ruled it"
    )
    assert "ENABLE_WORKFLOW_START=true" in body, "the refusal must name the re-enable switch"


def test_a_call_while_disabled_is_LOGGED():
    """The one event that would falsify the sweep is a real caller arriving. It must leave a
    trace at the moment it happens, not only in whatever the caller chooses to report."""
    body = _route_body()
    assert re.search(r"logger\.(warning|error)\(", body), (
        "a call to the disabled route must be logged — it is the sweep's falsification signal"
    )


# ---------------------------------------------------------------------------
# The posture is observable WITHOUT calling the route
# ---------------------------------------------------------------------------
def test_the_posture_is_ANNOUNCED_at_startup():
    """[[flag-effects-must-be-observable]]. An operator must be able to learn which state this
    pod is in without sending a request to a route they have been told not to use."""
    src = _src()
    assert "_workflow_start_posture_line" in src
    assert re.search(r"logger\.info\(_workflow_start_posture_line\(\)\)", src), (
        "the workflow/start posture is not announced at startup"
    )


def test_the_posture_line_names_its_SOURCE():
    """`DISABLED (default)` and `DISABLED (explicit config)` are different claims about whether
    anyone decided."""
    src = _src()
    m = re.search(r"def _workflow_start_posture_line.*?(?=\n\n\n|\ndef )", src, re.S)
    assert m, "posture-line helper missing"
    assert "explicit config" in m.group(0) and "default" in m.group(0)


# ---------------------------------------------------------------------------
# Behavioural — runs when the heavy module imports
# ---------------------------------------------------------------------------
def _main_module():
    """Import engine-a's main, adding the path its own internals assume.

    `main.py` does `from orchestrator.auth import ...` — an import that only resolves when
    `agent_fleet/restate_analyst` is itself on `sys.path` (the container flattens the directory).
    Other suites happen to put it there, which is why `test_restate_analyst.py` collects in a big
    batch and fails in a small one — the ordering coupling filed in `suite-signal`.

    Inserted HERE rather than at module import, deliberately: doing it at collection time would
    mutate `sys.path` for every other test file in the session, which is the same ambient-state
    coupling being worked around. Scoped to the tests that need it, the fix cannot spread.
    """
    import sys
    ra = str(_ROOT / "agent_fleet" / "restate_analyst")
    if ra not in sys.path:
        sys.path.insert(0, ra)
    return pytest.importorskip(
        "agent_fleet.restate_analyst.main",
        reason="engine-a's main pulls smolagents/baml; source pins above still hold",
    )


def test_disabled_route_returns_410_with_the_reason(monkeypatch):
    mod = _main_module()
    monkeypatch.setattr(mod, "ENABLE_WORKFLOW_START", False, raising=False)

    req = mod.WorkflowStartRequest(workflow_id="wf_probe", tasks=[])
    resp = asyncio.run(mod.start_workflow(req))

    assert resp.status_code == 410
    payload = json.loads(resp.body)
    assert "disabled" in payload["error"]
    assert "ENABLE_WORKFLOW_START" in payload["re_enable"]
    assert payload["decision"].endswith(".md")


def test_disabled_route_does_NOT_reach_restate(monkeypatch):
    """The refusal must short-circuit BEFORE the proxy call. A route that refuses after
    dispatching has disabled nothing."""
    mod = _main_module()
    monkeypatch.setattr(mod, "ENABLE_WORKFLOW_START", False, raising=False)

    called = {"n": 0}

    def _boom(*a, **k):
        called["n"] += 1
        raise AssertionError("disabled route reached the Restate ingress")

    monkeypatch.setattr(mod.requests, "post", _boom)
    resp = asyncio.run(mod.start_workflow(mod.WorkflowStartRequest(workflow_id="w", tasks=[])))
    assert resp.status_code == 410
    assert called["n"] == 0


def test_ENABLING_it_restores_the_proxy(monkeypatch):
    """THE BREAK-ON-PURPOSE LEG. A disable whose re-enable path was never exercised is a
    one-way door nobody has tried to open — and the 410 body promises it works."""
    mod = _main_module()
    monkeypatch.setattr(mod, "ENABLE_WORKFLOW_START", True, raising=False)

    seen = {}

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            return None

    def _post(url, json=None, headers=None, timeout=None):
        seen["url"] = url
        seen["json"] = json
        return _Resp()

    monkeypatch.setattr(mod.requests, "post", _post)
    resp = asyncio.run(mod.start_workflow(mod.WorkflowStartRequest(workflow_id="wf_1", tasks=[])))

    assert resp.status_code == 202
    assert "BPMNWorkflowRunner/wf_1/run" in seen["url"], "the re-enabled route must still proxy"
