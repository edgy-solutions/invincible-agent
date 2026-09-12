"""The seeded matrix IS MIL-STD-882E Table III, cell for cell.

WHY THIS SEAL EXISTS, AND IT IS NOT THE OBVIOUS REASON. Seal 4 already proves the drafted level
FOLLOWS THE FILE. It would pass just as green against a table that was confidently wrong — and on
2026-09-12 it did, because **five of the twenty seeded cells were wrong**. They had been written
from "the agent's reading of MIL-STD-882 convention", which is an honest label on a table nobody
had checked.

    seeded v1        standard (Table III)
    II/E  Low        Medium
    III/B Medium     Serious
    III/D Low        Medium
    III/E Low        Medium
    IV/B  Low        Medium

**EVERY ONE OF THE FIVE ERRED IN THE SAME DIRECTION — too permissive.** A remembered matrix does
not fail randomly; it drifts toward what sounds reasonable, and in this domain that direction
understates the risk and routes the acceptance to a MORE JUNIOR authority than the standard
requires. A wrong cell here is not a wrong label: it changes who is allowed to sign.

So this seal pins the transcription itself. Seal 4 asserts the mechanism reads the file; this
asserts the file says what the standard says. Neither implies the other, and only both together
make "follows MIL-STD-882E" a fact rather than a claim.

SOURCE: MIL-STD-882E, Table III "Risk assessment matrix", document page 12 (section 4.3.3),
transcribed from the standard's own PDF. 4.3.3.d permits a TAILORED matrix when formally approved
under DoD Component policy — tailoring belongs in an overlay, not here, which is why this seal
asserts the seed equals the standard exactly.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_fleet.safety_agent import matrix

from ._engine_extra import requires_rdflib

_MATRIX_TTL = Path(__file__).resolve().parents[2] / "setup" / "ontologies" / "safety_risk_matrix.ttl"

#: MIL-STD-882E Table III, verbatim. Row order is the standard's own (by probability).
#: Written out rather than computed: a rule that generated it would be a second reading of
#: the same convention, and the whole point is that this came from the document.
TABLE_III = {
    # probability: (Catastrophic I, Critical II, Marginal III, Negligible IV)
    "A": ("High", "High", "Serious", "Medium"),      # Frequent
    "B": ("High", "High", "Serious", "Medium"),      # Probable
    "C": ("High", "Serious", "Medium", "Low"),       # Occasional
    "D": ("Serious", "Medium", "Medium", "Low"),     # Remote
    "E": ("Medium", "Medium", "Medium", "Low"),      # Improbable
}
_SEVERITIES = ("I", "II", "III", "IV")


@pytest.fixture(autouse=True)
def _clean_cache():
    matrix.reset_cache()
    yield
    matrix.reset_cache()


@requires_rdflib
@pytest.mark.parametrize("probability", sorted(TABLE_III))
def test_each_probability_row_matches_the_standard(probability):
    """One test per row, so a failure names the row rather than the whole table."""
    expected_row = TABLE_III[probability]
    for severity, expected in zip(_SEVERITIES, expected_row):
        level, _audience, source = matrix.resolve_risk_level(severity, probability)
        assert level == expected, (
            f"{severity}/{probability}: seeded {level!r}, MIL-STD-882E Table III says "
            f"{expected!r} ({source}). A wrong cell changes WHO MAY ACCEPT, not just a label."
        )


@requires_rdflib
def test_no_cell_is_more_permissive_than_the_standard():
    """THE DIRECTIONAL CHECK, because the five real errors all leaned the same way.

    A table that is wrong in the conservative direction over-escalates and someone complains. A
    table that is wrong in the permissive direction routes a real acceptance to a junior authority
    and NOBODY COMPLAINS, because the queue works and the card renders. That asymmetry is why this
    assertion exists separately from the equality above: it is the failure with no symptom.
    """
    rank = {"High": 0, "Serious": 1, "Medium": 2, "Low": 3}
    too_soft = []
    for probability, row in TABLE_III.items():
        for severity, expected in zip(_SEVERITIES, row):
            level, _a, _s = matrix.resolve_risk_level(severity, probability)
            if level is not None and rank[level] > rank[expected]:
                too_soft.append(f"{severity}/{probability}: {level} < {expected}")
    assert not too_soft, (
        "seeded cells are MORE PERMISSIVE than MIL-STD-882E: " + "; ".join(too_soft)
    )


@requires_rdflib
def test_the_comparison_can_fail():
    """THE CONTROL. A table-equality test that never sees a mismatch has not been shown able to
    detect one — and every assertion above passing is equally consistent with `resolve_risk_level`
    returning whatever it was asked about."""
    rank = {"High": 0, "Serious": 1, "Medium": 2, "Low": 3}
    level, _a, _s = matrix.resolve_risk_level("I", "A")
    assert level == "High"
    assert rank[level] < rank["Low"], "the ordering used by the directional check is broken"
    absent, _a2, _s2 = matrix.resolve_risk_level("I", "F")
    assert absent is None, (
        "probability F (Eliminated) resolved to a risk level — it is a hazard STATE, not a risk "
        "band, and Table III's F row reads 'Eliminated' across every severity"
    )


@requires_rdflib
def test_probability_f_is_absent_and_that_is_deliberate():
    """F (Eliminated) is Table III's sixth row and is intentionally not a cell here.

    An eliminated hazard is not ASSESSED — it is `hazardStatus` `closed` in this vocabulary. The
    seal asserts the omission is TOTAL rather than partial: a stray F cell would mean somebody
    transcribed half of the row and left a risk band where a state belongs.
    """
    for severity in _SEVERITIES:
        level, _a, _s = matrix.resolve_risk_level(severity, "F")
        assert level is None, f"{severity}/F resolved to {level!r}; F is not a risk band"
    assert len(matrix.known_cells()) == 20, (
        "the matrix has cells beyond the 4x5 assessment grid"
    )


# ---------------------------------------------------------------------------
# THE ALWAYS-RUNS HALF — the coverage claim, read as TEXT.
#
# This is the assertion that must survive `rdflib` being legitimately absent. It does not prove
# the ENGINE resolves a cell correctly (that is the parsing half above, which skips); it proves
# the FILE declares MIL-STD-882E Table III's twenty cells with the standard's own values.
#
# Those are different claims and neither implies the other: a correct file can be read by a broken
# resolver, and a correct resolver can read a file that drifted. The second is the one that went
# wrong on 2026-09-12 — five cells, all too permissive — and it is the one asserted here, where no
# optional dependency can take it dark.
# ---------------------------------------------------------------------------

def test_the_TTL_TEXT_declares_table_iii_exactly():
    """Twenty cells, parsed from the file's own lines by regex. No rdflib, no graph."""
    text = _MATRIX_TTL.read_text(encoding="utf-8")
    rows = re.findall(
        r'safety:whenSeverity\s+"(\w+)"\s*;\s*safety:whenProbability\s+"(\w+)"\s*;\s*'
        r'safety:yieldsRiskLevel\s+safety:(\w+)\s*\.',
        text,
    )
    assert rows, "no matrix cells parsed from the TTL text — instrument failure, not an empty file"
    declared = {(sev, prob): level for sev, prob, level in rows}

    expected = {
        (sev, prob): TABLE_III[prob][i]
        for prob in TABLE_III
        for i, sev in enumerate(_SEVERITIES)
    }
    assert declared == expected, (
        "the TTL's declared cells differ from MIL-STD-882E Table III: "
        + "; ".join(
            f"{s}/{p}: file says {declared.get((s, p))!r}, standard says {v!r}"
            for (s, p), v in sorted(expected.items())
            if declared.get((s, p)) != v
        )
    )


def test_the_TEXT_reader_can_say_no():
    """THE CONTROL for the always-runs half. A regex that silently matches nothing looks exactly
    like one that matched everything it was asked about."""
    sample = (
        '[] a safety:MatrixCell ; safety:whenSeverity "I" ; '
        'safety:whenProbability "A" ; safety:yieldsRiskLevel safety:Low .'
    )
    rows = re.findall(
        r'safety:whenSeverity\s+"(\w+)"\s*;\s*safety:whenProbability\s+"(\w+)"\s*;\s*'
        r'safety:yieldsRiskLevel\s+safety:(\w+)\s*\.',
        sample,
    )
    assert rows == [("I", "A", "Low")], "the text reader cannot read a cell it was handed"
    assert rows[0][2] != TABLE_III["A"][0], (
        "the control's deliberately-wrong value matches the standard — it is not discriminating"
    )


def test_probability_F_is_absent_from_the_TEXT_too():
    """The deliberate omission, asserted where no dependency can hide it."""
    text = _MATRIX_TTL.read_text(encoding="utf-8")
    assert 'safety:whenProbability "F"' not in text, (
        "an F cell is declared; F (Eliminated) is a hazard STATE, not a risk band"
    )
    assert "Eliminated" in text, (
        "F's deliberate absence is not explained in the file — a considered omission and a "
        "transcription that stopped at E look identical without the note"
    )
