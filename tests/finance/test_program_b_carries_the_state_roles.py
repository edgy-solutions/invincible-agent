"""Program B's contract passes engine-fin's contract check and its frame is a state the engine reads.

B carries `program_name` and `program_bac`, required and determined by `program_id`, as
`contracts/ev_fixture.yaml` does, so no test needs to monkeypatch `asset_inputs.dataset_contract`
for B. Two assertions: the contract check is clean, and the consumer (`state_from_rows`) reads
`b_frame()` without raising.

The consumer case declares B's calendar as the only one in force. The state read holds periods to
the calendar in force (`entities.fiscal_periods()`), not to the contract's `period.calendar`; with
two calendars declared none is in force and every state read refuses. That is reported, not fixed
here.

Run: uv run --no-sync pytest -c pyproject.toml --rootdir=. -p no:cacheprovider -p no:langsmith_plugin tests/finance/test_program_b_carries_the_state_roles.py
"""
from __future__ import annotations

import pytest

pytest.importorskip("polars")

from agent_fleet.finance_agent import asset_inputs, entities, fiscal_calendar  # noqa: E402
from agent_fleet.utils import dataset_contracts  # noqa: E402
from tests.finance.test_a_calendar_lookup_lists_the_periods_in_order import B_DIR  # noqa: E402
from tests.finance.test_a_flow_row_draws_to_its_declared_depth import b_frame  # noqa: E402


def _contract():
    return dataset_contracts.load_contract("program_b", B_DIR / "contracts")


def test_program_b_passes_the_engines_contract_check():
    assert asset_inputs.contract_problems(_contract()) == []


@pytest.fixture
def b_calendar(monkeypatch):
    monkeypatch.setenv("FIN_CALENDAR_OVERLAY_DIRS", str(B_DIR / "fin_calendar"))
    fiscal_calendar._cache.clear()
    try:
        yield
    finally:
        fiscal_calendar._cache.clear()


def test_the_state_read_takes_program_bs_frame(b_calendar):
    assert entities.fiscal_periods() == tuple(fiscal_calendar.calendar_for("program_b_445").labels)
    state = asset_inputs.state_from_rows(b_frame(), "PRG-B", _contract())
    assert state is not None
