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
import sys

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


#: Modules that test files replace with hand-built stubs to avoid importing heavy deps.
#: Anything listed here is snapshotted before each test module and restored after it.
_STUBBED_GLOBALS = ("baml_client", "dagster")


@pytest.fixture(scope="module", autouse=True)
def _restore_globally_stubbed_modules():
    """PUT sys.modules BACK after any module that stubbed a shared dependency.

    THE DEFECT, measured 2026-09-04. Five test files install a hand-built `baml_client`
    stub -- a bare ModuleType with no `__path__` -- and none of them removed it. It is
    process-global, so every file that ran afterwards inherited it, and any of them
    importing a SUBMODULE (`baml_client.types`) failed with "is not a package".
    `tests/routing` and `tests/planning` each passed alone and failed together, eleven
    tests deep in a suite that mentions neither stubbing nor baml.

    AND THE FIRST REPAIR FIXED ONE FILE OF FIVE. I added a teardown to the file I had
    open, verified the pair that had failed, and described it as closing the pollution --
    the remembered-population defect inside the fix for a remembered-population defect.
    The count came from grepping for the stub afterwards: five install it, one restored it.

    SO IT LIVES HERE INSTEAD OF IN EACH FILE. Those files duplicate their stubs on purpose
    (each gate is meant to be self-contained), and that is fine -- what must NOT be
    per-file is the cleanup, because a new file that stubs and forgets reintroduces the
    whole class. Module-scoped and autouse: for a module that stubs nothing the snapshot
    equals the restore and this is a no-op.
    """
    # THE WHOLE SUBTREE, not just the top name. Restoring only "baml_client" leaves
    # sys.modules["baml_client.types"] behind while the parent object that should carry
    # "types" as an ATTRIBUTE has been swapped -- so "baml_client.types.AgentStatus"
    # resolves the submodule and then fails on the attribute. Measured: restoring the
    # parent alone traded eleven failures for seventeen.
    def _snapshot():
        return {k: v for k, v in sys.modules.items()
                if any(k == n or k.startswith(n + ".") for n in _STUBBED_GLOBALS)}

    saved = _snapshot()
    yield
    for k in list(_snapshot()):
        if k not in saved:
            sys.modules.pop(k, None)
    sys.modules.update(saved)
