"""Shared pytest fixtures.

CAPLOG AND NON-PROPAGATING LOGGERS (2026-08-21)
-----------------------------------------------
`agent_fleet/utils/uvicorn_safe_logging.ensure_stdout_logger` sets
`propagate = False` on the loggers it configures. It has to: uvicorn replaces
the root handler at startup, so a logger that depends on propagation is silently
DROPPED — which is how engine-f registered ten presentations through the mesh
gateway and printed nothing at all.

But pytest's `caplog` captures through a handler on the ROOT logger, so
`propagate = False` makes it capture nothing either, and seven existing tests
that assert on `caplog.records` for "mesh_registration" went red the moment the
shared module was fixed.

BOTH REQUIREMENTS ARE REAL and neither should bend:
  * production must be AUDIBLE — that is the whole defect;
  * tests must be able to OBSERVE what production says — otherwise the audible
    line is untested and drifts.

So the test harness adapts rather than the production logger. This attaches
caplog's own handler directly to the non-propagating loggers, which is the
documented pytest idiom for exactly this case. The alternative — re-enabling
propagation to satisfy the tests — would trade a real production defect for a
green suite, which is the trade this whole arc exists to refuse.
"""
from __future__ import annotations

import logging

import pytest

# Loggers configured by ensure_stdout_logger that tests assert against. Adding a
# name here is cheaper than rediscovering why caplog is empty.
_NON_PROPAGATING = ("mesh_registration",)


@pytest.fixture(autouse=True)
def _caplog_sees_non_propagating_loggers(caplog):
    """Let caplog observe loggers that deliberately do not propagate.

    Autouse so a test asserting on these records does not have to know that the
    logger is non-propagating — the knowledge lives here, once.
    """
    attached = []
    for name in _NON_PROPAGATING:
        lg = logging.getLogger(name)
        if caplog.handler not in lg.handlers:
            lg.addHandler(caplog.handler)
            attached.append(lg)
    try:
        yield
    finally:
        for lg in attached:
            lg.removeHandler(caplog.handler)
