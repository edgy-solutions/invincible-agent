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
from pathlib import Path

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


# ═══════════════════════════════════════════════════════════════════════════════════════
# THE SUITE REFUSES A DIRTY TREE AT EXIT, the way the roll refuses an unsettled fleet.
#
# RULED 2026-09-12. A full run mutated `docs/BOARD.md` and I found it by diffing the tree
# afterwards rather than by noticing — and diffing afterwards is a habit, not a check. Two
# consequences, neither of which announces itself:
#
#   1. THE RUN MEASURED A TREE THAT WAS MOVING. A suite run measures the tree for its whole
#      duration; if the run itself is one of the things changing it, the result belongs to no
#      single state. That is the same defect as editing a file mid-run, with the suite as the
#      editor.
#   2. THE MUTATION GETS STAGED. In a shared tree `git add -A` after a green sweeps the
#      generated change into a commit whose message says something else — and the message is
#      what the next reader trusts.
#
# WHY AT EXIT AND NOT AT START. A dirty tree at START is ordinary work in progress and refusing
# it would make the suite unusable. The claim here is narrower and always true: *the suite must
# not be what changed the tree*. So the baseline is taken at session start and compared at
# session end, and only files the RUN touched are named.
#
# WHY A WARNING WOULD NOT DO. The runbook's own killed-client trap already records that a
# warning in a long log stops nobody, including its author. This sets a non-zero exit status,
# which is the only signal a CI step and a shell `&&` both read.
# ═══════════════════════════════════════════════════════════════════════════════════════

_TREE_BASELINE: "dict[str, str] | None" = None


def _tree_state() -> "dict[str, str] | None":
    """Tracked-file status as {path: xy}, or None when git cannot answer.

    `--porcelain` over tracked files only: untracked scratch output is not a tree mutation, and
    including it would fire on every developer's stray file — a guard that cries wolf is the
    thing this is written against.
    """
    import subprocess  # noqa: PLC0415
    try:
        r = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            capture_output=True, text=True, timeout=30,
            cwd=str(Path(__file__).resolve().parents[1]),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    out = {}
    for line in r.stdout.splitlines():
        if len(line) > 3:
            out[line[3:].strip()] = line[:2]
    return out


def pytest_configure(config):  # noqa: D103
    global _TREE_BASELINE
    _TREE_BASELINE = _tree_state()


def pytest_sessionfinish(session, exitstatus):  # noqa: D103
    # NOT an error when git is unavailable — an environment fact, and refusing on it would be
    # the anesthesia failure in the other direction. It is reported, so a silent absence of the
    # check cannot be mistaken for the check passing.
    if _TREE_BASELINE is None:
        tr = session.config.pluginmanager.get_plugin("terminalreporter")
        if tr is not None:
            tr.write_line(
                "tree-mutation check SKIPPED: git could not be read. The suite was NOT shown to "
                "leave the tree unchanged.", yellow=True)
        return

    after = _tree_state()
    if after is None:
        return

    changed = sorted(p for p, xy in after.items() if _TREE_BASELINE.get(p) != xy)
    if not changed:
        return

    tr = session.config.pluginmanager.get_plugin("terminalreporter")
    if tr is not None:
        tr.write_line("")
        tr.write_line("THE SUITE MUTATED TRACKED FILES:", red=True, bold=True)
        for p in changed:
            tr.write_line(f"    {p}", red=True)
        tr.write_line(
            "A run that changes the tree measured a tree that was moving, and `git add -A` "
            "after a green stages the change into a commit whose message says otherwise. "
            "Restore these (`git checkout --`) or make the test that writes them use tmp_path.",
            red=True)
    session.exitstatus = 1 if exitstatus == 0 else exitstatus
