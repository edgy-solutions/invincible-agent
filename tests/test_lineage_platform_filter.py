"""Regression tests for platform-scoped lineage selection.

THE BUG THIS PINS
-----------------
A question of the form "which <platform> tables does <asset> depend on?"
was answered by pulling a large unfiltered lineage/search result set and
asking an LLM to pick the matching rows out of it. The model read a long,
repetitive list, missed the matching rows, and emitted a confident "none"
— contradicting the evidence attached to its own answer. Retrieval had
been correct; only the reading of it was wrong.

The structural properties that made it fail are reproduced below:

  * a large result set (~96 entities) relative to a tiny answer (3),
  * matches sitting LATE in traversal order (deep hops, not the head),
  * heavy near-duplication — the same logical table registered against
    several platforms, so rows look interchangeable while scanning.

FIXTURE IS AUTHORED, NEVER CAPTURED. Every name, platform slug and
identifier here is invented. A fixture is source code: it lives in the
repo forever and is read by everyone, so it carries STRUCTURE (counts,
depths, ordering, duplication) and never content from any real catalog.
The structure is what exercises the logic; real names would test nothing
extra and would leak.
"""
from __future__ import annotations

from agent_fleet.datahub_wrapper.lineage_filter import (
    LINEAGE_SCROLL_MAX_ENTITIES,
    build_lineage_result,
    dedupe_logical,
    dataset_name_of,
    filter_by_platforms,
    platform_of,
    summarize_platforms,
)

# Neutral platform slugs — the logic is slug-agnostic.
TARGET = "warehouse_a"       # the platform the question asks about
OTHERS = ["transform", "relational", "orchestrator", "warehouse_b"]


def _ds(platform: str, name: str, env: str = "PROD") -> str:
    return f"urn:li:dataset:(urn:li:dataPlatform:{platform},{name},{env})"


def _chart(n: int) -> str:
    return f"urn:li:chart:(bi_tool,{n})"


def _fixture():
    """~96 entities across hops 1-11; 3 TARGET rows at hops 8 and 11.

    Mirrors the measured shape: a wide middle (hops 5-8), non-dataset
    entities at hop 1, and the answer buried deep rather than at the head.
    """
    rows = []
    # hop 1: non-dataset entities (no platform segment at all)
    for i in range(5):
        rows.append({"urn": _chart(i), "degree": 1})
    # hops 2-4: a few rows, each logical table duplicated across platforms
    for hop in (2, 3, 4):
        for p in OTHERS[:2]:
            rows.append({"urn": _ds(p, f"zone_b.tbl_h{hop}"), "degree": hop})
    # hops 5-8: the wide middle, heavy duplication
    for hop in (5, 6, 7, 8):
        for idx in range(5):
            for p in OTHERS:
                rows.append({"urn": _ds(p, f"zone_c.tbl_h{hop}_{idx}"), "degree": hop})
    # the answer: 1 TARGET row at hop 8, 2 at hop 11 — deep, not at the head
    rows.append({"urn": _ds(TARGET, "zone_t.tbl_target_one"), "degree": 8})
    for hop in (9, 10):
        for idx in range(2):
            rows.append({"urn": _ds(OTHERS[0], f"zone_d.tbl_h{hop}_{idx}"), "degree": hop})
    rows.append({"urn": _ds(TARGET, "zone_t.tbl_target_two"), "degree": 11})
    rows.append({"urn": _ds(TARGET, "zone_t.tbl_target_three"), "degree": 11})
    return rows


FIXTURE = _fixture()


# ---------------------------------------------------------------------------
# URN parsing — platform classification is a pure string op, no fetch, no LLM
# ---------------------------------------------------------------------------

def test_platform_of_extracts_slug():
    assert platform_of(_ds(TARGET, "z.t")) == TARGET
    assert platform_of(_ds("Transform", "z.t")) == "transform"  # lowercased


def test_platform_of_is_empty_for_non_dataset_entities():
    # Charts/dashboards have no dataPlatform segment. Filtering by platform
    # therefore drops them, which is correct: "which tables feed this" is
    # not a question about charts.
    assert platform_of(_chart(1)) == ""
    assert platform_of("") == ""


def test_dataset_name_is_platform_independent():
    a = _ds(TARGET, "zone.same_table")
    b = _ds("relational", "zone.same_table")
    assert dataset_name_of(a) == dataset_name_of(b) == "zone.same_table"


# ---------------------------------------------------------------------------
# THE REGRESSION: the answer is findable by code where reading it failed
# ---------------------------------------------------------------------------

def test_the_answer_is_buried_late_in_a_large_set():
    """Guards the fixture itself: if this stops holding, the fixture no
    longer reproduces the conditions that broke the LLM-reading approach
    and the tests below stop proving anything."""
    assert len(FIXTURE) > 80, "answer must be a needle in a large set"
    target_hops = sorted(
        r["degree"] for r in FIXTURE if platform_of(r["urn"]) == TARGET
    )
    assert target_hops == [8, 11, 11], "matches must sit deep, not at the head"


def test_filter_returns_exactly_the_target_rows():
    got = filter_by_platforms(FIXTURE, [TARGET])
    assert len(got) == 3
    assert {platform_of(r["urn"]) for r in got} == {TARGET}
    assert sorted(r["degree"] for r in got) == [8, 11, 11]


def test_filter_accepts_slug_or_full_platform_urn():
    by_slug = filter_by_platforms(FIXTURE, [TARGET])
    by_urn = filter_by_platforms(FIXTURE, [f"urn:li:dataPlatform:{TARGET}"])
    assert [r["urn"] for r in by_slug] == [r["urn"] for r in by_urn]


def test_empty_platform_list_means_no_filter_not_no_results():
    # An absent constraint must never silently become an
    # everything-excluded one.
    assert len(filter_by_platforms(FIXTURE, [])) == len(FIXTURE)
    assert len(filter_by_platforms(FIXTURE, None)) == len(FIXTURE)


def test_filtering_preserves_traversal_order():
    got = filter_by_platforms(FIXTURE, [TARGET])
    assert [r["degree"] for r in got] == [8, 11, 11]


# ---------------------------------------------------------------------------
# Dedupe — one logical table registered against several platforms
# ---------------------------------------------------------------------------

def test_dedupe_collapses_same_table_across_platforms():
    rows = [{"urn": _ds(p, "zone.shared_table"), "degree": 5} for p in OTHERS]
    got = dedupe_logical(rows)
    assert len(got) == 1
    assert got[0]["platforms"] == sorted(OTHERS)
    assert len(got[0]["urns"]) == len(OTHERS)


def test_dedupe_keeps_distinct_tables_distinct():
    rows = [
        {"urn": _ds("relational", "zone.table_one"), "degree": 5},
        {"urn": _ds("relational", "zone.table_two"), "degree": 5},
    ]
    assert len(dedupe_logical(rows)) == 2


def test_dedupe_keeps_first_occurrence_as_representative():
    rows = [
        {"urn": _ds("transform", "zone.shared"), "degree": 3},
        {"urn": _ds("relational", "zone.shared"), "degree": 9},
    ]
    got = dedupe_logical(rows)
    assert len(got) == 1 and got[0]["degree"] == 3


def test_dedupe_never_merges_non_dataset_entities():
    rows = [{"urn": _chart(1), "degree": 1}, {"urn": _chart(2), "degree": 1}]
    assert len(dedupe_logical(rows)) == 2


# ---------------------------------------------------------------------------
# The structured result the narrative is written FROM
# ---------------------------------------------------------------------------

def test_result_carries_the_selected_set_and_the_considered_count():
    res = build_lineage_result(FIXTURE, platforms=[TARGET])
    assert res["match_count"] == 3
    assert res["considered_count"] == len(FIXTURE)
    assert res["platforms_requested"] == [TARGET]
    assert res["truncated"] is False
    assert "truncated_at" not in res


def test_zero_matches_is_an_honest_empty_not_an_error():
    res = build_lineage_result(FIXTURE, platforms=["platform_not_present"])
    assert res["match_count"] == 0 and res["matches"] == []
    # The histogram still reports what WAS considered, so "none" is
    # distinguishable from "nothing was looked at".
    assert res["considered_count"] == len(FIXTURE)
    assert res["platform_histogram"]


def test_truncation_reports_what_bound_and_at_what_number():
    # A truncation flag with no ceiling value tells an operator only that
    # something bound. It must say WHICH bound and AT WHAT NUMBER.
    res = build_lineage_result(FIXTURE, platforms=[TARGET], truncated=True)
    assert res["truncated"] is True
    assert res["truncated_at"] == LINEAGE_SCROLL_MAX_ENTITIES
    assert "LOWER BOUND" in res["truncation_note"]


def test_histogram_leaks_no_identifiers():
    hist = summarize_platforms(FIXTURE)
    assert hist[TARGET] == 3
    # Keys are platform slugs only — safe to log or paste.
    assert all(":" not in k for k in hist)
