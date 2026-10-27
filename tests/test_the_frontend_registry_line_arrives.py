"""The frontend-registry logger's INFO lines (`frontend_menu_replayed` ...) must ARRIVE: the process
root handler sits at WARNING, so the logger needs its own level and a handler
(`_ensure_the_audit_line_actually_ARRIVES`, as for the two other BFF loggers)."""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from src.iagent import gateway  # noqa: E402

NAME = "iagent.registry.frontend_capabilities"


def test_arm1_the_logger_is_effectively_at_info():
    assert logging.getLogger(NAME).getEffectiveLevel() <= logging.INFO


def test_arm2_it_can_emit_info_under_a_warning_root_with_no_handlers():
    from src.iagent.identity_vault import _ensure_the_audit_line_actually_ARRIVES as ensure

    lg = logging.getLogger(NAME)
    root = logging.getLogger()
    saved = (lg.level, list(lg.handlers), lg.propagate, root.level, list(root.handlers))
    try:
        root.handlers[:] = []
        root.setLevel(logging.WARNING)
        lg.handlers[:] = []
        lg.setLevel(logging.NOTSET)
        ensure(lg)
        assert lg.isEnabledFor(logging.INFO)
        assert lg.handlers or root.handlers
    finally:
        lg.level, lg.propagate = saved[0], saved[2]
        lg.handlers[:] = saved[1]
        root.setLevel(saved[3])
        root.handlers[:] = saved[4]


def test_arm3_gateway_wires_the_call():
    src = Path(gateway.__file__).read_text(encoding="utf-8")
    assert "_ensure_the_audit_line_actually_ARRIVES(_frontend_registry_logger)" in src
