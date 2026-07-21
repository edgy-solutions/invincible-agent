"""Tests for the subject-resolution honest-degradation guard (recall-override).

The load-bearing property: when the LLM's class pick stood ALONE (no phone-book
preemption) and overrode a STRONG vector-recall winner, the reported confidence
is discounted and provenance flags it — so a silent confidently-wrong subject
becomes a visibly weak one. Conservative: a small-margin override, or a weak
top candidate, must NOT trip it (that would penalize the LLM legitimately
correcting noisy recall).

Authored data only — generic idp class URIs.
"""
from __future__ import annotations

from agent_fleet.ontology_service.recall_guard import (
    _RECALL_OVERRIDE_CEIL,
    recall_override_guard,
)

IDP = "http://invincible-agent/idp#"
DASH, TABLE, DATASET = IDP + "Dashboard", IDP + "Table", IDP + "Dataset"


def _cands(*pairs):
    return [{"uri": u, "score": s} for u, s in pairs]


def test_the_work_case_fires_discounts_and_flags():
    # subject=Table @0.78 chosen over Dashboard @recall-1.00 (no phone-book)
    conf, reason, prov = recall_override_guard(
        TABLE, 0.78, _cands((DASH, 1.00), (DATASET, 0.62), (TABLE, 0.45)), "picked Table", None)
    assert conf == _RECALL_OVERRIDE_CEIL          # 0.78 -> 0.50
    assert prov["recall_override"] is True
    assert prov["recall_top_uri"] == DASH
    assert "WEAK PATH" in reason and "Dashboard" in reason and "Table" in reason


def test_pick_is_the_recall_winner_is_a_noop():
    # LLM agreed with vector recall — nothing weak about it
    conf, reason, prov = recall_override_guard(
        DASH, 0.82, _cands((DASH, 1.00), (TABLE, 0.45)), "picked Dashboard", None)
    assert conf == 0.82 and prov["recall_override"] is False and reason == "picked Dashboard"


def test_small_margin_override_is_a_noop():
    # top 0.72, pick 0.60 -> gap 0.12 < margin, AND top < strong: don't penalize
    conf, reason, prov = recall_override_guard(
        TABLE, 0.75, _cands((DASH, 0.72), (TABLE, 0.60)), "r", None)
    assert conf == 0.75 and prov["recall_override"] is False


def test_strong_winner_but_narrow_gap_is_a_noop():
    # top 0.90 (strong) but pick 0.80 -> gap 0.10 < 0.35: legit close call, no-op
    conf, _, prov = recall_override_guard(
        TABLE, 0.75, _cands((DASH, 0.90), (TABLE, 0.80)), "r", None)
    assert conf == 0.75 and prov["recall_override"] is False


def test_already_low_confidence_is_not_raised():
    # guard only ever CAPS; a 0.30 pick that overrode strong recall stays 0.30
    conf, _, prov = recall_override_guard(
        TABLE, 0.30, _cands((DASH, 1.00), (TABLE, 0.20)), "r", None)
    assert conf == 0.30 and prov["recall_override"] is True


def test_no_candidates_is_a_noop():
    conf, reason, prov = recall_override_guard(TABLE, 0.9, [], "r", None)
    assert conf == 0.9 and prov["recall_override"] is False


def test_preserves_prior_provenance_keys():
    conf, _, prov = recall_override_guard(
        TABLE, 0.78, _cands((DASH, 1.00), (TABLE, 0.40)), "r", {"instance_match": "empty"})
    assert prov["instance_match"] == "empty" and prov["recall_override"] is True
