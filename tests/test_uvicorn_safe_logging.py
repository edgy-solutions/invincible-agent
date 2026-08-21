"""LOGGERS THAT SURVIVE UVICORN — the meta-defect's seal.

uvicorn replaces the root handler at startup, so any logger relying on
propagation is silently DROPPED. Not downgraded, not buffered: dropped, while
the process stays healthy and its access logs keep flowing — which is what makes
it invisible.

WHAT IT COST, 2026-08-21: engine-f registered ten presentations through the
mesh-registrar gateway and printed NOTHING. Not the success line, not the
fallback line, not the three-way refusal classification built specifically so an
operator could tell "ship the image" from "fix the registration" from "check the
network". The discriminator worked perfectly into a log nobody could read. And a
retirement trigger written that same hour keyed on `grep "VIA GATEWAY"` — a
condition that could never be observed, therefore not a condition.

Two engines had each discovered this and hand-rolled the repair on their OWN
named logger. Neither reached the shared module both delegate to. The pattern
drifted because it was per-module; this helper exists so it stops being.

Run: uv run --frozen --with pytest pytest tests/test_uvicorn_safe_logging.py -v
"""
from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SRC = _REPO / "agent_fleet" / "utils" / "uvicorn_safe_logging.py"


def _mod():
    spec = importlib.util.spec_from_file_location("uvicorn_safe_logging__test", _SRC)
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


def test_records_survive_a_root_handler_replacement(capsys):
    """THE ACTUAL DEFECT, reproduced: uvicorn swaps the root handler after our
    module is imported. A propagating logger goes silent; this one must not."""
    m = _mod()
    log = m.ensure_stdout_logger("iagent_test_survivor")

    # Simulate uvicorn's reconfiguration AFTER setup, which is the real ordering.
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)

    log.info("registered VIA GATEWAY")
    assert "registered VIA GATEWAY" in capsys.readouterr().out


def test_a_propagating_logger_would_have_been_silent(capsys):
    """THE DISCRIMINATING CONTROL. Without this, the test above could pass for
    reasons unrelated to the fix — it must be shown that the OLD shape actually
    loses the record under the same conditions."""
    bare = logging.getLogger("iagent_test_bare")
    bare.handlers.clear()
    bare.propagate = True

    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)

    bare.info("this record is lost")
    assert "this record is lost" not in capsys.readouterr().out


def test_it_is_idempotent_across_repeated_imports(capsys):
    """Several modules call this for the same name; handlers must not stack, or
    every line prints N times and the log becomes its own noise problem."""
    m = _mod()
    for _ in range(4):
        log = m.ensure_stdout_logger("iagent_test_idem")
    log.info("once")
    assert capsys.readouterr().out.count("once") == 1


def test_a_foreign_handler_does_not_suppress_ours(capsys):
    """Idempotency keys on OUR tagged handler, not on 'has any handler'. A
    library that attaches its own would otherwise make this a no-op and restore
    exactly the silence it exists to prevent."""
    m = _mod()
    name = "iagent_test_foreign"
    logging.getLogger(name).addHandler(logging.NullHandler())
    log = m.ensure_stdout_logger(name)
    log.info("still audible")
    assert "still audible" in capsys.readouterr().out


def test_propagate_is_off_so_records_do_not_double_print(capsys):
    """Under a root that IS configured, propagation would print twice."""
    m = _mod()
    log = m.ensure_stdout_logger("iagent_test_nodup")
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(logging.StreamHandler(stream=sys.stdout))
    log.warning("exactly once")
    assert capsys.readouterr().out.count("exactly once") == 1


def test_level_is_settable_from_the_environment(monkeypatch):
    """Verbosity must be changeable without a code change — impossible while the
    records were being dropped outright."""
    m = _mod()
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    log = m.ensure_stdout_logger("iagent_test_level")
    assert log.level == logging.WARNING
