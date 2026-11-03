"""The directory's answer for the finance tests that are not about cells.

A declared measure's `policy.cells` is enforced (`_require_cell`): the engine asks the directory
which domains the caller holds. The existing finance tests were written before that gate and are
about something else (the figure, the render, the program check), so each of them runs with a
directory that says every caller holds the sample rows' cell, `PROGRAM_FINANCE`. That keeps each arm
testing what it tested. The arms that ARE about cells (`test_a_measure_row_cells_are_enforced.py`)
set their own double over this one, and a test that wants no answer at all can ask for the
`no_default_directory` fixture.

This patches the NAME the engine bound at import (`entitled_domains` in `finance_agent.main`), in
every module object the engine was imported as: tests import it both as `agent_fleet.finance_agent.main`
and as `finance_agent.main`, and an exception type or a function needs one module object to be one.
"""
from __future__ import annotations

import sys

import pytest

DEFAULT_DOMAINS = frozenset({"PROGRAM_FINANCE"})


def _engine_modules():
    return [m for n, m in list(sys.modules.items())
            if n.endswith("finance_agent.main") and hasattr(m, "entitled_domains")]


@pytest.fixture(autouse=True)
def _the_directory_says_every_caller_holds_the_sample_cell(request, monkeypatch):
    if "no_default_directory" in request.fixturenames:
        return
    for m in _engine_modules():
        monkeypatch.setattr(m, "entitled_domains", lambda user_id, **kw: DEFAULT_DOMAINS)


@pytest.fixture
def no_default_directory():
    """Ask for this and the autouse default above stands down."""
    return None
