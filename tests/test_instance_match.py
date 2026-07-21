"""Tests for resolveInstance name-matching (the descriptor-suffix fix).

The failure this fixes: a user names an asset with appended descriptors
("customer 360 superset dashboard"); DataHub's search on the full string
returns nothing, and even the core name scored against the full identifier fell
below the resolve floor (~0.57 fuzzy). The two behaviors here fix it while
holding precision — a lone descriptor word must NOT earn the strong boost.

Authored data only — invented names, generic descriptors.
"""
from __future__ import annotations

from agent_fleet.datahub_wrapper.instance_match import name_score, strip_descriptor_tokens


# --- strip_descriptor_tokens: build the reduced fallback query ---------------

def test_strip_removes_entity_type_and_platform_and_articles():
    assert strip_descriptor_tokens("customer 360 superset dashboard") == "customer 360"
    assert strip_descriptor_tokens("the orders table") == "orders"
    assert strip_descriptor_tokens("revenue by region tableau workbook") == "revenue by region"


def test_strip_is_a_noop_when_no_descriptors():
    assert strip_descriptor_tokens("customer 360") == "customer 360"


# --- name_score: the descriptor case now clears the floor --------------------

def test_core_name_inside_descriptor_phrase_is_a_strong_hit():
    # THE case: was ~0.57 (below floor) -> now 0.9 via multi-word containment.
    assert name_score("customer 360 superset dashboard", "Customer 360") == 0.9


def test_exact_and_suffix_unchanged():
    assert name_score("Customer 360", "customer 360") == 1.0
    # dotted alias suffix (the original reason the suffix rule exists)
    assert name_score("gold.sales.revenue_summary", "revenue_summary") == 0.9


def test_lone_descriptor_word_does_NOT_win():
    # "Dashboard" is a suffix of the identifier but a lone descriptor word — it
    # must NOT score 0.9 (that would tie the real hit and force an abstain).
    assert name_score("customer 360 superset dashboard", "Dashboard") < 0.6
    assert name_score("orders table", "Table") < 0.6


def test_single_word_core_stays_fuzzy_not_boosted():
    # "Orders" (1 token) is not a >=2-token containment; no spurious boost.
    s = name_score("orders table", "Orders")
    assert s < 0.9


def test_unrelated_names_score_low():
    assert name_score("customer 360 superset dashboard", "Weather Map") < 0.5


def test_empty_is_zero():
    assert name_score("", "Customer 360") == 0.0
    assert name_score("Customer 360", "") == 0.0
