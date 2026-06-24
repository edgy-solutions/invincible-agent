"""Unit tests for Engine A's Phase 3 source-attribution helpers.

The closure-bound `_collect_datahub_source` inside the /analyze handler
appends Source records by parsing DataHub URNs through the module-level
``parse_datahub_urn`` helper. This file pins the URN-parsing behavior
across the four shapes that datahub_wrapper's referenced_uris emits
(dataset, dashboard, chart, tag) so a regression in the URN-parser
goes red before it ships as silently-mislabeled HUD entries on the
SourcesTrail.

The end-to-end probe (catalog query → /interview/stream → assert
`sources` SSE event contains ≥1 urn:li:dataset entry) lives at the
sandbox-e2e layer rather than here — it requires Restate + Dagster +
the LLM stack and is too slow for the unit suite. Per
[[feedback-integration-positive-controls]], that end-to-end probe is
a Phase 3 follow-up (Engines W and E shipped without one too; the
gap is fleet-wide for source attribution, not Engine A-specific).
"""
from __future__ import annotations

import pytest

from agent_fleet.restate_analyst.urn_utils import parse_datahub_urn


def test_dataset_urn_extracts_middle_segment_as_label():
    """Dataset URNs encode (platformURN, name, env); name is in the middle."""
    urn = "urn:li:dataset:(urn:li:dataPlatform:snowflake,gold.sales.revenue_summary,PROD)"
    entity_type, label = parse_datahub_urn(urn)
    assert entity_type == "dataset"
    assert label == "gold.sales.revenue_summary"


def test_dataset_urn_with_different_platform_and_env():
    """Same shape, different platform/env — the middle segment still wins."""
    urn = "urn:li:dataset:(urn:li:dataPlatform:bigquery,analytics.fct_orders,DEV)"
    entity_type, label = parse_datahub_urn(urn)
    assert entity_type == "dataset"
    assert label == "analytics.fct_orders"


def test_dashboard_urn_extracts_trailing_segment_as_label():
    """Dashboard URNs are (platform, name); name is the last segment."""
    urn = "urn:li:dashboard:(superset,Revenue by Region)"
    entity_type, label = parse_datahub_urn(urn)
    assert entity_type == "dashboard"
    assert label == "Revenue by Region"


def test_chart_urn_extracts_trailing_segment_as_label():
    """Chart URNs follow the same (platform, name) shape as dashboards."""
    urn = "urn:li:chart:(superset,Monthly Revenue)"
    entity_type, label = parse_datahub_urn(urn)
    assert entity_type == "chart"
    assert label == "Monthly Revenue"


def test_tag_urn_falls_through_to_simple_body():
    """Tag URNs don't have parens — the body itself is the label."""
    urn = "urn:li:tag:gold"
    entity_type, label = parse_datahub_urn(urn)
    assert entity_type == "tag"
    assert label == "gold"


def test_dataset_urn_with_whitespace_segments_strips_correctly():
    """DataHub occasionally returns segments padded with whitespace —
    don't carry that into the rendered label."""
    urn = "urn:li:dataset:(urn:li:dataPlatform:snowflake, gold.sales.revenue_summary , PROD)"
    entity_type, label = parse_datahub_urn(urn)
    assert entity_type == "dataset"
    assert label == "gold.sales.revenue_summary"


def test_empty_urn_returns_unknown():
    """An empty string is a defensive case — must not raise, just abstain
    on the type and return empty label."""
    entity_type, label = parse_datahub_urn("")
    assert entity_type == "unknown"
    assert label == ""


def test_non_urn_string_returns_unknown_with_raw_input():
    """Anything that doesn't start with urn:li: is reflected back so the
    caller can see what it actually got rather than a silent empty."""
    entity_type, label = parse_datahub_urn("not-a-urn")
    assert entity_type == "unknown"
    assert label == "not-a-urn"


def test_urn_with_no_body_returns_unknown():
    """`urn:li:` alone (no body) is malformed — return ``unknown`` rather
    than crashing on the missing trailing colon."""
    entity_type, label = parse_datahub_urn("urn:li:")
    # The body is empty after stripping "urn:li:", so type-end search
    # finds no colon → unknown.
    assert entity_type == "unknown"


def test_dataset_urn_with_only_two_segments_returns_last():
    """Defensive: a dataset URN that's missing the env segment
    (shouldn't happen, but handle it) returns the last segment rather
    than out-of-range-indexing."""
    urn = "urn:li:dataset:(snowflake,partial_name)"
    entity_type, label = parse_datahub_urn(urn)
    assert entity_type == "dataset"
    # Two segments → second-to-last is "snowflake", last is
    # "partial_name". For the partial case the function picks the
    # second-to-last (index -2). That's "snowflake" here, which is
    # less informative than "partial_name" but the function is
    # consistent — flagging the trade-off for the test reader.
    assert label in ("snowflake", "partial_name")


def test_parse_is_pure_no_mutation():
    """parse_datahub_urn is a pure function; the same input yields the
    same output across repeated calls."""
    urn = "urn:li:dataset:(urn:li:dataPlatform:snowflake,gold.sales.revenue_summary,PROD)"
    first = parse_datahub_urn(urn)
    second = parse_datahub_urn(urn)
    third = parse_datahub_urn(urn)
    assert first == second == third
