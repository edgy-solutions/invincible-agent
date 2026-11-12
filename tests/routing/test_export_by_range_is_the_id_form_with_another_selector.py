"""POST /ingest/export/notices by `range: {from, to}` (Job 27, architect ruling; targets 0.4.86).

The range form is the id form with a different SELECTOR and nothing else: it resolves a set of
notice ids, then runs the same gates, the same `_export_preflight`, the same 422/503, the same
file and the same audit record. Decisions sealed here (one case each, each with a control):

  1. SELECTION  exactly one of `notice_ids` / `range`; both or neither is 422 `export_selection_invalid`.
  2. BOUNDS     YYYY-MM-DD UTC days, both ends inclusive, from <= to, at most 92 days.
  3. TIMESTAMP  the notice's RECEIPT time (`created_at`): not `updated_at`, not the promotion time.
  4. SIZE       at most 500 notices in scope and 5000 scanned: 422 `export_range_too_large`; an
                empty range is 200 (`notices: 0`, a header-only/empty file, as the GET batch does).
  5. DOMAIN     another domain's notices are dropped silently: a range never enumerates them.
  6. CORE       the same notices by ids and by range: the same unexportable list, the same file.

Run: .venv/Scripts/python -I -m pytest -c pyproject.toml --rootdir=. -q tests/routing/test_export_by_range_is_the_id_form_with_another_selector.py
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from src.iagent import gateway  # noqa: E402
from src.iagent import human_tasks as ht  # noqa: E402
from src.iagent import ingest_status as ist  # noqa: E402
from tests.routing.test_a_review_export_resolves_every_column_or_refuses import (  # noqa: E402
    DOM_B, REV_C, ROOT, Ledger, _iid, _world,
)
from tests.routing.test_the_export_profile_server_is_sealed import (  # noqa: E402
    BATCH, _cleanup, _door, _states_line, _yaml, built,  # noqa: F401  (fixtures)
)

REVIEW = ist.REVIEW


def _ms(y, m, d, hh=0, mm=0, ss=0, ms=0):
    return int(datetime(y, m, d, hh, mm, ss, tzinfo=timezone.utc).timestamp() * 1000) + ms


DAY = _ms(2026, 11, 3)                       # 2026-11-03T00:00:00Z
RANGE = {"from": "2026-11-03", "to": "2026-11-05"}
MID = _ms(2026, 11, 4, 12)                   # inside RANGE


def _post(body):
    with TestClient(gateway.app) as c:
        return c.post("/ingest/export/notices", json=body)


def _range_world(monkeypatch, tmp_path, specs, *, extra="", grants=None, scan=None):
    """One notice per spec (a dict of row overrides, `created_at` among them), numbered from 1.
    `ist.list_by_created` is a double that applies the store's contract over those rows
    (`start <= created_at < end`, oldest first, `limit`); `calls` records what it was asked."""
    worlds = [_world(i + 1, REV_C, **{"created_at": MID, **spec}) for i, spec in enumerate(specs)]
    asks = _door(monkeypatch, tmp_path, grants=grants if grants is not None
                 else {BATCH, "can_export:t"}, worlds=worlds,
                 profiles={"t": _yaml("t", version=7, extra=extra)})
    rows = [w[0] for w in worlds]
    calls: list = []

    def list_by_created(start_ms, end_ms, limit):
        calls.append((start_ms, end_ms, limit))
        hit = sorted((r for r in rows if r["kind"] != ist.EVENT and start_ms <= r["created_at"] < end_ms),
                     key=lambda r: (r["created_at"], r["id"]))
        return [{"id": r["id"], "review_generation": 0, "created_at": r["created_at"]}
                for r in hit[:limit]]

    monkeypatch.setattr(ist, "list_by_created", list_by_created)
    for r in rows:                           # a notice not promoted has no record: its task names it
        if r["status"] != ist.PROMOTED:
            Ledger.records[r["id"]] = None
    if any(r["status"] != ist.PROMOTED for r in rows):
        monkeypatch.setattr(ht, "get_task_open_state",
                            lambda t: {"audience": "document_promotion:maintenance", "open": True})
    if scan is not None:
        monkeypatch.setattr(gateway, "_EXPORT_RANGE_SCAN", scan)
    return calls, asks


def _bad(r):
    return r.json()["detail"]["unexportable"]


# 1. selection --------------------------------------------------------------------------------

def test_1_both_or_neither_is_refused_and_each_alone_is_admitted(monkeypatch, tmp_path, built):
    calls, _ = _range_world(monkeypatch, tmp_path, [{}])
    for body in ({"notice_ids": [_iid(1)], "range": RANGE, "profile": "t"}, {"profile": "t"}):
        r = _post(body)
        assert r.status_code == 422 and r.json()["detail"]["error"] == "export_selection_invalid", body
    assert calls == [] and built["render"] == 0 and built["records"] == []   # nothing read, built
    assert _post({"notice_ids": [_iid(1)], "profile": "t"}).status_code == 200      # control: ids
    assert _post({"range": RANGE, "profile": "t"}).status_code == 200               # control: range


def test_1_an_empty_id_list_is_still_the_id_forms_own_refusal(monkeypatch, tmp_path, built):
    _range_world(monkeypatch, tmp_path, [{}])
    r = _post({"notice_ids": [], "profile": "t"})
    assert r.status_code == 422 and r.json()["detail"]["error"] == "export_notice_ids_invalid"


def test_1_a_range_takes_no_other_key(monkeypatch, tmp_path, built):
    _range_world(monkeypatch, tmp_path, [{}])
    for rng in ({**RANGE, "field": "updated_at"}, {"from": RANGE["from"]}, {"to": RANGE["to"]}):
        assert _post({"range": rng, "profile": "t"}).status_code == 422, rng
    assert _post({"range": RANGE, "profile": "t"}).status_code == 200                # control


# 2. bounds -----------------------------------------------------------------------------------

@pytest.mark.parametrize("rng", [
    {"from": "2026-11-05", "to": "2026-11-03"}, {"from": "2026-13-01", "to": "2026-13-02"},
    {"from": "2026-1-3", "to": "2026-11-05"}, {"from": "2026-11-03T00:00:00Z", "to": "2026-11-05"},
    {"from": "", "to": ""}])
def test_2_a_malformed_or_inverted_range_is_export_range_invalid(monkeypatch, tmp_path, built, rng):
    calls, _ = _range_world(monkeypatch, tmp_path, [{}])
    r = _post({"range": rng, "profile": "t"})
    assert r.status_code == 422 and r.json()["detail"]["error"] == "export_range_invalid"
    assert calls == []


def test_2_the_range_is_capped_at_92_days_both_ends_counted(monkeypatch, tmp_path, built):
    calls, _ = _range_world(monkeypatch, tmp_path, [{}])
    r = _post({"range": {"from": "2026-01-01", "to": "2026-04-03"}, "profile": "t"})   # 93 days
    assert r.status_code == 422 and r.json()["detail"]["error"] == "export_range_too_large"
    assert calls == []
    assert _post({"range": {"from": "2026-01-01", "to": "2026-04-02"}, "profile": "t",       # 92: control
                  "check_only": True}).status_code == 200


def test_2_both_ends_are_inclusive_and_the_day_is_utc(monkeypatch, tmp_path, built):
    edges = {  # notice -> created_at
        1: DAY - 1,                            # the last ms of the day BEFORE `from`: out
        2: DAY,                                # `from` 00:00:00.000Z: in
        3: _ms(2026, 11, 5, 23, 59, 59, 999),  # `to` 23:59:59.999Z: in
        4: _ms(2026, 11, 6),                   # the day after `to`: out
    }
    calls, _ = _range_world(monkeypatch, tmp_path, [{"created_at": edges[i]} for i in (1, 2, 3, 4)])
    r = _post({"range": RANGE, "profile": "t", "check_only": True})
    assert r.status_code == 200 and r.json()["notice_ids"] == [_iid(2), _iid(3)]
    assert calls[0][:2] == (DAY, _ms(2026, 11, 6))                       # half-open [from, to+1d)
    wide = _post({"range": {"from": "2026-11-02", "to": "2026-11-06"}, "profile": "t",
                  "check_only": True})                                    # control: widen both ends
    assert wide.json()["notice_ids"] == [_iid(i) for i in (1, 2, 3, 4)]


# 3. timestamp --------------------------------------------------------------------------------

def test_3_the_range_reads_receipt_time_not_updated_at_and_not_promotion(
        monkeypatch, tmp_path, built):
    out = _ms(2026, 12, 25)
    _range_world(monkeypatch, tmp_path, [
        {"created_at": MID, "updated_at": out},      # received in range, moved later: IN
        {"created_at": out, "updated_at": MID}])     # received later, touched in range: OUT
    Ledger.between = [(_iid(2), MID)]                # the ledger would say notice 2 was promoted in range
    Ledger.calls.clear()
    r = _post({"range": RANGE, "profile": "t", "check_only": True})
    assert r.json()["notice_ids"] == [_iid(1)]
    assert Ledger.calls == []                        # promoted_between was never asked


def test_3_a_notice_in_review_is_selected_and_the_profile_decides_its_fate(
        monkeypatch, tmp_path, built):
    _range_world(monkeypatch, tmp_path, [{"status": ist.PROMOTED}, {"status": REVIEW}])
    r = _post({"range": RANGE, "profile": "t"})                                # default [promoted]
    assert r.status_code == 422
    assert _bad(r) == [{"notice_id": _iid(2), "reason": "state_not_exportable", "state": REVIEW}]


def test_3_control_the_same_range_with_the_state_listed_builds_the_file(
        monkeypatch, tmp_path, built):
    _range_world(monkeypatch, tmp_path, [{"status": ist.PROMOTED}, {"status": REVIEW}],
                 extra=_states_line(REVIEW, ist.PROMOTED))
    r = _post({"range": RANGE, "profile": "t"})
    assert r.status_code == 200 and built["render"] == 1


# 4. size and the empty range -----------------------------------------------------------------

def test_4_more_than_the_notice_cap_in_scope_is_too_large_even_for_check_only(
        monkeypatch, tmp_path, built):
    _range_world(monkeypatch, tmp_path, [{}, {}, {}])
    monkeypatch.setattr(gateway, "_EXPORT_MAX_NOTICES", 2)
    for body in ({"range": RANGE, "profile": "t"}, {"range": RANGE, "profile": "t", "check_only": True}):
        r = _post(body)
        assert r.status_code == 422 and r.json()["detail"]["error"] == "export_range_too_large", body
    assert built["render"] == 0
    monkeypatch.setattr(gateway, "_EXPORT_MAX_NOTICES", 3)                    # control: at the cap
    assert _post({"range": RANGE, "profile": "t"}).status_code == 200


def test_4_the_scan_cap_counts_other_domains_receipts_too(monkeypatch, tmp_path, built):
    calls, _ = _range_world(monkeypatch, tmp_path, [{}, {}, {}], scan=2)
    Ledger.domains = {_iid(2): DOM_B, _iid(3): DOM_B}      # only ONE notice is in the caller's scope
    r = _post({"range": RANGE, "profile": "t", "check_only": True})
    assert r.status_code == 422 and r.json()["detail"]["error"] == "export_range_too_large"
    assert calls[0][2] == 3                                # the store was asked for scan + 1
    monkeypatch.setattr(gateway, "_EXPORT_RANGE_SCAN", 3)  # control: at the scan cap
    assert _post({"range": RANGE, "profile": "t", "check_only": True}).status_code == 200


def test_4_an_empty_range_is_200_with_nothing_unexportable_and_a_file_of_no_rows(
        monkeypatch, tmp_path, built):
    _range_world(monkeypatch, tmp_path, [{"created_at": _ms(2026, 1, 1)}])
    c = _post({"range": RANGE, "profile": "t", "check_only": True})
    assert c.status_code == 200 and c.json()["notices"] == 0 and c.json()["unexportable"] == []
    assert c.json()["notice_ids"] == []
    r = _post({"range": RANGE, "profile": "t"})
    assert r.status_code == 200 and r.json()["rows"] == [] and r.json()["notices"] == 0
    assert built["records"][0]["notice_ids"] == [] and built["records"][0]["range"]["from"] == RANGE["from"]


# 5. domain: no enumeration -------------------------------------------------------------------

def test_5_another_domains_notice_is_neither_listed_nor_counted(monkeypatch, tmp_path, built):
    _range_world(monkeypatch, tmp_path, [{}, {}, {"content_kind": "other-kind"}],
                 extra="accepts: [pcn]\n")
    Ledger.domains = {_iid(2): DOM_B, _iid(3): DOM_B}
    r = _post({"range": RANGE, "profile": "t", "check_only": True})
    assert r.status_code == 200 and r.json()["notice_ids"] == [_iid(1)] and r.json()["notices"] == 1
    assert r.json()["unexportable"] == []
    for n in (2, 3):                                       # in neither the body nor the 422 form
        assert _iid(n) not in r.text
    Ledger.domains = {_iid(2): DOM_B}                      # control: notice 3 in scope is reported
    r = _post({"range": RANGE, "profile": "t", "check_only": True})
    assert r.json()["unexportable"] == [{"notice_id": _iid(3), "reason": "kind_not_accepted"}]
    assert _iid(2) not in r.text


def test_5_a_caller_with_no_cell_domains_reads_nothing(monkeypatch, tmp_path, built):
    calls, _ = _range_world(monkeypatch, tmp_path, [{}])
    Ledger.domains = {_iid(1): DOM_B}
    r = _post({"range": RANGE, "profile": "t", "check_only": True})
    assert r.json()["notice_ids"] == []


# 6. the core control: ids and range are one selection ----------------------------------------

def test_6_the_same_notices_by_ids_and_by_range_give_the_same_unexportable_list(
        monkeypatch, tmp_path, built):
    _range_world(monkeypatch, tmp_path, [
        {}, {}, {"content_kind": "other-kind"}, {"status": REVIEW}, {}], extra="accepts: [pcn]\n")
    Ledger.domains = {_iid(5): DOM_B}
    in_scope = [_iid(i) for i in (1, 2, 3, 4)]
    by_ids = _post({"notice_ids": in_scope, "profile": "t"})
    by_range = _post({"range": RANGE, "profile": "t"})
    assert by_ids.status_code == by_range.status_code == 422
    assert _bad(by_ids) == _bad(by_range) and len(_bad(by_ids)) == 2
    c_ids = _post({"notice_ids": in_scope, "profile": "t", "check_only": True}).json()
    c_rng = _post({"range": RANGE, "profile": "t", "check_only": True}).json()
    assert c_ids["unexportable"] == c_rng["unexportable"] and c_ids["notices"] == c_rng["notices"]
    assert built["render"] == 0


def test_6_the_same_notices_by_ids_and_by_range_give_the_same_file(monkeypatch, tmp_path, built):
    _range_world(monkeypatch, tmp_path, [{}, {}, {}, {}])
    Ledger.domains = {_iid(4): DOM_B}
    by_ids = _post({"notice_ids": [_iid(1), _iid(2), _iid(3)], "profile": "t"})
    by_range = _post({"range": RANGE, "profile": "t"})
    assert by_ids.status_code == by_range.status_code == 200
    assert by_ids.content == by_range.content and len(by_ids.content) > 0
    assert by_ids.headers["content-disposition"] == by_range.headers["content-disposition"]
    ids_rec, rng_rec = built["records"]
    assert ids_rec["notice_ids"] == rng_rec["notice_ids"]
    assert "range" not in ids_rec                                        # control: ids form
    assert rng_rec["range"] == {"from": "2026-11-03", "to": "2026-11-05", "field": "created_at"}
    assert {k: v for k, v in rng_rec.items() if k != "range"} == ids_rec  # nothing else differs


# 7. gates and faults, unchanged --------------------------------------------------------------

@pytest.mark.parametrize("grants", [{"can_export:t"}, {BATCH}, set()])
def test_7_each_gate_refuses_the_range_before_the_store_is_read(
        monkeypatch, tmp_path, built, grants):
    calls, _ = _range_world(monkeypatch, tmp_path, [{}], grants=grants)
    r = _post({"range": RANGE, "profile": "t", "check_only": True})
    assert r.status_code == 403, r.text
    assert calls == [] and built["records"] == []
    r = _post({"notice_ids": [_iid(1)], "profile": "t", "check_only": True})   # the id form: the same
    assert r.status_code == 403


def test_7_a_task_store_fault_is_503_not_a_reason(monkeypatch, tmp_path, built):
    _range_world(monkeypatch, tmp_path, [{"status": REVIEW}], extra=_states_line(REVIEW))

    def boom(t):
        raise RuntimeError("down")

    monkeypatch.setattr(ht, "get_task_open_state", boom)
    r = _post({"range": RANGE, "profile": "t", "check_only": True})
    assert r.status_code == 503 and r.json()["detail"]["error"] == "review_task_unreachable"
    assert built["render"] == 0 and built["records"] == []


def test_7_an_ingest_store_fault_is_503(monkeypatch, tmp_path, built):
    _range_world(monkeypatch, tmp_path, [{}])

    def boom(*a):
        raise RuntimeError("down")

    ok = _post({"range": RANGE, "profile": "t", "check_only": True})
    assert ok.status_code == 200                                              # control
    monkeypatch.setattr(ist, "list_by_created", boom)
    r = _post({"range": RANGE, "profile": "t", "check_only": True})
    assert r.status_code == 503 and r.json()["detail"]["error"] == "ingest_store_unreachable"


# 8. the store's own query and the GET route's shared parser ----------------------------------

def test_8_the_store_query_is_half_open_on_created_at_and_leaves_events_out():
    src = (ROOT / "src" / "iagent" / "ingest_status.py").read_text(encoding="utf-8")
    body = src[src.index("def list_by_created"):src.index("def fail_stalled")]
    assert re.search(r"created_at\s*>=\s*%s\s+AND\s+created_at\s*<\s*%s", body)
    assert "kind <> 'event'" in body and "ORDER BY created_at, id" in body and "LIMIT %s" in body
    assert "updated_at" not in body.split('"""')[1]


def test_8_the_get_batch_route_and_the_post_range_share_one_parser():
    src = (ROOT / "src" / "iagent" / "gateway.py").read_text(encoding="utf-8")
    assert src.count("_export_parse_range(") == 3          # the def, the GET route, the POST range
    assert src.count("def _day(") == 1                       # no second day parser
