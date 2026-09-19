"""`unsummarised` retired: every finance verb now leads with a figure, not with a pointer.

The brief's `_headline` reads `headline` / `summary` / `value` / `verdict` from a payload and
falls back to **`"reported (see artifact)"`** — a sentence that tells a reader the figure exists
and not what it is.

── THE CENSUS, WHICH WAS FIVE AND NOT TWO ───────────────────────────────────────────────────
Two verbs were reported as falling back. Measured against every verb the engine declares:

    fin_variance_analysis      FELL BACK   (reported)
    fin_funding_status         FELL BACK   (reported)
    fin_eac_calculation        FELL BACK   (not reported)
    fin_eac_comparison         FELL BACK   (not reported)
    fin_variance_drivers       FELL BACK   (not reported)

**The brief renders all of them**, so fixing the two named would have left it still saying
"reported (see artifact)" three times. A filed defect is a sample.

── THE SCOPE RULE THESE LIVE UNDER ──────────────────────────────────────────────────────────
A verdict is a **MECHANICAL restatement of the data against a declared reference** — arithmetic
a reader could redo from the chart. It says nothing about whether the figure is ACCEPTABLE,
which is a programmatic judgement this engine has no standing to make and no inputs for.

"CPI below 1.0" is a restatement. "CPI is concerning" is not.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent_fleet.finance_agent import measures as m
from agent_fleet.finance_agent.main import app
from agent_fleet.finance_agent.seed import build_seed

STATE = build_seed()
PARAMS = {"program_id": "NP-MERIDIAN"}
EXTRA = {"fin_eac_calculation": {"method": "CPI"}}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _payload(client, fn):
    return client.post(f"/measure/{fn}",
                       json={"params": {**PARAMS, **EXTRA.get(fn, {})}}).json()


@pytest.mark.parametrize("fn", sorted(m.OUTPUT_URI))
def test_EVERY_verb_leads_with_a_figure_and_not_with_a_pointer(client, fn):
    """DERIVED FROM `OUTPUT_URI`, so a tenth verb is covered by the commit that adds it.

    Listing the verbs here would reproduce the defect this seal exists to close — two were
    reported and five were falling back.
    """
    from agent_fleet.graph_host.graphs.fin_program_brief import _headline

    headline = _headline(_payload(client, fn))
    assert headline != "reported (see artifact)", (
        f"{fn} leads the brief with a pointer; add a VERDICT entry"
    )
    assert headline.strip(), f"{fn} produced an empty headline, which renders as a blank line"


@pytest.mark.parametrize("fn", sorted(m.VERDICT))
def test_a_verdict_is_ABSENT_when_there_is_nothing_to_say(fn):
    """Silence is the honest state. A card with no caption reads correctly; one saying
    "0 lines short" has spent a line to say nothing.

    Checked by handing each verdict an EMPTY row set — the one input every one of them must
    survive, and the one a live call never produces.
    """
    assert m.VERDICT[fn]([]) is None, f"{fn} invented a verdict from no rows"


@pytest.mark.parametrize("fn", sorted(m.VERDICT))
def test_no_verdict_makes_a_JUDGEMENT_about_acceptability(fn):
    """THE SCOPE RULE, checked as far as a string check honestly can.

    ⚠ WHAT THIS CANNOT DO: tell a restatement from a judgement in general. It matches a word
    list, and a judgement phrased without those words passes. It is a floor — the cheap half of
    a rule whose real enforcement is review — and it is written down as such rather than left
    to imply more coverage than it has.
    """
    verdict = m.VERDICT[fn](_rows_for(fn))
    if verdict is None:
        return
    banned = ("concerning", "acceptable", "unacceptable", "poor", "good", "bad",
              "healthy", "unhealthy", "risk", "alarming", "should", "must")
    hit = [w for w in banned if w in verdict.lower()]
    assert not hit, (
        f"{fn} verdict {verdict!r} contains {hit}, which reads as a judgement about whether "
        f"the figure is acceptable — a call the finance group makes, not this engine"
    )


def _rows_for(fn):
    if fn == "fin_eac_calculation":
        return m.fin_eac_calculation(STATE, program_id="NP-MERIDIAN", method="CPI")
    return getattr(m, fn)(STATE, program_id="NP-MERIDIAN")


def test_the_spread_verdict_reads_the_EXACT_column_and_not_the_float_edge():
    """THE SPREAD IS THE FINDING (R-001), and it is the subtraction the money ruling names.

    Reading `eac` here would make the exact column decorative — carried, then unused by the one
    calculation that needed it. Asserted by recomputing from the exact columns.
    """
    from decimal import Decimal

    rows = m.fin_eac_comparison(STATE, program_id="NP-MERIDIAN")
    exact = [Decimal(r["eac_exact"]) for r in rows if r.get("eac_exact") is not None]
    assert len(exact) >= 2, "fewer than two methods answered; the spread cannot discriminate"
    assert f"{float(max(exact) - min(exact)):,.0f}" in m._verdict_eac_spread(rows)


def test_the_spread_verdict_is_ABSENT_when_only_ONE_method_answered():
    """A spread over one figure is zero BY CONSTRUCTION and reads as agreement between methods
    rather than as the absence of a comparison — the two states a reader must not confuse."""
    one = [{"eac_exact": "100.00", "value_unit": "USD"}]
    assert m._verdict_eac_spread(one) is None


def test_the_drivers_verdict_reads_the_RANKING_rather_than_re_sorting():
    """The rows arrive ranked. A second ordering here could disagree with the one the card
    draws, and a caption naming a different row than the chart's first is worse than none."""
    rows = m.fin_variance_drivers(STATE, program_id="NP-MERIDIAN")
    assert rows[0].get("rank") == 1
    assert str(rows[0]["entity_name"]) in m.VERDICT["fin_variance_drivers"](rows)
