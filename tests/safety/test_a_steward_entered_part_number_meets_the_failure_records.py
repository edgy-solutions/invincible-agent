"""A part number a steward ENTERS must meet the failure records the way an EXTRACTED one does.

THE GAP (measured on master 7a45a3cb, 2026-10-25). `steward_correction.validate_row_edits` takes a
`corrected_mpn` as any non-empty string. The graph keeps the steward's spelling, the router hands
that spelling to Engine S, and Engine S looks a part up by EXACT spelling, so `pn-8801` typed for
recorded `PN-8801` is accepted at promotion and the safety lookup answers `no_failures_recorded`
for a part with failures: a confident false negative with no refusal anywhere on the path.

THE RULING (architect, 2026-10-25, a1): promotion refuses a steward value that does not exactly
equal a recorded part AFTER the connector's own normalisation. A value that matches nothing must
come in as an explicit `added` edit, never as a silent correction. The spelling rule is doc-tools';
enforcing it at promotion is Lane 1's. Three cases:
  (i)   `pn-8801` and its separator variants match after normalisation: accepted, and the value
        that is WRITTEN is the recorded spelling `PN-8801`, so Engine S resolves its 2 failures.
  (ii)  a value matching no recorded part, arriving as a CORRECTION: refused.
  (iii) that same value arriving as an explicit `added` edit: accepted (pinned green; it is the
        ruling's way in, and must survive Lane 1's build).

THE NORMALISATION IS READ, NEVER RESTATED: loaded by file path from the sibling doc-tools checkout
(`doc_tools/utils/text_layer_health.py::_mpn_key`, the only part-number normaliser in doc-tools; it
is stdlib-only). `doc_tools` is not importable in this venv, hence the path. The tests skip when the
sibling is absent. WHICH normaliser the ruling means is Q1 in the packet to Lane 1.

THE SEAM is Lane 1's: the carriers drive the gate Lane 1 owns (`validate_row_edits` +
`edit_log`) and assert only the OUTCOME. They are strict xfail (red by assertion under
`--runxfail`); a build that meets the ruling turns them into XPASS-failures that say "remove the
xfail". The population of recorded parts is Engine S's own `FAILURE_RECORDS`.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from agent_fleet.restate_analyst import steward_correction as sc
from agent_fleet.safety_agent import measures
from agent_fleet.safety_agent.entities import FAILURE_RECORDS

from . import _program_filter as pf

_NORMALISER = (Path(__file__).resolve().parents[3] / "doc-tools" / "doc_tools" / "utils"
               / "text_layer_health.py")
if not _NORMALISER.is_file():
    pytest.skip("sibling doc-tools checkout absent: the normalisation is read from it",
                allow_module_level=True)
_spec = importlib.util.spec_from_file_location("_doc_tools_text_layer_health", _NORMALISER)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
key = _mod._mpn_key

RECORDED = "PN-8801"
RECORDED_KEYS = {key(r.part_number): r.part_number for r in FAILURE_RECORDS}
#: spellings of the recorded part the connector's normalisation folds onto it
MATCHING_VARIANTS = ["pn-8801", "Pn-8801", "PN 8801", "-PN-8801", "PN-8801,"]
#: well-formed, matches no recorded part
UNRECORDED = "ZZ-9999"
BATCH = ["A-1", "B-2"]


def _correct(value):
    return {"corrected": [{"mpn": "A-1", "corrected_mpn": value, "evidence": "page 2"}]}


def _add(value):
    return {"added": [{"mpn": value, "disposition": "affected", "reason": "r", "evidence": "page 2"}]}


def _gate(raw):
    """Today's gate, then what it WRITES: the edit log's `corrected` value of the one edit."""
    edits = sc.validate_row_edits(raw, extracted_mpns=BATCH)
    return sc.edit_log(edits)[0]["corrected"]


def _ask(monkeypatch, pn):
    pf.install(monkeypatch, caller=pf.ALICE, members=pf.ALL_PROGRAMS)
    return measures.what_failed_on_this_part(part_number=pn)


# ── controls: shared gate and population, each differing in the one thing the arm decides on ──

def test_CONTROL_the_normaliser_folds_the_variants_and_not_the_unrecorded_value():
    assert {key(v) for v in MATCHING_VARIANTS} == {key(RECORDED)}
    assert key(UNRECORDED) not in RECORDED_KEYS


def test_CONTROL_the_recorded_spelling_is_accepted_as_a_correction_and_meets_its_records(monkeypatch):
    assert _gate(_correct(RECORDED)) == RECORDED
    out = _ask(monkeypatch, RECORDED)
    assert out["refused"] is False and out["failure_count"] == 2


@pytest.mark.parametrize("value", ["pn-8801", "Pn-8801"])
def test_CONTROL_engine_s_looks_a_part_up_by_exact_spelling(monkeypatch, value):
    """The read side that makes (i) matter: the unfolded spelling meets nothing."""
    out = _ask(monkeypatch, value)
    assert out["refused"] is True and out["outcome"] == "no_failures_recorded"


# ── (iii) the explicit way in: pinned green ────────────────────────────────────────────────

def test_iii_an_unrecorded_value_as_an_explicit_added_edit_is_accepted():
    assert _gate(_add(UNRECORDED)) == UNRECORDED


# ── (i) and (ii): the ruling, red until Lane 1 builds ──────────────────────────────────────

@pytest.mark.xfail(strict=True, reason="a1 (i): a variant is written as typed, so Engine S "
                   "answers no_failures_recorded; the ruling folds it onto the recorded spelling")
@pytest.mark.parametrize("variant", MATCHING_VARIANTS)
def test_i_a_variant_that_matches_after_normalisation_is_written_as_the_recorded_part(
        monkeypatch, variant):
    written = _gate(_correct(variant))            # accepted today; the build must keep accepting
    assert written == RECORDED, f"{variant!r} is written as {written!r}"
    assert _ask(monkeypatch, written)["failure_count"] == 2


@pytest.mark.xfail(strict=True, reason="a1 (ii): a correction that matches no recorded part is "
                   "accepted today; the ruling refuses it")
def test_ii_an_unrecorded_value_as_a_correction_is_refused():
    with pytest.raises(sc.EditRefusal):
        sc.validate_row_edits(_correct(UNRECORDED), extracted_mpns=BATCH)
