"""PCN/PDN disposition proposer sealed deterministically (feeds the bulk-resolve funnel).

The disposition rule + the honest-degradation property (no confident proposal -> None -> can't ride
accept-all), and the assembly of funnel-ready PartItems from a notice's parts (incl. the real
IPCN25300X shape).

Run:  cd agent_fleet/restate_analyst && uv run --frozen --with pytest pytest ../../tests/test_pcn_disposition_proposer.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_RA = _REPO / "agent_fleet" / "restate_analyst"
for p in (str(_RA), str(_REPO)):
    if p not in sys.path:
        sys.path.insert(0, p)

from agent_fleet.restate_analyst.pcn_disposition_proposer import (  # noqa: E402
    propose_disposition, score_relevance, build_part_items,
)
from agent_fleet.restate_analyst.workflow_bulk_resolve import run_funnel, resolve_batch, BulkDecision, ReviewBatch  # noqa: E402


# ---------------------------------------------------------------------------
# propose_disposition — the rule
# ---------------------------------------------------------------------------

def test_pdn_with_replacement_qualifies():
    assert propose_disposition("PDN", has_replacement=True) == "dispatchQualification"


def test_pdn_without_replacement_is_last_time_buy():
    assert propose_disposition("PDN", has_replacement=False) == "dispatchLTB"


def test_pcn_form_fit_function_change_qualifies():
    assert propose_disposition("PCN", has_replacement=False, categories=["Material"]) == "dispatchQualification"
    # the real IPCN25300X carries Material/Process/Testing -> qualify
    assert propose_disposition("PCN", has_replacement=False,
                               categories=["Material", "Process", "Location", "Testing"]) == "dispatchQualification"


def test_pcn_administrative_only_is_archive():
    assert propose_disposition("PCN", has_replacement=False, categories=["Location", "Packaging"]) == "archive"


def test_pcn_discontinuation_category_takes_the_discontinuation_path():
    assert propose_disposition("PCN", has_replacement=True, categories=["Discontinuation"]) == "dispatchQualification"
    assert propose_disposition("PCN", has_replacement=False, categories=["Discontinuation"]) == "dispatchLTB"


def test_unclassifiable_change_yields_no_proposal():
    """Honest degradation at the proposer: no categories, or an unknown category only, -> None. The
    system proposes only what it's sure of; the approver disposes the rest explicitly."""
    assert propose_disposition("PCN", has_replacement=False, categories=None) is None
    assert propose_disposition("PCN", has_replacement=False, categories=["Firmware"]) is None


# ---------------------------------------------------------------------------
# score_relevance — scope is an input, no optimistic default
# ---------------------------------------------------------------------------

def test_relevance_is_scope_membership():
    scope = {"NSR01L30NXT5G", "NSR01F30NXT5G"}
    assert score_relevance("NSR01L30NXT5G", in_scope_mpns=scope) == 1.0
    assert score_relevance("SOMETHING_ELSE", in_scope_mpns=scope) == 0.0


def test_empty_scope_filters_everything_honestly():
    assert score_relevance("NSR01L30NXT5G", in_scope_mpns=set()) == 0.0


# ---------------------------------------------------------------------------
# build_part_items — assembly + funnel integration
# ---------------------------------------------------------------------------

_PARTS = [
    {"affected_mpn": "NSR01L30NXT5G", "replacement_mpn": "SNSR01F30NXT5G"},
    {"affected_mpn": "NSR01F30NXT5G", "replacement_mpn": None, "needs_review": True},
    {"affected_mpn": "NOT_OURS", "replacement_mpn": None},
    {"affected_mpn": "", "replacement_mpn": None},  # skipped
]
_SCOPE = {"NSR01L30NXT5G", "NSR01F30NXT5G"}


def test_build_part_items_shapes_and_scoping():
    items = build_part_items(_PARTS, doc_type="PCN", categories=["Material"], in_scope_mpns=_SCOPE)
    assert len(items) == 3  # the empty-mpn row is skipped
    by = {i.mpn: i for i in items}
    assert by["NSR01L30NXT5G"].relevance == 1.0 and by["NSR01L30NXT5G"].proposed_disposition == "dispatchQualification"
    assert by["NSR01F30NXT5G"].needs_review is True          # carried from extraction
    assert by["NOT_OURS"].relevance == 0.0                   # out of scope -> will be filtered
    assert all(i.subject is None for i in items)             # subject filled by resolveInstance step


def test_proposer_output_flows_through_the_funnel():
    """Assembled items reduce correctly: out-of-scope filtered, needs_review forced to residue."""
    items = build_part_items(_PARTS, doc_type="PCN", categories=["Material"], in_scope_mpns=_SCOPE)
    res = run_funnel(items, relevance_floor=0.5)
    assert [p.mpn for p in res.filtered] == ["NOT_OURS"]     # out of scope
    assert "NSR01F30NXT5G" in [p.mpn for p in res.review_forced]  # needs_review -> residue
    assert {p.mpn for p in res.residue} == {"NSR01L30NXT5G", "NSR01F30NXT5G"}


def test_unclassifiable_proposal_cannot_ride_accept_all_end_to_end():
    """A part the proposer couldn't classify (None disposition) reaches the approver and BLOCKS
    accept-all until dispositioned — the honest-degradation chain from proposer to core seal."""
    items = build_part_items(
        [{"affected_mpn": "NSR01L30NXT5G", "replacement_mpn": None}],
        doc_type="PCN", categories=["Firmware"], in_scope_mpns={"NSR01L30NXT5G"})  # unknown category -> None
    assert items[0].proposed_disposition is None
    batch = ReviewBatch(approver="alice", items=items)
    import pytest
    with pytest.raises(ValueError):
        resolve_batch(batch, BulkDecision(), notice_fingerprint="IPCN25300X")
