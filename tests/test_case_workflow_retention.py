"""A case's Restate workflow is kept for CASE_WORKFLOW_RETENTION_DAYS (default 30) after it
completes (ruled 2026-10-16, the belt to the Postgres case summary's braces). Restate's own default
is 1 day. restate-sdk 0.14.0 has no `Workflow(workflow_retention=...)`: the retention rides on the
`@workflow_runner.main(...)` handler and is emitted as `workflowCompletionRetention` in discovery.

The module is loaded as a PRIVATE COPY under a throwaway name for each env value, so the module
object the executor and the other tests registered is never reloaded or replaced.

Arms:
  default   no env -> 30 days, on the handler and in the discovery JSON the runtime registers.
  env       45 -> 45 days.
  refuse    0, negative, blank-to-garbage -> the import fails with a message naming the variable.
  scope     only the main handler carries it.

Run: uv run pytest tests/test_case_workflow_retention.py -v
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import timedelta
from pathlib import Path

import pytest

pytest.importorskip("restate")
from restate.discovery import compute_discovery_json  # noqa: E402
from restate.endpoint import Endpoint  # noqa: E402

_SRC = Path(__file__).resolve().parents[1] / "agent_fleet" / "restate_analyst" / "workflow_runner.py"
_VAR = "CASE_WORKFLOW_RETENTION_DAYS"
for _p in (str(_SRC.parent), str(_SRC.parents[2])):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _load_copy():
    spec = importlib.util.spec_from_file_location("workflow_runner_retention_probe", _SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # deliberately NOT put in sys.modules
    return mod


def _discovered_ms(mod) -> dict:
    ep = Endpoint()
    ep.bind(mod.workflow_runner)
    doc = json.loads(compute_discovery_json(ep, 3, "bidi"))
    (svc,) = [s for s in doc["services"] if s["name"] == "WorkflowRunner"]
    return {h["name"]: h.get("workflowCompletionRetention") for h in svc["handlers"]}


def test_the_default_is_thirty_days(monkeypatch):
    monkeypatch.delenv(_VAR, raising=False)
    mod = _load_copy()
    assert mod.workflow_runner.handlers["run"].workflow_retention == timedelta(days=30)
    assert _discovered_ms(mod)["run"] == 30 * 24 * 3600 * 1000


def test_the_environment_sets_the_days(monkeypatch):
    monkeypatch.setenv(_VAR, "45")
    mod = _load_copy()
    assert mod.workflow_runner.handlers["run"].workflow_retention == timedelta(days=45)
    assert _discovered_ms(mod)["run"] == 45 * 24 * 3600 * 1000


def test_only_the_main_handler_carries_a_retention(monkeypatch):
    monkeypatch.delenv(_VAR, raising=False)
    carried = {name: ms for name, ms in _discovered_ms(_load_copy()).items() if ms is not None}
    assert list(carried) == ["run"]


@pytest.mark.parametrize("bad", ["0", "-3", "abc", "1.5"])
def test_fewer_than_one_day_or_not_a_number_refuses_the_import(monkeypatch, bad):
    monkeypatch.setenv(_VAR, bad)
    with pytest.raises(RuntimeError, match=_VAR):
        _load_copy()


def test_the_module_the_executor_registers_carries_the_configured_retention():
    import workflow_runner as wr  # the harness's module object; sys.path set there

    assert wr.workflow_runner.handlers["run"].workflow_retention == wr.CASE_WORKFLOW_RETENTION
    assert wr.CASE_WORKFLOW_RETENTION >= timedelta(days=1)
