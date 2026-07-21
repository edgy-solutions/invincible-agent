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
    humanize_urn_label,
    resolve_urn_outcome,
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


# --- the URN-resolution floor: three outcomes, never a silent pick ----------

def _cand(name, n):
    return {"name": name, "urn": f"urn:li:dashboard:(bi,{n})"}


def test_resolve_no_candidates_is_not_found():
    r = resolve_urn_outcome("anything", [])
    assert r["outcome"] == "not_found" and r["urn"] is None


def test_resolve_single_candidate_is_found():
    # The asked name carries descriptors the catalog name omits — containment
    # still resolves to the lone candidate.
    r = resolve_urn_outcome("Quarterly Sales Overview Dashboard", [_cand("Sales Overview", 19)])
    assert r["outcome"] == "found"
    assert r["urn"] == "urn:li:dashboard:(bi,19)"


def test_resolve_clear_best_is_found():
    # one strong containment match, others unrelated
    cands = [_cand("Sales Overview", 1), _cand("Quarterly Sales Dashboard", 2), _cand("Weather", 3)]
    r = resolve_urn_outcome("Quarterly Sales Dashboard", cands)
    assert r["outcome"] == "found" and r["urn"].endswith(",2)")


def test_resolve_near_equal_is_ambiguous_not_a_silent_pick():
    # two identically-named assets — must NOT pick one
    cands = [_cand("Orders", 1), _cand("Orders", 2)]
    r = resolve_urn_outcome("Orders", cands)
    assert r["outcome"] == "ambiguous" and r["urn"] is None
    assert r["candidate_count"] >= 2


def test_resolve_nothing_clears_the_floor_is_ambiguous():
    # the asked name matches none of the candidates well
    cands = [_cand("Weather Map", 1), _cand("Fleet Status", 2)]
    r = resolve_urn_outcome("customer revenue attribution", cands)
    assert r["outcome"] == "ambiguous" and r["urn"] is None


def test_resolve_lone_candidate_is_found_even_on_poor_name_score():
    # THE Customer 360 bug: the asked "name" was actually a URN, so it scored
    # below min_score against the candidate's display name. With exactly one
    # candidate there is nothing to be ambiguous BETWEEN — take it.
    cands = [_cand("Customer 360", 7)]
    r = resolve_urn_outcome("urn:li:dashboard:(superset,customer_360)", cands)
    assert r["outcome"] == "found"
    assert r["urn"] == "urn:li:dashboard:(bi,7)"
    assert r["candidate_count"] == 1


# --- humanize_urn_label: readable prose from a resolved URN ------------------

def test_humanize_dashboard_urn():
    assert humanize_urn_label("urn:li:dashboard:(superset,customer_360)") == "Customer 360"


def test_humanize_drops_env_marker_and_takes_specific_segment():
    urn = "urn:li:dataset:(urn:li:dataPlatform:snowflake,bronze.sales.orders_fact,PROD)"
    assert humanize_urn_label(urn) == "Orders Fact"


def test_humanize_handles_plain_token_and_empty():
    assert humanize_urn_label("not-a-urn") == "Not A Urn"
    assert humanize_urn_label("") == ""


def test_no_instance_fails_honestly_without_echoing_the_prompt():
    # THE fallback bug: when the router resolved no instance, the branch used
    # to search task.task_description (the whole question) -> "cannot locate
    # '<entire prompt>'". no_instance must NOT echo any searched string.
    res = build_trace_lineage_answer(asset_label="", resolve={"outcome": "no_instance"},
                                     platform_scope=SCOPE_WH, lineage_result=None)
    assert res["outcome"] == OUTCOME_COULDNT_LOCATE
    assert "couldn't determine which specific asset" in res["summary"]
    assert "cannot locate" not in res["summary"].lower()
    assert res["structured_data"]["nodes"] == []
