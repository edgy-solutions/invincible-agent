"""Pure-logic tests for Recipe v2's instance-resolution decision table.

The decision table — `agent_fleet.ontology_service.instance_resolution.decide`
— is the load-bearing pure function the router consumes when the LLM
extracts an `instance_identifier` from a query. These tests run with
no cluster, no HTTP, no Neo4j, no LLM. They're cheap and exhaustive on
purpose: every decision branch this function takes has to be testable
without spinning anything up, because the design's correctness lives
or dies in this small table.

Per Recipe v2 §5 build order: this test file lands BEFORE Engine O is
wired to call the table. The router-side wiring goes red until all
these cases turn green.
"""

from __future__ import annotations

import pytest

from agent_fleet.ontology_service.instance_resolution import (
    DEFAULT_EXACT_THRESHOLD,
    DEFAULT_MIN_SCORE,
    InstanceCandidate,
    decide,
)


def _c(score: float, class_uri: str = "idp:Table", *, instance_id: str = "urn:x", label: str = "x", provider: str = "engine_d") -> InstanceCandidate:
    return InstanceCandidate(
        instance_id=instance_id, class_uri=class_uri,
        label=label, score=score, provider=provider,
    )


# ---------------------------------------------------------------------------
# Exact match → class OVERRIDES with confidence 1.0
# ---------------------------------------------------------------------------

def test_exact_match_overrides_with_confidence_one():
    candidates = [_c(1.0, "idp:Table", instance_id="urn:li:dataset:rev_sum", label="gold.sales.revenue_summary")]
    d = decide(candidates)
    assert d.subject_uri == "idp:Table"
    assert d.confidence == 1.0
    assert d.provenance["instance_resolved"] is True
    assert d.provenance["instance_match"] == "exact"
    assert d.provenance["instance_id"] == "urn:li:dataset:rev_sum"
    assert d.provenance["instance_n"] == 1


def test_score_at_exact_threshold_still_counts_as_exact():
    candidates = [_c(DEFAULT_EXACT_THRESHOLD, "idp:Dashboard")]
    d = decide(candidates)
    assert d.subject_uri == "idp:Dashboard"
    assert d.provenance["instance_match"] == "exact"


def test_exact_match_uses_top_score_candidate():
    candidates = [
        _c(0.85, "idp:Table", instance_id="urn:b", label="b"),
        _c(0.98, "idp:Dashboard", instance_id="urn:a", label="a"),
        _c(0.72, "idp:Table", instance_id="urn:c", label="c"),
    ]
    d = decide(candidates)
    assert d.subject_uri == "idp:Dashboard"
    assert d.provenance["instance_id"] == "urn:a"


# ---------------------------------------------------------------------------
# Fuzzy + unanimous class → that class wins with high (not 1.0) confidence
# ---------------------------------------------------------------------------

def test_fuzzy_unanimous_class_overrides():
    # R2 — typo / fuzzy unanimous: five near-matches all Tables.
    candidates = [
        _c(0.85, "idp:Table", instance_id=f"urn:t{i}", label=f"t{i}")
        for i in range(5)
    ]
    d = decide(candidates)
    assert d.subject_uri == "idp:Table"
    assert 0.7 <= d.confidence < 1.0
    assert d.provenance["instance_resolved"] is True
    assert d.provenance["instance_match"] == "fuzzy"
    assert d.provenance["instance_n"] == 5


def test_fuzzy_unanimous_single_candidate():
    # One survivor above threshold but below exact — still confidence-
    # boosted, classified, fuzzy.
    candidates = [_c(0.8, "idp:Pipeline")]
    d = decide(candidates)
    assert d.subject_uri == "idp:Pipeline"
    assert d.provenance["instance_match"] == "fuzzy"
    assert d.provenance["instance_n"] == 1


# ---------------------------------------------------------------------------
# Fuzzy + mixed classes → abstain (v1 simplification; v2 = ADR-0015)
# ---------------------------------------------------------------------------

def test_fuzzy_mixed_classes_abstains():
    # "revenue_summary" matches both a table AND a dashboard — abstain
    # to the LLM's existing guess rather than coin-flip the class.
    candidates = [
        _c(0.85, "idp:Table",     instance_id="urn:t", label="revenue_summary"),
        _c(0.82, "idp:Dashboard", instance_id="urn:d", label="Revenue Summary"),
    ]
    d = decide(candidates)
    assert d.subject_uri is None
    assert d.confidence == 0.0
    assert d.provenance["instance_resolved"] is False
    assert d.provenance["instance_match"] == "mixed"
    assert d.provenance["instance_distinct_classes"] == ["idp:Dashboard", "idp:Table"]


def test_mixed_with_one_exact_still_treats_exact_as_winner():
    # If one candidate is exact, that one wins regardless of how many
    # fuzzier ones surround it — exact-match short-circuits the table.
    candidates = [
        _c(1.0,  "idp:Table",     instance_id="urn:t", label="customers_gold"),
        _c(0.82, "idp:Dashboard", instance_id="urn:d", label="Customers Dashboard"),
    ]
    d = decide(candidates)
    assert d.subject_uri == "idp:Table"
    assert d.provenance["instance_match"] == "exact"


# ---------------------------------------------------------------------------
# Empty / all-below-threshold → abstain (fall through to LLM resolve)
# ---------------------------------------------------------------------------

def test_empty_candidate_list_abstains():
    d = decide([])
    assert d.subject_uri is None
    assert d.provenance["instance_match"] == "empty"
    assert d.provenance["instance_n"] == 0


def test_all_below_threshold_abstains_and_reports_total_seen():
    # Provider returned 4 candidates but each scored below the router's
    # belt-and-suspenders min_score. v1 disease prevention: NEVER treat
    # top-of-fuzzy-search as a match.
    candidates = [_c(0.5, "idp:Table") for _ in range(4)]
    d = decide(candidates)
    assert d.subject_uri is None
    assert d.provenance["instance_match"] == "empty"
    # The router knows the provider tried — n reflects what was offered,
    # not just what survived the floor.
    assert d.provenance["instance_n"] == 4


def test_only_one_above_threshold_is_treated_as_fuzzy_unanimous():
    # Three candidates: only one passes min_score. That one wins as
    # fuzzy-unanimous (n=1), not as exact unless it crosses
    # exact_threshold.
    candidates = [
        _c(0.55, "idp:Table"),
        _c(0.78, "idp:Table"),
        _c(0.65, "idp:Table"),
    ]
    d = decide(candidates)
    assert d.subject_uri == "idp:Table"
    assert d.provenance["instance_match"] == "fuzzy"
    assert d.provenance["instance_n"] == 1


# ---------------------------------------------------------------------------
# Threshold overrides — tunable per call (env-driven in production)
# ---------------------------------------------------------------------------

def test_tight_exact_threshold_can_demote_to_fuzzy():
    # A 0.95 score is exact under the default; under exact_threshold=
    # 0.99 it's just a very-good fuzzy match.
    candidates = [_c(0.95, "idp:Table")]
    d = decide(candidates, exact_threshold=0.99)
    assert d.subject_uri == "idp:Table"
    assert d.provenance["instance_match"] == "fuzzy"


def test_relaxed_min_score_admits_more_candidates():
    candidates = [_c(0.6, "idp:Table"), _c(0.5, "idp:Table")]
    d_strict  = decide(candidates, min_score=0.7)
    d_relaxed = decide(candidates, min_score=0.4)
    assert d_strict.subject_uri is None
    assert d_relaxed.subject_uri == "idp:Table"
    assert d_relaxed.provenance["instance_n"] == 2


# ---------------------------------------------------------------------------
# Provider-timeout shape — caller's responsibility, but the table must
# still produce a sensible decision when handed an empty list because a
# provider timed out (caller substitutes []).
# ---------------------------------------------------------------------------

def test_provider_timeout_emulated_as_empty_list_abstains():
    # Caller fans out to N providers in parallel; timeouts become empty
    # answers; the surviving union is what hits the table.
    d = decide([])
    assert d.subject_uri is None
    assert d.provenance["instance_match"] == "empty"


# ---------------------------------------------------------------------------
# Sanity: provenance schema is stable enough to log against
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("candidates,expected_match", [
    ([_c(1.0, "idp:Table")],                                  "exact"),
    ([_c(0.85, "idp:Table"), _c(0.84, "idp:Table")],          "fuzzy"),
    ([_c(0.85, "idp:Table"), _c(0.84, "idp:Dashboard")],      "mixed"),
    ([],                                                       "empty"),
    ([_c(0.4, "idp:Table")],                                  "empty"),
])
def test_provenance_always_has_match_label(candidates, expected_match):
    d = decide(candidates)
    assert d.provenance["instance_match"] == expected_match
    assert "instance_resolved" in d.provenance
    assert "instance_n" in d.provenance


# ─────────────────────────────────────────────────────────────────────────────
# THE SELF-MATCH PROPERTY — pinned as a strict xfail while the ruling is open
# ─────────────────────────────────────────────────────────────────────────────

# MARKER FLIPPED 2026-08-30 — the ruling landed and this now passes. Preserved verbatim
# rather than deleted, because the xfail's own reason is the clearest statement of what was
# broken and it did exactly the job it was written for: STRICT, so it went red the moment
# the gate was fixed, telling whoever fixed it to flip it rather than leave a
# silently-passing xfail behind.
#
#     OPEN RULING — see docs/plans/the-specificity-gate-strips-content-words.md.
#     `passes_segment_specificity(x, x)` is FALSE for any space-separated label whose final
#     word is in _ENV_SUFFIXES, because only the CANDIDATE side strips those suffixes:
#     'Integration and Test' yields name 'test' as an identifier and asset name 'and' as a
#     candidate, so a name cannot match itself. Measured consequence: every one of
#     engine-fin's tied-at-top cases returns `not_specific` — including an exact 1.00 label
#     match — so the decision table never reaches `mixed` and ADR-0033's disambiguation
#     consumer cannot fire.
#
# THE RULING: both readings, because neither alone works. Symmetry ALONE is a regression
# (it empties "Test" and refuses an identity); path-scoping ALONE still fails
# `publog.p_cage.prod`. See `_strip_env_suffixes` in instance_resolution.py for the measured
# table. The third reading — whether "the last word is the name" suits English phrases —
# remains open and is not prejudged.
def test_a_name_matches_ITSELF():
    """The property that must hold whichever reading of the gate wins.

    An identity that fails a specificity check is incoherent regardless of whether the fix is
    symmetry (strip suffixes on both sides), scoping (strip only on id-shaped text), or
    rethinking terminal-name for multi-word labels. So this is the assertion to keep, and it
    is written now — while the ruling is open — rather than after, because the value of a
    property test is that it predates the fix it describes.

    Parameterisation is deliberately inline: a parametrised xfail reports one result per case
    and the claim here is about ALL of them at once."""
    from agent_fleet.ontology_service.instance_resolution import passes_segment_specificity

    failures = [
        s for s in (
            "Integration and Test",          # a real IPMDAR ControlAccount
            "Acceptance Test",
            "Site A — Aurora",               # passes today — the control
            "Order to Cash",                 # passes today — the control
            "Core ERP Platform",             # passes today — the control
            "my_dataset_prod",               # passes today — one segment, nothing stripped
        )
        if not passes_segment_specificity(s, s)
    ]
    assert not failures, (
        f"a name did not match itself: {failures}. Only the candidate side strips "
        f"_ENV_SUFFIXES, so a label ending in prod|dev|test|stage|staging|qa|uat is given two "
        f"different names by the two halves of the comparison."
    )
