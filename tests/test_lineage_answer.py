"""Tests for the deterministic traceLineage answer assembler (ADR-0030).

The load-bearing property: the summary is derived FROM structured_data, so a
change to the structure changes the summary — they cannot disagree. And the six
outcomes render distinctly, so the honest distinctions (edgeless-filtered vs
walk-failed; not-mentioned vs unrecognized-platform; found vs ambiguous vs
not-found) are never conflated.

Authored data only — invented names, generic platform slugs. No catalog content.
"""
from __future__ import annotations

from agent_fleet.restate_analyst.lineage_answer import (
    OUTCOME_AMBIGUOUS,
    OUTCOME_COULDNT_LOCATE,
    OUTCOME_LINEAGE_ERROR,
    OUTCOME_LIST,
    OUTCOME_NONE,
    OUTCOME_UNRECOGNIZED_PLATFORM,
    OUTPUT_URI_LINEAGE_TOPOLOGY,
    build_trace_lineage_answer,
)

FOUND = {"outcome": "found", "urn": "urn:li:dashboard:(authored_bi,1)", "candidate_count": 1}
SCOPE_WH = {"platforms": ["warehouse_a"], "platform_mentioned": True, "unrecognized": []}
SCOPE_NONE = {"platforms": [], "platform_mentioned": False, "unrecognized": []}


def _ds(platform, name):
    return f"urn:li:dataset:(urn:li:dataPlatform:{platform},{name},PROD)"


def _result(matches, considered=None, truncated=False, **extra):
    r = {"matches": matches, "match_count": len(matches),
         "considered_count": considered if considered is not None else len(matches),
         "truncated": truncated}
    r.update(extra)
    return r


# --- output_uri is FIXED regardless of outcome (ADR-0030 rule 1) -------------

def test_output_uri_is_always_lineage_topology():
    for res in [
        build_trace_lineage_answer(asset_label="A", resolve=FOUND, platform_scope=SCOPE_WH,
                                   lineage_result=_result([{"urn": _ds("warehouse_a", "z.t"), "platforms": ["warehouse_a"]}])),
        build_trace_lineage_answer(asset_label="A", resolve=FOUND, platform_scope=SCOPE_WH,
                                   lineage_result=_result([], considered=5)),
        build_trace_lineage_answer(asset_label="A", resolve={"outcome": "not_found"}, platform_scope=SCOPE_WH, lineage_result=None),
    ]:
        assert res["output_uri"] == OUTPUT_URI_LINEAGE_TOPOLOGY


# --- the list outcome; summary derives from the structure --------------------

def test_list_summary_is_written_from_the_node_set():
    matches = [
        {"urn": _ds("warehouse_a", "zone.orders"), "platforms": ["warehouse_a"]},
        {"urn": _ds("warehouse_a", "zone.customers"), "platforms": ["warehouse_a"]},
    ]
    res = build_trace_lineage_answer(asset_label="Sales", resolve=FOUND,
                                     platform_scope=SCOPE_WH, lineage_result=_result(matches, considered=40))
    assert res["outcome"] == OUTCOME_LIST
    sd = res["structured_data"]
    assert sd["match_count"] == 2
    assert sd["considered_count"] == 40
    # summary reports the count AND the names that are in the structure
    assert "2 warehouse_a table" in res["summary"]
    assert "orders" in res["summary"] and "customers" in res["summary"]
    # edgeless-because-filtered: valid degenerate topology
    assert sd["edges"] == [] and len(sd["nodes"]) == 2
    # sources carry the URNs for the left-bar
    assert [s["uri"] for s in res["sources"]] == [m["urn"] for m in matches]


def test_changing_the_structure_changes_the_summary():
    # This is the anti-contradiction property in one assertion: two different
    # match sets -> two different summaries. The summary cannot be stale w.r.t.
    # the structure because it is generated from it.
    one = build_trace_lineage_answer(asset_label="A", resolve=FOUND, platform_scope=SCOPE_WH,
        lineage_result=_result([{"urn": _ds("warehouse_a", "z.a"), "platforms": ["warehouse_a"]}]))
    three = build_trace_lineage_answer(asset_label="A", resolve=FOUND, platform_scope=SCOPE_WH,
        lineage_result=_result([{"urn": _ds("warehouse_a", f"z.t{i}"), "platforms": ["warehouse_a"]} for i in range(3)]))
    assert one["summary"] != three["summary"]
    assert "1 warehouse_a table" in one["summary"]
    assert "3 warehouse_a table" in three["summary"]


# --- the honest distinctions: six outcomes never conflated -------------------

def test_genuinely_none_is_distinct_from_walk_failure():
    none = build_trace_lineage_answer(asset_label="A", resolve=FOUND, platform_scope=SCOPE_WH,
                                      lineage_result=_result([], considered=12))
    err = build_trace_lineage_answer(asset_label="A", resolve=FOUND, platform_scope=SCOPE_WH,
                                     lineage_result={"error": "lineage_unavailable"})
    assert none["outcome"] == OUTCOME_NONE
    assert err["outcome"] == OUTCOME_LINEAGE_ERROR
    # both are edgeless, but they must NOT read the same
    assert none["summary"] != err["summary"]
    assert "examined 12" in none["summary"]           # a correct answer
    assert "retrieval failure" in err["summary"]      # a failure, said as one


def test_access_denied_walk_is_a_failure_not_none():
    res = build_trace_lineage_answer(asset_label="A", resolve=FOUND, platform_scope=SCOPE_WH,
                                     lineage_result={"access_denied": True, "matches": []})
    assert res["outcome"] == OUTCOME_LINEAGE_ERROR


def test_not_found_and_ambiguous_are_distinct_and_do_not_walk():
    nf = build_trace_lineage_answer(asset_label="Ghost", resolve={"outcome": "not_found"},
                                    platform_scope=SCOPE_WH, lineage_result=None)
    amb = build_trace_lineage_answer(asset_label="Common", resolve={"outcome": "ambiguous", "candidate_count": 4},
                                     platform_scope=SCOPE_WH, lineage_result=None)
    assert nf["outcome"] == OUTCOME_COULDNT_LOCATE
    assert amb["outcome"] == OUTCOME_AMBIGUOUS
    assert nf["summary"] != amb["summary"]
    assert "4" in amb["summary"]          # names the ambiguity count
    assert nf["structured_data"]["nodes"] == [] and amb["structured_data"]["nodes"] == []


def test_platform_mentioned_but_unrecognized_says_so():
    scope = {"platforms": [], "platform_mentioned": True, "unrecognized": ["snowflurry"]}
    res = build_trace_lineage_answer(asset_label="A", resolve=FOUND, platform_scope=scope,
                                     lineage_result=_result([]))
    assert res["outcome"] == OUTCOME_UNRECOGNIZED_PLATFORM
    assert "snowflurry" in res["summary"]
    assert "guessing" in res["summary"].lower()


def test_no_platform_mentioned_is_not_the_unrecognized_case():
    # The load-bearing distinction: absent constraint -> no filter, full lineage,
    # NOT the "unrecognized" say-so. platform_mentioned=False routes to a real walk.
    res = build_trace_lineage_answer(asset_label="A", resolve=FOUND, platform_scope=SCOPE_NONE,
        lineage_result=_result([{"urn": _ds("warehouse_a", "z.t"), "platforms": ["warehouse_a"]}]))
    assert res["outcome"] == OUTCOME_LIST
    assert "upstream table" in res["summary"]   # generic phrasing, no platform name


# --- audit + truncation honesty ---------------------------------------------

def test_resolved_urn_is_carried_for_audit():
    res = build_trace_lineage_answer(asset_label="A", resolve=FOUND, platform_scope=SCOPE_WH,
        lineage_result=_result([{"urn": _ds("warehouse_a", "z.t"), "platforms": ["warehouse_a"]}]))
    assert res["structured_data"]["resolved_urn"] == FOUND["urn"]


def test_truncation_is_surfaced_as_a_lower_bound():
    res = build_trace_lineage_answer(asset_label="A", resolve=FOUND, platform_scope=SCOPE_WH,
        lineage_result=_result([{"urn": _ds("warehouse_a", "z.t"), "platforms": ["warehouse_a"]}], truncated=True))
    assert res["structured_data"]["truncated"] is True
    assert "lower bound" in res["summary"]
