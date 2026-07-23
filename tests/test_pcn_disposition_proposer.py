"""PCN/PDN disposition proposer (MECHANISM) sealed deterministically. Policy is DATA (the TTL); these
seal the EVALUATOR against a fixture ruleset that mirrors setup/ontologies/pcn_disposition_rules.ttl.

Covers: rule evaluation (all-match-must-agree), honest degradation (unclassifiable), the NEW
abstain-on-conflict outcome (only possible once rules are data), the ingest validation gate, and the
funnel integration.

Run:  cd agent_fleet/restate_analyst && uv run --frozen --with pytest pytest ../../tests/test_pcn_disposition_proposer.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_RA = _REPO / "agent_fleet" / "restate_analyst"
for p in (str(_RA), str(_REPO)):
    if p not in sys.path:
        sys.path.insert(0, p)

from agent_fleet.restate_analyst.pcn_disposition_proposer import (  # noqa: E402
    evaluate_rules, validate_ruleset, score_relevance, build_part_items,
    MATCHED, UNCLASSIFIABLE, CONFLICT,
)
from agent_fleet.restate_analyst.workflow_bulk_resolve import (  # noqa: E402
    run_funnel, resolve_batch, BulkDecision, ReviewBatch,
)

# Fixture ruleset — MIRRORS setup/ontologies/pcn_disposition_rules.ttl (the seed policy). The seal is
# on the evaluator; the live ruleset is loaded from the graph by the driver.
_CATEGORY_CLASSES = {
    "Material": "form_fit_function", "Process": "form_fit_function", "Testing": "form_fit_function",
    "Location": "administrative", "Packaging": "administrative", "Discontinuation": "discontinuance",
}
_RULESET = [
    {"id": "DiscWithRepl", "whenNoticeType": "PDN", "whenHasReplacement": True, "proposesDisposition": "dispatchQualification"},
    {"id": "DiscNoRepl", "whenNoticeType": "PDN", "whenHasReplacement": False, "proposesDisposition": "dispatchLTB"},
    {"id": "DiscCatRepl", "whenAnyChangeClass": "discontinuance", "whenHasReplacement": True, "proposesDisposition": "dispatchQualification"},
    {"id": "DiscCatNoRepl", "whenAnyChangeClass": "discontinuance", "whenHasReplacement": False, "proposesDisposition": "dispatchLTB"},
    {"id": "FFF", "whenNoticeType": "PCN", "whenAnyChangeClass": "form_fit_function", "proposesDisposition": "dispatchQualification"},
    {"id": "AdminOnly", "whenNoticeType": "PCN", "whenAllChangeClass": "administrative", "proposesDisposition": "archive"},
]
_DISPOSITIONS = {"dispatchLTB", "dispatchQualification", "dispatchAltSourcing", "archive"}


def _ev(doc_type, has_replacement, categories):
    return evaluate_rules(doc_type=doc_type, has_replacement=has_replacement, categories=categories,
                          ruleset=_RULESET, category_classes=_CATEGORY_CLASSES)


# ---------------------------------------------------------------------------
# Evaluation semantics against the seed ruleset
# ---------------------------------------------------------------------------

def test_pdn_with_replacement_qualifies():
    r = _ev("PDN", True, None)
    assert r.disposition == "dispatchQualification" and r.outcome == MATCHED


def test_pdn_without_replacement_is_last_time_buy():
    assert _ev("PDN", False, None).disposition == "dispatchLTB"


def test_real_ipcn_shape_qualifies():
    # IPCN25300X: PCN, Material/Process/Location/Testing -> a form/fit/function change -> qualify.
    r = _ev("PCN", False, ["Material", "Process", "Location", "Testing"])
    assert r.disposition == "dispatchQualification" and r.outcome == MATCHED


def test_administrative_only_change_archives():
    assert _ev("PCN", False, ["Location", "Packaging"]).disposition == "archive"


def test_no_categories_is_unclassifiable():
    r = _ev("PCN", False, None)
    assert r.disposition is None and r.outcome == UNCLASSIFIABLE


def test_unknown_category_is_unclassifiable():
    r = _ev("PCN", False, ["Firmware"])  # not in category_classes -> no change-class matches
    assert r.disposition is None and r.outcome == UNCLASSIFIABLE


# ---------------------------------------------------------------------------
# Abstain-on-conflict — the NEW outcome that only exists once rules are data
# ---------------------------------------------------------------------------

def test_conflicting_rules_abstain_rather_than_pick():
    """A PCN that is BOTH a discontinuance-with-no-replacement (-> LTB) AND a form/fit/function change
    (-> qualify) genuinely disagrees. The evaluator ABSTAINS (no proposal) rather than silently pick
    one — the honest-degradation discipline applied to rule conflict."""
    r = _ev("PCN", False, ["Discontinuation", "Material"])
    assert r.disposition is None and r.outcome == CONFLICT


def test_conflicting_rules_that_agree_do_not_abstain():
    """The same overlap but WITH a replacement: discontinuance+repl -> qualify AND fff -> qualify.
    They agree, so it proposes (overlaps that agree are fine; only disagreement abstains)."""
    r = _ev("PCN", True, ["Discontinuation", "Material"])
    assert r.disposition == "dispatchQualification" and r.outcome == MATCHED


# ---------------------------------------------------------------------------
# Ingest validation gate — a malformed ruleset fails at ingest, not at an approver's screen
# ---------------------------------------------------------------------------

def test_seed_ruleset_is_valid():
    assert validate_ruleset(_RULESET, known_dispositions=_DISPOSITIONS) == []


def test_unregistered_disposition_is_rejected():
    bad = _RULESET + [{"id": "Bogus", "whenNoticeType": "PDN", "proposesDisposition": "dispatchMagic"}]
    errs = validate_ruleset(bad, known_dispositions=_DISPOSITIONS)
    assert any("dispatchMagic" in e for e in errs)


def test_direct_contradiction_is_rejected():
    """Two rules, identical conditions, different disposition -> an always-conflict that would abstain
    every matching part. Caught at ingest."""
    bad = [
        {"id": "A", "whenNoticeType": "PDN", "whenHasReplacement": True, "proposesDisposition": "dispatchQualification"},
        {"id": "B", "whenNoticeType": "PDN", "whenHasReplacement": True, "proposesDisposition": "dispatchLTB"},
    ]
    errs = validate_ruleset(bad, known_dispositions=_DISPOSITIONS)
    assert any("contradiction" in e for e in errs)


# ---------------------------------------------------------------------------
# score_relevance + funnel integration (unchanged mechanism)
# ---------------------------------------------------------------------------

def test_relevance_is_scope_membership():
    scope = {"NSR01L30NXT5G"}
    assert score_relevance("NSR01L30NXT5G", in_scope_mpns=scope) == 1.0
    assert score_relevance("OTHER", in_scope_mpns=scope) == 0.0
    assert score_relevance("NSR01L30NXT5G", in_scope_mpns=set()) == 0.0


_PARTS = [
    {"affected_mpn": "NSR01L30NXT5G", "replacement_mpn": "SNSR01F30NXT5G"},
    {"affected_mpn": "NSR01F30NXT5G", "replacement_mpn": None, "needs_review": True},
    {"affected_mpn": "NOT_OURS", "replacement_mpn": None},
    {"affected_mpn": "", "replacement_mpn": None},  # skipped
]
_SCOPE = {"NSR01L30NXT5G", "NSR01F30NXT5G"}


def _build(parts, categories):
    return build_part_items(parts, doc_type="PCN", categories=categories, in_scope_mpns=_SCOPE,
                            ruleset=_RULESET, category_classes=_CATEGORY_CLASSES)


def test_build_part_items_shapes_and_scoping():
    items = _build(_PARTS, ["Material"])
    assert len(items) == 3
    by = {i.mpn: i for i in items}
    assert by["NSR01L30NXT5G"].relevance == 1.0 and by["NSR01L30NXT5G"].proposed_disposition == "dispatchQualification"
    assert by["NSR01F30NXT5G"].needs_review is True
    assert by["NOT_OURS"].relevance == 0.0
    assert all(i.subject is None for i in items)


def test_proposer_output_flows_through_the_funnel():
    items = _build(_PARTS, ["Material"])
    res = run_funnel(items, relevance_floor=0.5)
    assert [p.mpn for p in res.filtered] == ["NOT_OURS"]
    assert "NSR01F30NXT5G" in [p.mpn for p in res.review_forced]


def test_unclassifiable_proposal_cannot_ride_accept_all_end_to_end():
    """A part the rules couldn't classify (None disposition) BLOCKS accept-all until dispositioned —
    the honest-degradation chain from proposer (no rule) to the core seal."""
    items = _build([{"affected_mpn": "NSR01L30NXT5G", "replacement_mpn": None}], ["Firmware"])
    assert items[0].proposed_disposition is None
    batch = ReviewBatch(approver="alice", items=items)
    with pytest.raises(ValueError):
        resolve_batch(batch, BulkDecision(), notice_fingerprint="IPCN25300X")
