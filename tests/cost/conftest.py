"""Shared fixtures for tests/cost.

`isolated_dist` is the one fixture every test that builds or reads a cost export artifact
must use. Before it existed, `package_export` — and every seal built on it — wrote straight
into ROOT/dist, the real repository's artifact directory, so a full-suite run left megabyte
HTML/duckdb packages sitting in a SHARED checkout with no cleanup, long after the run that
produced them ended (measured: alpha and beta builds, mtimes 2026-09-30 00:51:12-15, still
there days later). `measures._dist_dir(root)` is the one place the artifact directory is
named, in production and in tests alike, so patching that one function redirects every writer
and every reader at once.
"""
from __future__ import annotations

import pytest

from agent_fleet.cost_agent import measures


@pytest.fixture(scope="module")
def isolated_dist(tmp_path_factory):
    """Redirect `measures._dist_dir` at a throwaway directory for the whole test module.

    MODULE-SCOPED, because the fixtures that build an export once and reuse it across a
    module's tests (`exported`, `emitted`, `slice2`) are themselves module-scoped, and some
    seals depend on more than one recipient's package sitting in the SAME directory (one
    recipient's reader being refused another's package) — exactly as they do in the real
    `dist/`. A function-scoped redirection under a module-scoped builder would rebuild, or
    disagree with itself, every test.

    `monkeypatch` is function-scoped and cannot be requested by a module-scoped fixture, so
    this drives `pytest.MonkeyPatch` directly via `tmp_path_factory` and restores by hand on
    teardown.
    """
    target = tmp_path_factory.mktemp("dist")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(measures, "_dist_dir", lambda root: target)
        yield target
