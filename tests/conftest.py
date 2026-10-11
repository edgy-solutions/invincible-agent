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

import contextlib
import importlib.machinery
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


# ═══════════════════════════════════════════════════════════════════════════════════════
# A DOUBLE IS INSTALLED, NOT NEGOTIATED -- AND IT DOES NOT OUTLIVE ITS MODULE
#
# `sys.modules` is process-global, so a test file that replaces an entry is editing every
# file that runs after it. TWO failures come out of that and they are NOT the same failure:
#
#   LEAKING    a double left behind makes a LATER file fail in its own name. Measured
#              2026-09-04: `tests/routing` and `tests/planning` each passed alone and failed
#              together, eleven tests deep, in a suite that mentions neither stubbing nor
#              baml -- five files installed a bare-ModuleType `baml_client` with no
#              `__path__`, none removed it, and the next `baml_client.types` import said
#              "is not a package".
#   DEFERRING  a double installed only `if name not in sys.modules` installs NOTHING when
#              anything got there first -- another file's stub OR a perfectly legitimate
#              real import -- and the file's own assertions then run against an object it
#              did not build.
#
# THE SECOND KIND IS WHAT THIS REVISION ADDS, and finding it corrected the diagnosis the
# work was dispatched under. Measured 2026-09-27 on master: the two order-dependent reds
# are `test_adr0019_engine_o_contract_a.py`'s pair, 2/2 green when the file runs alone and
# 2/2 red in the suite, failing with `'TypeBuilder' object has no attribute 'values'` --
# its own recorder reading an object that is not its own double. No unrestored stub is
# involved. `test_an_out_of_domain_hit_is_a_candidate_not_an_authority` loads engine-o's
# `main.py` at MODULE level, which imports the REAL, file-backed
# `baml_client.type_builder` during collection; adr0019 then offers its recorder under
# `if "baml_client.type_builder" not in sys.modules:` and so installs nothing at all.
#
# SO THE RULE, which the adr0019 file had already half-written for `weaviate` ("always
# overwrite ... other test modules install MagicMocks that confuse the imports") without
# generalising it:
#
#   a double the test ASSERTS ON is installed unconditionally  -- it is a recorder, and
#       yielding to whatever ran first makes the assertion measure a stranger
#   a double that only satisfies an IMPORT may defer            -- it is an absence shim,
#       and the real module is strictly better than a fake of it
#
# The deferring population is 12 files: 6 by `sys.modules.setdefault`, 7 by an `if`-guard,
# one using both. `tests/test_the_stub_harness_puts_sys_modules_back.py` ratchets that set
# so a new bet on collection order is a decision somebody makes in the open.
#
# THAT FIGURE IS 12 AND NOT THE 14 I FIRST WROTE OR THE 10 THE RE-MEASURE GAVE, AND BOTH
# ERRORS WERE THE MATCHER'S: the first double-counted the file that defers in two
# spellings, and the second used `[^\n]` inside a grep bracket -- which is the complement
# of `{\, n}`, so it silently dropped every guard whose subject contains the letter n. A
# matcher that shrinks the population it exists to measure reads exactly like a population
# that shrank, which is why the ratchet carries a positive control.

_ABSENT = object()


def _is_a_test_built_double(obj: object) -> bool:
    """Is this `sys.modules` entry a test's double rather than a real importable module?

    DERIVED, NOT LISTED. This used to be `_STUBBED_GLOBALS = ("baml_client", "dagster")`,
    and a list you have to append to is retired by the first file that stubs a third name
    -- with no red, because the restore simply stops covering it.

    THE PROPERTY IS IMPORT PROVENANCE, and specifically a genuine `ModuleSpec`: the object
    the import system builds when it actually located something, which nothing in a test
    fabricates. `types.ModuleType("x")` has `__spec__ = None`; a `MagicMock` answers
    `__spec__` with another mock; every real module -- file-backed, frozen, built-in or a
    namespace package -- carries the real thing.

    IT MATTERS THAT REAL IMPORTS ARE LEFT ALONE, and this is the direction that would be
    worse than the defect being fixed. Popping a real module so a later file re-imports it
    makes two module objects of one name, and then an `except SomeError` raised through one
    of them cannot catch the other's class -- trading a stub leak for an identity defect.

    ⛔ AND THE FIRST FORM OF THIS PREDICATE HAD EXACTLY THAT FALSE POSITIVE. It read
    `not isinstance(obj, types.ModuleType) -> double`, with `__file__ is None and __spec__
    is None` as the fallback, and it was right about every example I thought of. The census
    arm in `test_the_stub_harness_puts_sys_modules_back.py` ran it over the whole live
    `sys.modules` against `find_spec` and found `zipp.compat.overlay.zipfile`: a
    `HashableNamespace`, NOT a `ModuleType`, carrying the real stdlib `zipfile`'s spec and
    file. A hand-picked sample could not have found that, and the shape it broke on --
    a real module served by a class that is not `ModuleType` -- is the shape a proxy or
    overlay library uses deliberately.
    """
    return not isinstance(getattr(obj, "__spec__", None), importlib.machinery.ModuleSpec)


@contextlib.contextmanager
def stub_modules(doubles: dict[str, object]):
    """Install `doubles` in `sys.modules` UNCONDITIONALLY, and put the previous state back.

    Unconditional is the point: see the header. Restoring absence is equally the point --
    an entry that was not there before must not be there after, and `dict.update` on the
    way in has no inverse on the way out unless absence is recorded as a state.

    AND THE PARENT'S ATTRIBUTE IS PART OF THE INSTALL, because a `sys.modules` entry is
    only as good as the import form the subject was written in. MEASURED 2026-09-27 against
    a real package whose submodule was already imported, then overridden in `sys.modules`
    alone:

        from pkg.sub import name   -> the double      (resolves through sys.modules)
        import pkg.sub as s        -> THE REAL ONE    (resolves getattr(pkg, "sub"))
        from pkg import sub        -> THE REAL ONE    (same)

    Engine-o spells its import the first way, which is why the adr0019 repair needed
    nothing more. But two of the three forms ignore a `sys.modules`-only double entirely,
    and a caller cannot be asked to know which form the code under test happens to use --
    so the parent attribute is set here and its previous value, or its ABSENCE, is restored
    with everything else. This is the generalisation of the `wv.classes = wvc` line the
    adr0019 file already carried without saying what it was for.
    """
    saved = {k: sys.modules.get(k, _ABSENT) for k in doubles}
    saved_attrs: list[tuple[object, str, object]] = []
    for key, double in doubles.items():
        parent_name, _, child = key.rpartition(".")
        parent = sys.modules.get(parent_name) if parent_name else None
        if parent is not None:
            saved_attrs.append((parent, child, getattr(parent, child, _ABSENT)))
            setattr(parent, child, double)
    sys.modules.update(doubles)
    try:
        yield doubles
    finally:
        for parent, child, old in reversed(saved_attrs):
            if old is _ABSENT:
                with contextlib.suppress(AttributeError):
                    delattr(parent, child)
            else:
                setattr(parent, child, old)
        for key, old in saved.items():
            if old is _ABSENT:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = old


def snapshot_modules() -> dict[str, object]:
    """The state the autouse teardown compares against. A plain function so a seal can take
    the same snapshot the suite takes, rather than a copy of the idea of one."""
    return dict(sys.modules)


def restore_doubles_installed_since(saved: dict[str, object]) -> list[str]:
    """Undo every DOUBLE that appeared or replaced an entry since `saved`. Returns the keys
    touched, so a caller can assert on what happened rather than on what was intended.

    A MODULE-LEVEL FUNCTION AND NOT A FIXTURE BODY, for the reason measured twice this
    month: a rule that lives inside a fixture can only be MIRRORED by a test, and a mirror
    is not a seal -- `cold_start_fallback_domains` in the ontology service records a mutant
    that survived for exactly that reason. The fixture below is three lines and calls this.
    """
    touched: list[str] = []
    for key, obj in list(sys.modules.items()):
        if saved.get(key) is obj:
            continue
        if not _is_a_test_built_double(obj):
            continue
        if key in saved:
            sys.modules[key] = saved[key]
        else:
            sys.modules.pop(key, None)
        touched.append(key)
    return touched


@pytest.fixture(scope="module", autouse=True)
def _no_module_leaves_a_double_behind():
    """PUT sys.modules BACK after any module that installed a double of its own.

    AND THE FIRST REPAIR OF THE 2026-09-04 LEAK FIXED ONE FILE OF FIVE. I added a teardown
    to the file I had open, verified the pair that had failed, and described it as closing
    the pollution -- the remembered-population defect inside the fix for a
    remembered-population defect. That is why the cleanup is here and not in each file.
    Those files duplicate their doubles on purpose and that is fine; what must not be
    per-file is the putting back, because a new file that stubs and forgets reintroduces
    the whole class. For a module that stubs nothing this is a no-op by construction.

    THE WHOLE SUBTREE IS RESTORED, not just the top name. Restoring only `baml_client`
    leaves `sys.modules["baml_client.types"]` behind while the parent object that should
    carry `types` as an ATTRIBUTE has been swapped, so `baml_client.types.AgentStatus`
    resolves the submodule and then fails on the attribute. Measured then: restoring the
    parent alone traded eleven failures for seventeen. Comparing every key by OBJECT
    IDENTITY does that by construction rather than by remembering to.

    WHAT THIS CANNOT SEE, stated rather than implied:

      * THE SNAPSHOT IS POST-COLLECTION. It is taken when the module's first test sets up,
        so a double installed at IMPORT time is inside the snapshot and survives. Measured:
        exactly 1 of the 39 files that assign to `sys.modules` acts at module level, and it
        registers a loaded `main.py` under a unique name rather than stubbing a shared
        dependency -- so bracketing collection would be machinery for a case that does not
        exist yet. A file that stubs a shared dependency at import time is not covered here
        and must use `stub_modules` around its own import.
      * IT CANNOT UNDO A PARENT ATTRIBUTE. `sys.modules` is all this fixture sees, so a
        file that does its own stubbing AND repoints `pkg.sub` on a real `pkg` (as the
        adr0019 file does with `wv.classes`) leaves that attribute behind. There is no
        snapshot of module attributes to diff against, and taking one would mean walking
        every loaded module on every test. `stub_modules` restores it because it knows what
        it set; hand-rolled stubbing does not, which is the reason to prefer `stub_modules`.
    """
    saved = snapshot_modules()
    yield
    restore_doubles_installed_since(saved)


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


def _content_differs(path: str) -> bool:
    """True only when the file's BYTES differ from HEAD — not merely its status flag."""
    import subprocess  # noqa: PLC0415
    try:
        r = subprocess.run(
            ["git", "diff", "HEAD", "--quiet", "--", path],
            capture_output=True, timeout=30,
            cwd=str(Path(__file__).resolve().parents[1]),
        )
    except (OSError, subprocess.SubprocessError):
        return True          # cannot tell -> report it; a silent skip is the worse failure
    return r.returncode != 0


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

    candidates = sorted(p for p, xy in after.items() if _TREE_BASELINE.get(p) != xy)
    # CONFIRM BY CONTENT BEFORE FAILING A RUN. `git status --porcelain` reports FLAGS, and on
    # Windows a tracked file goes transiently "modified" while CRLF normalisation is pending —
    # git says so on every commit here ("CRLF will be replaced by LF the next time Git touches
    # it"). That fired on 2026-09-18 against a file byte-identical to HEAD and turned a 4011-pass
    # run into exit 1, which is precisely the crying-wolf failure this guard was written against.
    #
    # `git diff HEAD --` compares CONTENT, so a stat-dirty entry with identical bytes reports
    # nothing. One subprocess per candidate, and candidates are normally zero.
    changed = [p for p in candidates if _content_differs(p)]
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


def _duckdb_skips(stats):
    """The distinct (file, reason) of every skip whose reason names duckdb, sorted.

    Pure, so the seal can feed it a fake stats dict. A skip's `longrepr` is a tuple
    `(path, lineno, "Skipped: <reason>")`; anything else is not a skip we can read, and is left out.
    """
    seen = set()
    for rep in stats.get("skipped", []):
        lr = getattr(rep, "longrepr", None)
        if isinstance(lr, tuple) and len(lr) == 3 and "duckdb" in str(lr[2]):
            seen.add((str(lr[0]), str(lr[2])))
    return sorted(seen)


def pytest_terminal_summary(terminalreporter, exitstatus, config):  # noqa: D103
    # A skipped duckdb arm is not a green: the package page carries the .duckdb file's sha256 and
    # these arms are what verify it. Name them in the summary so a venv without duckdb cannot
    # pass for one with it. Prints nothing when none skipped; never changes pass/fail.
    skips = _duckdb_skips(terminalreporter.stats)
    if not skips:
        return
    terminalreporter.section("duckdb-gated skips", sep="-", yellow=True)
    terminalreporter.write_line(f"duckdb-gated skips: {len(skips)}", yellow=True)
    for path, reason in skips:
        terminalreporter.write_line(f"    {path}: {reason}", yellow=True)
