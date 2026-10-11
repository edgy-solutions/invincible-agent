"""`mesh:whichPartsDoesThisNoticeAffect`: a notice with NO parts is a named refusal, and a notice with
MANY parts is answered one page at a time.

WHY. An `ok` answer with `parts: []` reads as "checked, none"; the fleet's refusal envelope
(`refused: True`, `outcome`, `reason`) is what presentation keys on, so a known notice naming no
part now refuses as `no_affected_parts`, distinct from `unknown_notice`. And the statement used to
return every mpn: a notice with thousands of parts shipped them all. The page is cut IN THE STORE
(`ORDER BY mpn`, then `[$offset..($offset + $limit)]`), and the shaper says which range of how many.

THE DOUBLE PAGES LIKE THE STORE: `_PagingDriver` holds ALL the mpns, sorts them, and slices by the
`offset`/`limit` parameters the statement was run with, returning `total` beside the page. So an
arm that passes the wrong parameters gets the wrong page, not a lucky one.
"""
from __future__ import annotations

import re

import pytest

from agent_fleet.ontology_service import notice_parts as np_mod
from tests.test_notice_parts_provenance import NOTICE, _Record, _route, _row
from tests.test_notice_parts_renders_as_instances_by_property import ARCH, _project

PAGE = np_mod.NOTICE_PARTS_PAGE_SIZE


def _mpns(n):
    return [f"P{i:04d}" for i in range(n)]


class _PagingDriver:
    """Answers the way the statement does: sorted, sliced by the run's own offset/limit."""

    def __init__(self, mpns, over_return=0):
        self.all = sorted(mpns)
        self.over_return = over_return
        self.modes: list = []
        self.runs: list = []

    def session(self, **kw):
        self.modes.append(kw.get("default_access_mode"))
        driver = self

        class _S:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def run(self, cypher, params):
                driver.runs.append((cypher, dict(params)))
                off, lim = params["offset"], params["limit"]
                page = driver.all[off:off + lim + driver.over_return]
                return [_Record(_row(mpns=page, total=len(driver.all)))]
        return _S()


def _read(n, offset=0, **kw):
    d = _PagingDriver(_mpns(n), **kw)
    return d, np_mod.read_notice_parts(d, NOTICE, offset)


# -- no parts is a named refusal -------------------------------------------------------------

def test_A_KNOWN_NOTICE_WITH_NO_PARTS_IS_THE_NAMED_REFUSAL_NO_AFFECTED_PARTS():
    """The envelope presentation keys on: refused + outcome + reason, with empty parts/sources."""
    ans = np_mod.read_notice_parts(_PagingDriver([]), NOTICE)
    assert ans["refused"] is True and ans["outcome"] == "refused"
    assert (ans["status"], ans["reason"]) == ("refused", "no_affected_parts")
    assert ans["notice_id"] == NOTICE and ans["verb"] == np_mod.VERB
    assert ans["parts"] == [] and ans["sources"] == []
    assert NOTICE in ans["message"] and "no affected part" in ans["message"]


def test_CONTROL_AN_UNKNOWN_NOTICE_IS_A_DIFFERENT_REFUSAL_REASON():
    """The two differ in ONE thing, whether the graph returns the notice row. The reasons must
    differ, or "no parts" would collapse into "no such notice"."""
    ans = np_mod.notice_parts([], "PCN-NOPE")
    assert ans["refused"] is True and ans["outcome"] == "refused"
    assert ans["reason"] == "unknown_notice"
    assert ans["reason"] != "no_affected_parts"


@pytest.mark.parametrize("answer", [
    np_mod.notice_parts([], ""),
    np_mod.notice_parts([], "PCN-NOPE"),
    np_mod.notice_parts([_row(mpns=[])], NOTICE),
    np_mod.read_notice_parts(_PagingDriver([]), NOTICE, -1),
    np_mod.notice_parts([_row(mpns=_mpns(5))], NOTICE, 9),
], ids=["notice_required", "unknown_notice", "no_affected_parts", "bad_offset", "page_out_of_range"])
def test_EVERY_REFUSAL_IN_THE_MODULE_SPEAKS_THE_ONE_ENVELOPE(answer):
    assert answer["refused"] is True and answer["outcome"] == "refused"
    assert answer["status"] == "refused" and answer["reason"]
    assert answer["verb"] == np_mod.VERB and answer["message"]
    assert answer["parts"] == [] and answer["sources"] == []


# -- paging ----------------------------------------------------------------------------------

def test_250_PARTS_ANSWER_THE_FIRST_100_TRUNCATED_AND_NAME_THE_NEXT_PAGE():
    d, ans = _read(250)
    assert d.runs[0][1]["offset"] == 0 and d.runs[0][1]["limit"] == PAGE
    assert ans["status"] == "ok" and ans["count"] == 100
    assert [p["mpn"] for p in ans["parts"]] == _mpns(250)[:100]
    assert ans["total_available"] == 250 and ans["completeness"] == "truncated"
    assert ans["offset"] == 0 and ans["next_offset"] == 100
    assert len(ans["sources"]) == 100 and len(ans["rows"]) == 100
    assert "parts 1–100 of 250" in ans["title"] and "offset = 100" in ans["title"]
    assert "parts 1–100 of 250" in ans["message"] and "offset = 100" in ans["message"]


def test_THE_LAST_PAGE_AT_OFFSET_200_IS_THE_REMAINING_50_AND_COMPLETE():
    d, ans = _read(250, offset=200)
    assert d.runs[0][1]["offset"] == 200
    assert ans["count"] == 50 and [p["mpn"] for p in ans["parts"]] == _mpns(250)[200:]
    assert ans["completeness"] == "complete" and ans["next_offset"] is None
    assert ans["offset"] == 200 and ans["total_available"] == 250
    assert "parts 201–250 of 250" in ans["message"]


def test_BOUNDARY_EXACTLY_100_IS_COMPLETE_AND_101_IS_TRUNCATED():
    _, exact = _read(100)
    assert exact["count"] == 100 and exact["completeness"] == "complete"
    assert exact["next_offset"] is None
    assert exact["title"] == f"Parts affected by {NOTICE}"  # a complete single page keeps its title
    _, over = _read(101)
    assert over["count"] == 100 and over["completeness"] == "truncated"
    assert over["next_offset"] == 100 and over["total_available"] == 101


def test_A_STORE_THAT_OVER_RETURNS_IS_CUT_TO_THE_PAGE_IN_PYTHON():
    """The statement slices; this is the defence if a store hands back more than `limit`."""
    d, ans = _read(150, over_return=50)
    assert len(d.runs[0][0]) and ans["count"] == 100
    assert len(ans["sources"]) == 100 and len(ans["parts"]) == 100 and len(ans["rows"]) == 100
    assert ans["completeness"] == "truncated" and ans["next_offset"] == 100


def test_AN_OFFSET_PAST_THE_END_IS_PAGE_OUT_OF_RANGE_CARRYING_THE_TOTAL():
    _, ans = _read(250, offset=250)
    assert ans["refused"] is True and ans["reason"] == "page_out_of_range"
    assert ans["total_available"] == 250 and ans["parts"] == [] and ans["sources"] == []


@pytest.mark.parametrize("bad", [-1, "x", True, 1.5, "-1", "1.5", [1]],
                         ids=["negative", "word", "bool", "fraction", "neg-str", "frac-str", "list"])
def test_A_BAD_OFFSET_IS_REFUSED_BEFORE_THE_STORE_IS_READ(bad):
    d = _PagingDriver(_mpns(250))
    ans = np_mod.read_notice_parts(d, NOTICE, bad)
    assert ans["refused"] is True and ans["reason"] == "bad_offset"
    assert d.runs == [] and d.modes == []


@pytest.mark.parametrize("good,want", [(0, 0), (100, 100), ("100", 100), (None, 0), (100.0, 100)])
def test_A_WHOLE_NUMBER_OFFSET_IS_ACCEPTED(good, want):
    d = _PagingDriver(_mpns(250))
    ans = np_mod.read_notice_parts(d, NOTICE, good)
    assert ans["status"] == "ok" and d.runs[0][1]["offset"] == want


# -- the statement ---------------------------------------------------------------------------

def test_THE_STATEMENT_ORDERS_THEN_COLLECTS_THEN_SLICES_WITH_PARAMETERS():
    """Sealed on the text. The order is before `collect`, so the page is stable across calls; the
    slice and the total are in the statement, so the cut is made in the store."""
    c = np_mod.NOTICE_PARTS_CYPHER
    assert re.search(r"ORDER BY mpn\s+WITH n, collect\(DISTINCT mpn\) AS all_mpns", c)
    assert "all_mpns[$offset..($offset + $limit)] AS mpns" in c
    assert "size(all_mpns) AS total" in c
    assert not re.search(r"\b(CREATE|MERGE|SET|DELETE|REMOVE)\b", c)
    assert "LIMIT" not in c


def test_OFFSET_AND_LIMIT_ARE_RUN_PARAMETERS_NEVER_FORMATTED_INTO_THE_TEXT():
    d, _ = _read(250, offset=200)
    cypher, params = d.runs[0]
    assert cypher == np_mod.NOTICE_PARTS_CYPHER
    assert params == {"notice_id": NOTICE, "offset": 200, "limit": PAGE}
    assert "200" not in cypher and "$offset" in cypher and "$limit" in cypher


# -- the route -------------------------------------------------------------------------------

def test_THE_ROUTE_CARRIES_PARAMS_OFFSET_TO_THE_STORE(monkeypatch):
    d = _PagingDriver(_mpns(250))
    r = _route(monkeypatch, d, {"entitled_domains": ["SUSTAINMENT"],
                                "params": {"notice_id": NOTICE, "offset": 100}})
    assert r.status_code == 200, r.text
    assert d.runs[0][1]["offset"] == 100
    body = r.json()
    assert body["offset"] == 100 and body["next_offset"] == 200 and body["count"] == 100


def test_THE_ROUTE_REFUSES_A_BAD_OFFSET_WITHOUT_READING(monkeypatch):
    d = _PagingDriver(_mpns(250))
    r = _route(monkeypatch, d, {"entitled_domains": ["SUSTAINMENT"],
                                "params": {"notice_id": NOTICE, "offset": -5}})
    assert r.status_code == 200 and r.json()["reason"] == "bad_offset" and d.runs == []


def test_THE_DECLARED_SLOTS_DO_NOT_GAIN_AN_OFFSET():
    """`offset` is a paging control read from `params`, not a slot the planner fills."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "agent_fleet/ontology_service/main.py").read_text(
        encoding="utf-8")
    i = src.index("_register_notice_parts")
    j = src.index("mr.when_stores_answer", i)
    assert "offset" not in src[i:j].replace("next_offset", "").replace("params.offset", "")


# -- presentation ----------------------------------------------------------------------------

def test_THE_PAGED_ANSWER_STILL_PROJECTS_TO_INSTANCES_BY_PROPERTY_ROWS():
    _, ans = _read(250)
    got = _project(ans)
    assert got is not None, ARCH
    assert len(got["rows"]) == 100
    assert "parts 1–100 of 250" in got["title"]
