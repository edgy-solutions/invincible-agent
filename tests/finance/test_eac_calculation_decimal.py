"""ADR-0053 §7 step 2 for `fin_eac_calculation` — vac and etc are the subtractions.

Step 1 (`e3f726b`) extracted the formulas. This changes the arithmetic, alone.

── WHAT MOVED, EACH NAMED ───────────────────────────────────────────────────────────────────
Six values, all cent-quantization of repeating decimals, none a correctness change:

    CPI.eac       14152380.952380951  -> 14152380.95
    CPI.vac      -2152380.9523809515  -> -2152380.95
    CPI.etc       6722380.9523809515  ->  6722380.95
    CPI_SPI.eac   14792607.709750567  -> 14792607.71
    CPI_SPI.vac  -2792607.7097505666  -> -2792607.71
    CPI_SPI.etc   7362607.709750567   ->  7362607.71

**`CPI_SPI` is the figure ADR-0053 §6 is written about.** Its correction records that quantizing
absorbs the float/Decimal difference — both paths land on the same cent — which is why the
Decimal seal asserts the DERIVATION rather than the value. These rows are that fact, arriving in
a second verb.

── THE MODULE NEEDED NO CHANGE ──────────────────────────────────────────────────────────────
`eac_formulas` is type-agnostic: `+`, `-`, `*`, `/` over whatever it is handed. Its version is
unmoved, because §1 ties a version bump to the FIGURES changing by the module's doing, and these
moved because the verb changed the inputs' type.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from agent_fleet.finance_agent import measures as m
from agent_fleet.finance_agent.seed import build_seed

STATE = build_seed()
PROGRAM = "NP-MERIDIAN"
METHODS = ("REMAINING_AT_BUDGET", "CPI", "CPI_SPI")


def _row(method):
    return m.fin_eac_calculation(STATE, program_id=PROGRAM, method=method)[0]


@pytest.mark.parametrize("method", METHODS)
def test_every_money_field_carries_an_exact_string_that_agrees(method):
    row = _row(method)
    for key in m._EAC_MONEY_FIELDS:
        assert f"{key}_exact" in row, f"{method}.{key} has no exact column"
        assert Decimal(row[f"{key}_exact"]) == Decimal(str(row[key]))


@pytest.mark.parametrize("method", METHODS)
def test_the_two_SUBTRACTIONS_are_exact_over_the_exact_operands(method):
    """THE REASON THIS VERB IS IN SCOPE — recomputed from the row's own exact columns."""
    row = _row(method)
    bac, eac, acwp = (Decimal(row["bac_exact"]), Decimal(row["eac_exact"]),
                      Decimal(row["acwp_exact"]))
    assert Decimal(row["vac_exact"]) == m._money(bac - eac)
    assert Decimal(row["etc_exact"]) == m._money(eac - acwp)


@pytest.mark.parametrize("method", METHODS)
def test_the_ratios_are_NOT_quantized_and_the_float_is_their_faithful_float(method):
    """`cpi`, `spi` and `percent_complete` are factors, not amounts. Rounding
    percent_complete to the cent would put a currency on a proportion."""
    row = _row(method)
    for key in ("cpi", "spi", "percent_complete"):
        if row.get(key) is None:
            continue
        assert float(Decimal(row[f"{key}_exact"])) == row[key]


def test_the_forecast_is_computed_from_the_UNQUANTIZED_index():
    """QUANTIZE AFTER, NEVER BEFORE, A DERIVATION (§6a).

    `EAC = BAC / CPI` divides by the full-precision index; `_emit_money` rounds afterwards.
    Dividing by a cent-rounded CPI would fold a presentation decision into a forecast — and on
    a figure near 10^7 that is thousands of dollars.
    """
    row = _row("CPI")
    exact_cpi = Decimal(row["cpi_exact"])
    assert Decimal(row["eac_exact"]) == m._money(Decimal(row["bac_exact"]) / exact_cpi)

    rounded_cpi = exact_cpi.quantize(Decimal("0.01"))
    assert rounded_cpi != exact_cpi, "cpi lands on a cent; this seal cannot discriminate"
    assert m._money(Decimal(row["bac_exact"]) / rounded_cpi) != Decimal(row["eac_exact"])


def test_the_module_version_is_UNMOVED_by_a_caller_side_type_change():
    """§1 ties a version bump to the figures changing by the MODULE's doing. These moved
    because the verb changed the inputs' type, and the module is type-agnostic."""
    from agent_fleet.finance_agent.measure_modules import eac_formulas

    assert eac_formulas.VERSION == "1.0.0"
