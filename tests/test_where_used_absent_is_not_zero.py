"""Where-used: a value with no source is absent, never 0 (ADR-0065 s4, "absent is not zero").

Run: uv run pytest tests/test_where_used_absent_is_not_zero.py -q
"""
from __future__ import annotations

from tests.test_where_used_rolls_up_through_every_level import ALICE, ask, ident


def _ok():
    got = ask(ident("P"), ALICE)
    assert got["status"] == "ok"
    return got


def test_POPULATION_AND_STOCK_ARE_NONE_ON_EVERY_ROW_NEVER_ZERO():
    for r in _ok()["where_used"]:
        assert r["population"] is None and r["stock"] is None


def test_THE_TABLE_CELL_IS_NULL_PRESENT_NEVER_ZERO_EMPTY_OR_A_PLACEHOLDER():
    """The key is present and its value is None (`null` on the wire): cortex reads that as absent.
    A served number is drawn as a number, so qty_per is one."""
    got = _ok()
    for r in got["rows"]:
        for key in ("population", "stock"):
            assert key in r and r[key] is None, (key, r.get(key))
        assert isinstance(r["qty_per"], (int, float)) and r["qty_per"] > 0
    assert all("no source" in line for line in got["message"].splitlines())


def test_THE_PROVENANCE_NAMES_BOTH_ABSENCES_AND_EVERY_NONE_INPUT():
    for r in _ok()["where_used"]:
        absent = r["data_provenance"]["absent"]
        assert absent["population"] and absent["stock"]
        for inp in r["data_provenance"]["inputs"]:
            for k in ("dataset_urn", "ticket_id", "classification"):
                if inp[k] is None:
                    assert f"{inp['name']}.{k}" in absent, (inp["name"], k)
            assert inp["ticket_id"] is None
            assert inp["locator"].endswith("where_used.yaml")
        assert r["as_of"] == "2026-11-07"
