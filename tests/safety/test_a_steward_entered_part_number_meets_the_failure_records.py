"""A part number a steward ENTERS must meet the failure records the way an EXTRACTED one does.

THE GAP (measured on master 7a45a3cb, 2026-10-25). `steward_correction.validate_row_edits` takes
an added `mpn` / a `corrected_mpn` as any non-empty string, and compares every identity with
`.lower()`. Engine S (`measures.what_failed_on_this_part`) looks a part up by EXACT spelling
(`failure_source` fixture: `getattr(r, by) == value`; a real connector decides for itself) and
refuses what `_PART_NUMBER_SHAPE` does not match. The graph keeps the steward's spelling
(`promotion_stores._WRITE_EDGE_CYPHER` MERGEs `Component {mpn: $mpn}` verbatim) and the router hands
that spelling to Engine S. So `pn-8801` typed for recorded `PN-8801` is accepted at promotion,
and the safety lookup then answers `no_failures_recorded` for a part with failures: a confident
false negative on the safety-critical read, with no refusal anywhere on the path.

WHO OWNS THE FIX is not saf's: the spelling rule (refuse, or canonicalise to a spelling a
registry holds) lives on the steward side (restate_analyst, Lane 1) or in the connector's matching.
The two xfail arms are the red-by-assertion carriers; run `--runxfail` to see them red. Strict, so
a fix on either side turns them into a failure that says "remove the xfail".

The CONTROLS share the gate and the population: the recorded spelling meets its records, and the
same steward gate accepts the variant (so the arm is red because of the lookup, not the gate).
"""
from __future__ import annotations

import pytest

from agent_fleet.restate_analyst import steward_correction as sc
from agent_fleet.safety_agent import measures

from . import _program_filter as pf

RECORDED = "PN-8801"
#: Spellings of the SAME recorded part that the steward gate treats as it treats any identity.
CASE_VARIANTS = ["pn-8801", "Pn-8801"]
#: Spellings Engine S's own shape check refuses (so it answers unknown_part for them).
SHAPE_REFUSED = ["PN 8801", "-PN-8801", "PN-8801,"]


def _ask(monkeypatch, pn):
    pf.install(monkeypatch, caller=pf.ALICE, members=pf.ALL_PROGRAMS)
    return measures.what_failed_on_this_part(part_number=pn)


def _steward_takes(op, mpn) -> bool:
    row = {"mpn": mpn, "disposition": "affected", "reason": "r", "evidence": "e"}
    if op == "corrected":
        raw = {"corrected": [{"mpn": "EXTRACTED-1", "corrected_mpn": mpn, "evidence": "e"}]}
        extracted = ["EXTRACTED-1"]
    else:
        raw, extracted = {"added": [row]}, ["EXTRACTED-1"]
    try:
        sc.validate_row_edits(raw, extracted_mpns=extracted)
    except sc.EditRefusal:
        return False
    return True


def test_CONTROL_the_recorded_spelling_meets_its_records(monkeypatch):
    out = _ask(monkeypatch, RECORDED)
    assert out["refused"] is False and out["failure_count"] > 0


@pytest.mark.parametrize("op", ["added", "corrected"])
@pytest.mark.parametrize("mpn", CASE_VARIANTS + SHAPE_REFUSED)
def test_CONTROL_the_steward_gate_takes_every_variant(op, mpn):
    """Today's gate, pinned: the variants are accepted. If this goes red the gap moved to the
    steward side and the xfail arms below should be re-read, not just flipped."""
    assert _steward_takes(op, mpn)


@pytest.mark.parametrize("mpn", CASE_VARIANTS)
def test_CONTROL_engine_s_looks_a_part_up_by_exact_spelling(monkeypatch, mpn):
    out = _ask(monkeypatch, mpn)
    assert out["refused"] is True and out["outcome"] == "no_failures_recorded"


@pytest.mark.parametrize("mpn", SHAPE_REFUSED)
def test_CONTROL_engine_s_refuses_what_its_shape_does_not_match(monkeypatch, mpn):
    assert not measures._PART_NUMBER_SHAPE.fullmatch(mpn)
    assert _ask(monkeypatch, mpn)["outcome"] == "unknown_part"


@pytest.mark.xfail(strict=True, reason="GAP a1: steward gate accepts a spelling Engine S answers "
                   "'no_failures_recorded' for -- a false negative on the safety read")
@pytest.mark.parametrize("op", ["added", "corrected"])
@pytest.mark.parametrize("mpn", CASE_VARIANTS)
def test_a_steward_entered_case_variant_meets_the_same_records_or_is_refused(monkeypatch, op, mpn):
    if not _steward_takes(op, mpn):
        return          # refused at promotion: the safe outcome
    want = _ask(monkeypatch, RECORDED)["failure_count"]
    got = _ask(monkeypatch, mpn)
    assert got.get("failure_count") == want, (
        f"{op} {mpn!r} was accepted at promotion; the failure lookup answered {got.get('outcome')!r}")


@pytest.mark.xfail(strict=True, reason="GAP a1b: steward gate accepts a part number Engine S "
                   "cannot look up at all (unknown_part)")
@pytest.mark.parametrize("op", ["added", "corrected"])
@pytest.mark.parametrize("mpn", SHAPE_REFUSED)
def test_a_steward_entered_malformed_part_number_is_refused_at_promotion(op, mpn):
    assert not _steward_takes(op, mpn)
