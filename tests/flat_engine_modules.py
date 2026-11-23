"""Keep an engine's flat sibling modules from outliving the test or module that imported them.

Several engines under `agent_fleet/` share bare module names (`seed`, `entities`, `measures`, ...).
Each engine module imports its siblings flat first and falls back to the package
(`try: import seed / except ImportError: from agent_fleet.cost_agent import seed`). In one
process, whichever engine's bare `seed` is in `sys.modules` first is bound by every engine imported
after it, so a test that stages one engine flat leaves a stranger's module for the next. This
plugin snapshots every flat name (derived from the top-level `*.py` stems of `agent_fleet/*/`)
around each collected module and each test, and puts back any entry that changed: absent stays
absent, a replaced entry returns to the old object. It is test-side only because production runs
each engine as its own flat process, where only one engine's modules exist.
"""

from __future__ import annotations

import contextlib
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]

FLAT_NAMES = frozenset(
    p.stem
    for p in (_ROOT / "agent_fleet").glob("*/*.py")
    if p.stem != "__init__" and "." not in p.stem
)

_ABSENT = object()


@contextlib.contextmanager
def _guard():
    before = {n: sys.modules.get(n, _ABSENT) for n in FLAT_NAMES}
    try:
        yield
    finally:
        for n, old in before.items():
            if sys.modules.get(n, _ABSENT) is old:
                continue
            if old is _ABSENT:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = old


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    with _guard():
        yield


@pytest.hookimpl(hookwrapper=True)
def pytest_make_collect_report(collector):
    with _guard():
        yield
