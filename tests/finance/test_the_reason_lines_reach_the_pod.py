"""The reason lines reach the pod's log at INFO, only when nothing else would emit them.

The architect, 2026-11-25: "INFO lines must show in the pod. The point of #561 is that an operator
can see not_a_member without asking us." The engine's logger has effective level WARNING and no
handler in a pod, so an INFO line was discarded. `_ensure_reasons_visible` mirrors the SDK's
`ensure_gauge_visible`: additive and deferential.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from agent_fleet.finance_agent import main as engine  # noqa: E402

CHILD = """
import collections, sys
sys.path.insert(0, {repo!r})
from agent_fleet.finance_agent import main as e
e._log_empty("fin.resolve_empty", identifier="x", class_uri=None, seen=1,
             withheld=collections.Counter({{"not_a_member": 1}}), user_email="", reason="not_a_member")
"""
WANT = "INFO:agent_fleet.finance_agent.main.reasons:fin.resolve_empty reason=not_a_member"


def _child(autoconfig: str | None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop("FIN_REASON_LOG_AUTOCONFIG", None)
    if autoconfig is not None:
        env["FIN_REASON_LOG_AUTOCONFIG"] = autoconfig
    return subprocess.run(
        [sys.executable, "-c", CHILD.format(repo=str(REPO))],
        cwd=str(REPO), env=env, capture_output=True, text=True, timeout=300,
    )


def test_the_pod_shape_shows_the_not_a_member_line_on_stdout():
    r = _child(None)
    assert r.returncode == 0, r.stderr[-800:]
    assert any(line.startswith(WANT) for line in r.stdout.splitlines()), r.stdout[-800:]


def test_the_witness_switch_silences_it():
    r = _child("0")
    assert r.returncode == 0, r.stderr[-800:]
    assert "reason=not_a_member" not in r.stdout
    assert "reason=not_a_member" not in r.stderr


def _bare(parent_handler: bool = False):
    parent = logging.Logger("bare")
    child = logging.Logger("bare.reasons")
    child.parent = parent
    parent.setLevel(logging.WARNING)  # a pod's root: WARNING, no handler
    if parent_handler:
        h = logging.StreamHandler(open(os.devnull, "w"))
        h.setLevel(logging.INFO)
        parent.addHandler(h)
        parent.setLevel(logging.INFO)
    return parent, child


def test_an_upstream_info_handler_means_no_second_handler(monkeypatch):
    monkeypatch.delenv("FIN_REASON_LOG_AUTOCONFIG", raising=False)
    _parent, child = _bare(parent_handler=True)
    monkeypatch.setattr(engine, "_reason_log", child)
    assert engine._ensure_reasons_visible() is False
    assert child.handlers == []
    assert child.level == logging.NOTSET


def test_two_calls_on_a_bare_chain_attach_exactly_one_handler(monkeypatch):
    monkeypatch.delenv("FIN_REASON_LOG_AUTOCONFIG", raising=False)
    parent, child = _bare()
    monkeypatch.setattr(engine, "_reason_log", child)
    assert engine._ensure_reasons_visible() is True
    assert engine._ensure_reasons_visible() is False
    assert len(child.handlers) == 1
    assert parent.handlers == []
    assert child.level == logging.INFO
