"""DataHub schema-skew tolerance — unit tests for the introspection layer
that lets `_FIND_TOOLS_QUERY` work against both DataHub 1.1.0 (nested
`properties.customProperties` shape) and newer DataHub builds
(top-level `Dataset.customProperties` shape).

These tests don't touch a live GMS — they cover the pure-Python helpers
(`_build_find_tools_query`, `_extract_custom_properties`) plus the cache
reset hook. The full introspection path that hits the GMS is exercised
end-to-end at deploy time against whichever DataHub version is wired
up.

The bug this thread closes: when a sandbox cluster runs an older
DataHub version (the case observed: GMS 1.1.0), the prior
`_FIND_TOOLS_QUERY` selected `customProperties` at the top level of
Dataset (the newer-version shape), which trips
`FieldUndefined@[searchAcrossEntities/searchResults/entity/customProperties]`
on the GMS. Engine D logged the error and returned an empty tool list,
breaking JIT tool discovery silently.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest


_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


# Import the unit-under-test helpers. The httpx-using async helpers are
# tested in isolation via monkeypatching of httpx.AsyncClient; the pure
# helpers are exercised directly.
from agent_fleet.datahub_wrapper.main import (  # noqa: E402
    _build_find_tools_query,
    _extract_custom_properties,
    _reset_schema_cache_for_tests,
)


# ===========================================================================
# _build_find_tools_query — emits the right shape per the discovered features
# ===========================================================================
def test_build_query_nested_only_keeps_customProperties_inside_properties():
    """Legacy / v1.1.0 shape: customProperties lives in DatasetProperties
    only. The query MUST select properties { customProperties } and MUST
    NOT select customProperties at the Dataset top level.
    """
    q = _build_find_tools_query({
        "dataset_has_top_level_customProperties": False,
        "dataset_properties_has_customProperties": True,
    })

    # Nested shape is selected
    assert "customProperties { key value }" in q
    assert "properties {" in q

    # Top-level shape is NOT selected — this is what would trip
    # FieldUndefined on DataHub 1.1.0.
    lines = q.splitlines()
    properties_indices = [i for i, line in enumerate(lines) if "properties {" in line]
    assert properties_indices, "expected at least one `properties {` line"
    # Find the indentation of the cp inside properties vs any other line.
    # All customProperties references must be *inside* a properties block:
    cp_lines = [i for i, line in enumerate(lines) if "customProperties" in line]
    assert cp_lines, "expected at least one customProperties reference"
    # Each customProperties reference must come AFTER a `properties {` and
    # before the matching `}` — the simplest structural check is that no
    # customProperties appears at the same indentation level as the
    # `... on Dataset {` block opener.
    dataset_open_lines = [i for i, line in enumerate(lines) if "... on Dataset {" in line]
    assert dataset_open_lines
    dataset_indent = len(lines[dataset_open_lines[0]]) - len(lines[dataset_open_lines[0]].lstrip())
    for cp_i in cp_lines:
        cp_indent = len(lines[cp_i]) - len(lines[cp_i].lstrip())
        assert cp_indent > dataset_indent, (
            f"customProperties at line {cp_i} ({lines[cp_i]!r}) appears at "
            f"the Dataset top-level indent — that's the FieldUndefined shape"
            f" we're guarding against on DataHub 1.1.0."
        )


def test_build_query_top_level_only_emits_top_level_customProperties():
    """Newer shape: customProperties is a top-level Dataset field, and
    DatasetProperties does NOT carry it. The query must select it at the
    top level; the nested properties block must NOT include
    customProperties.
    """
    q = _build_find_tools_query({
        "dataset_has_top_level_customProperties": True,
        "dataset_properties_has_customProperties": False,
    })

    assert "customProperties { key value }" in q

    # The properties block must not have customProperties inside it
    # (otherwise we'd trip FieldUndefined on DatasetProperties).
    lines = q.splitlines()
    in_properties = False
    properties_depth = 0
    properties_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("properties {"):
            in_properties = True
            properties_depth = 1
            continue
        if in_properties:
            properties_depth += stripped.count("{") - stripped.count("}")
            if properties_depth <= 0:
                in_properties = False
                continue
            properties_lines.append(stripped)
    assert not any("customProperties" in line for line in properties_lines), (
        f"properties block should not contain customProperties on the "
        f"newer-only shape. Found: {properties_lines!r}"
    )


def test_build_query_both_shapes_emits_both():
    """Transitional DataHub builds may expose customProperties at both
    locations. The query should select both — the result parser
    (`_extract_custom_properties`) prefers the top-level data when both
    are present and non-empty.
    """
    q = _build_find_tools_query({
        "dataset_has_top_level_customProperties": True,
        "dataset_properties_has_customProperties": True,
    })

    # Both selections should be present — easier to verify by counting
    # `customProperties` references; both shapes adds at least two.
    cp_count = q.count("customProperties")
    assert cp_count >= 2, (
        f"expected customProperties selected in both locations "
        f"(properties.customProperties + top-level Dataset.customProperties), "
        f"got {cp_count}"
    )


def test_build_query_neither_shape_degrades_gracefully():
    """When introspection found NEITHER location (unusual but possible
    on a partially-stripped DataHub schema or auth-restricted GMS), the
    query should still be syntactically valid and not select
    customProperties anywhere — Engine D's result parser returns an
    empty tool list in that case, which the caller treats as
    "no tools tagged with this URI" rather than an error.
    """
    q = _build_find_tools_query({
        "dataset_has_top_level_customProperties": False,
        "dataset_properties_has_customProperties": False,
    })

    assert "customProperties" not in q
    # Basic GraphQL syntactic sanity — the query must still have the
    # surrounding structure intact.
    assert "searchAcrossEntities(input: $input)" in q
    assert "... on Dataset {" in q


# ===========================================================================
# _extract_custom_properties — finds data in either location
# ===========================================================================
def test_extract_prefers_top_level_when_populated():
    """Top-level location takes precedence when both are present and the
    top-level is non-empty. Newer DataHub builds carry the authoritative
    customProperties at the Dataset top level; the nested copy may exist
    for backward compatibility but is treated as fallback only.
    """
    entity = {
        "urn": "urn:li:dataset:(...)",
        "customProperties": [{"key": "top_key", "value": "top_value"}],
        "properties": {
            "name": "test",
            "customProperties": [{"key": "nested_key", "value": "nested_value"}],
        },
    }
    result = _extract_custom_properties(entity)
    assert result == [{"key": "top_key", "value": "top_value"}]


def test_extract_falls_back_to_nested_when_top_level_missing():
    """v1.1.0 shape: only the nested location has data."""
    entity = {
        "urn": "urn:li:dataset:(...)",
        "properties": {
            "name": "test",
            "customProperties": [{"key": "nested_key", "value": "nested_value"}],
        },
    }
    result = _extract_custom_properties(entity)
    assert result == [{"key": "nested_key", "value": "nested_value"}]


def test_extract_falls_back_to_nested_when_top_level_is_empty_list():
    """Some DataHub builds populate both locations but leave the
    top-level empty. Treat empty as "no data here, look elsewhere" —
    the nested location may still carry the authoritative bag.
    """
    entity = {
        "urn": "urn:li:dataset:(...)",
        "customProperties": [],
        "properties": {
            "name": "test",
            "customProperties": [{"key": "nested_key", "value": "nested_value"}],
        },
    }
    result = _extract_custom_properties(entity)
    assert result == [{"key": "nested_key", "value": "nested_value"}]


def test_extract_returns_empty_list_when_neither_present():
    """Defensive: callers expect a list. Don't raise; just return []."""
    entity = {"urn": "urn:li:dataset:(...)", "properties": {"name": "test"}}
    result = _extract_custom_properties(entity)
    assert result == []


def test_extract_handles_missing_properties_block():
    entity = {"urn": "urn:li:dataset:(...)"}
    result = _extract_custom_properties(entity)
    assert result == []


def test_extract_handles_null_properties_block():
    """DataHub sometimes returns `"properties": null` rather than
    omitting the field. Handle that without crashing.
    """
    entity = {"urn": "urn:li:dataset:(...)", "properties": None}
    result = _extract_custom_properties(entity)
    assert result == []


# ===========================================================================
# Cache reset hook
# ===========================================================================
def test_reset_schema_cache_clears_cached_features():
    """The test-only reset hook clears the module-level cache so the
    next `_discover_schema_features()` call re-probes.
    """
    from agent_fleet.datahub_wrapper import main as wrapper

    # Seed a cache value directly
    wrapper._schema_cache = {
        "dataset_has_top_level_customProperties": True,
        "dataset_properties_has_customProperties": True,
    }
    assert wrapper._schema_cache is not None

    _reset_schema_cache_for_tests()
    assert wrapper._schema_cache is None


# ===========================================================================
# Integration: introspection round-trip via mocked httpx
# ===========================================================================
@pytest.mark.asyncio
async def test_discover_schema_features_reports_v1_1_0_shape(monkeypatch):
    """Simulate DataHub 1.1.0: GMS exposes DatasetProperties.customProperties
    but Dataset.customProperties is absent. The introspection helper must
    report this shape correctly so the query builder selects the nested
    block.
    """
    _reset_schema_cache_for_tests()
    from agent_fleet.datahub_wrapper import main as wrapper

    class _FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {
                "data": {
                    "dataset": {"fields": [
                        {"name": "urn"},
                        {"name": "type"},
                        {"name": "properties"},
                        # NO customProperties here — this is the v1.1.0 shape
                    ]},
                    "datasetProperties": {"fields": [
                        {"name": "name"},
                        {"name": "description"},
                        {"name": "customProperties"},
                    ]},
                }
            }

    class _FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def post(self, *a, **k): return _FakeResp()

    monkeypatch.setattr(wrapper.httpx, "AsyncClient", _FakeClient)

    features = await wrapper._discover_schema_features()
    assert features["dataset_has_top_level_customProperties"] is False
    assert features["dataset_properties_has_customProperties"] is True


@pytest.mark.asyncio
async def test_discover_schema_features_reports_newer_shape(monkeypatch):
    """Simulate newer DataHub: GMS exposes Dataset.customProperties at the
    top level. The introspection helper must report this shape so the
    query builder selects the top-level block.
    """
    _reset_schema_cache_for_tests()
    from agent_fleet.datahub_wrapper import main as wrapper

    class _FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {
                "data": {
                    "dataset": {"fields": [
                        {"name": "urn"},
                        {"name": "type"},
                        {"name": "properties"},
                        {"name": "customProperties"},  # top-level shape
                    ]},
                    "datasetProperties": {"fields": [
                        {"name": "name"},
                        {"name": "description"},
                        # Some newer builds drop the nested copy entirely
                    ]},
                }
            }

    class _FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def post(self, *a, **k): return _FakeResp()

    monkeypatch.setattr(wrapper.httpx, "AsyncClient", _FakeClient)

    features = await wrapper._discover_schema_features()
    assert features["dataset_has_top_level_customProperties"] is True
    assert features["dataset_properties_has_customProperties"] is False


@pytest.mark.asyncio
async def test_discover_schema_features_falls_back_to_legacy_on_introspection_failure(monkeypatch):
    """When introspection fails (network error, GMS unreachable, schema
    response malformed), assume the legacy nested shape. This is the
    safer default because the nested shape works on more DataHub
    versions historically.
    """
    _reset_schema_cache_for_tests()
    from agent_fleet.datahub_wrapper import main as wrapper

    class _FailingClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def post(self, *a, **k): raise RuntimeError("GMS unreachable")

    monkeypatch.setattr(wrapper.httpx, "AsyncClient", _FailingClient)

    features = await wrapper._discover_schema_features()
    assert features["dataset_has_top_level_customProperties"] is False
    assert features["dataset_properties_has_customProperties"] is True
