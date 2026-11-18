"""The review domain is stored on the receipt (`ingest_status_projection.domain`) so the range
export's domain scope sits IN THE QUERY (architect ruling 2026-11-15), with a bound on pages read.

  1. QUERY      the store is asked for the caller's cell domains (asserted on the request; the
                scope follows the caller; the SQL carries the clause, and no clause when unscoped).
  2. BACKFILL   a NULL row is resolved the old way and written back; a row that has a domain is
                found by range without the old derivation; a failed write loses nothing.
  3. BOUND      the page bound refuses 422 `export_range_scan_bound` and states the bound only.
  4. CORE       ids and range select the same notices, with stored domains too.
  5. WRITER     `set_domain` refuses blank, never touches EVENT rows; the filer calls it.

Run: .venv/Scripts/python -I -m pytest -c pyproject.toml --rootdir=. -q tests/routing/test_the_receipt_carries_its_domain_so_the_scope_sits_in_the_query.py
"""
from __future__ import annotations

import inspect
import re

import pytest

pytest.importorskip("fastapi")

from src.iagent import gateway  # noqa: E402
from src.iagent import ingest_status as ist  # noqa: E402
from tests.routing.test_a_review_export_resolves_every_column_or_refuses import (  # noqa: E402
    DOM_A, DOM_B, ROOT, Ledger, _iid,
)
from tests.routing.test_export_by_range_is_the_id_form_with_another_selector import (  # noqa: E402
    MID, RANGE, _post, _range_world,
)
from tests.routing.test_the_export_profile_server_is_sealed import _cleanup, built  # noqa: E402,F401


def _spy(monkeypatch):
    """Wrap the store double: record the `domains` each page was asked with."""
    seen: list = []
    inner = ist.list_by_created

    def spy(start_ms, end_ms, limit, *, after=None, domains=None):
        seen.append(None if domains is None else frozenset(domains))
        return inner(start_ms, end_ms, limit, after=after, domains=domains)

    monkeypatch.setattr(ist, "list_by_created", spy)
    return seen


def _writes(monkeypatch):
    """Stateful: the writers change the stored receipt as the real SQL does (`set_domain` replaces
    anything different; `clear_domain` puts it back to NULL), and record what they were asked."""
    done: list = []
    rows = {r["id"]: r for r in _range_world.rows}

    def set_domain(i, d):
        done.append((i, d))
        changed = rows[i].get("domain") != d
        rows[i]["domain"] = d
        return changed

    def clear_domain(i):
        done.append((i, None))
        changed = rows[i].get("domain") is not None
        rows[i]["domain"] = None
        return changed

    def set_no_domain(i):
        done.append((i, ist.NO_DOMAIN))
        if rows[i].get("domain") is None:
            rows[i]["domain"] = ist.NO_DOMAIN
            return True
        return False

    monkeypatch.setattr(ist, "set_domain", set_domain)
    monkeypatch.setattr(ist, "clear_domain", clear_domain)
    monkeypatch.setattr(ist, "set_no_domain", set_no_domain)
    return done


@pytest.fixture(autouse=True)
def _fast_retry(monkeypatch):
    async def instant(_s):
        return None
    monkeypatch.setattr(gateway.asyncio, "sleep", instant)


# 1. the query carries the scope ---------------------------------------------------------------

def test_1_the_store_is_asked_for_the_callers_cell_domains(monkeypatch, tmp_path, built):
    _range_world(monkeypatch, tmp_path, [{}, {}])
    seen = _spy(monkeypatch)
    _writes(monkeypatch)
    assert _post({"range": RANGE, "profile": "t", "check_only": True}).status_code == 200
    assert seen and all(s == frozenset({DOM_A}) for s in seen)       # scoped, to the caller's cells


def test_1_control_a_filter_mutated_to_no_scope_is_seen_by_the_assertion(monkeypatch, tmp_path, built):
    _range_world(monkeypatch, tmp_path, [{}])
    seen = _spy(monkeypatch)
    _writes(monkeypatch)
    real = ist.list_by_created
    monkeypatch.setattr(ist, "list_by_created",
                        lambda s, e, n, *, after=None, domains=None: real(s, e, n, after=after, domains=None))
    _post({"range": RANGE, "profile": "t", "check_only": True})
    assert seen and all(s is None for s in seen)       # the mutant drops the scope: `seen` shows it
    assert not all(s == frozenset({DOM_A}) for s in seen)


def test_1_a_notice_stored_in_another_domain_never_leaves_the_store(monkeypatch, tmp_path, built):
    _range_world(monkeypatch, tmp_path, [{"domain": DOM_A}, {"domain": DOM_B}, {"domain": DOM_B}])
    pulled: list = []
    inner = ist.list_by_created

    def tap(*a, **k):
        out = inner(*a, **k)
        pulled.extend(r["id"] for r in out)
        return out

    monkeypatch.setattr(ist, "list_by_created", tap)
    _writes(monkeypatch)
    r = _post({"range": RANGE, "profile": "t", "check_only": True})
    assert r.json()["notice_ids"] == [_iid(1)]
    assert pulled == [_iid(1)]                          # rows 2 and 3 were not read at all


def test_1_the_sql_carries_the_scope_and_the_unscoped_read_has_none(monkeypatch):
    sqls: list = []

    class Cur:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, sql, params): sqls.append((" ".join(sql.split()), params))
        def fetchall(self): return []

    class Conn:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def cursor(self, **k): return Cur()

    monkeypatch.setattr(ist, "_pg_connect", lambda: Conn())
    ist.list_by_created(0, 9, 5, domains={"B", "A"})
    ist.list_by_created(0, 9, 5)
    scoped, plain = sqls
    assert "(domain IS NULL OR domain = ANY(%s))" in scoped[0]
    assert scoped[1] == (0, 9, ["A", "B"], 5)           # a sorted list, no set, no ordering luck
    assert "domain =" not in plain[0] and plain[1] == (0, 9, 5)


# 2. backfill ----------------------------------------------------------------------------------

def test_2_a_null_row_is_resolved_the_old_way_and_written_back(monkeypatch, tmp_path, built):
    _range_world(monkeypatch, tmp_path, [{}, {}])       # no stored domain: the ledger says DOM_A
    done = _writes(monkeypatch)
    r = _post({"range": RANGE, "profile": "t", "check_only": True})
    assert r.json()["notice_ids"] == [_iid(1), _iid(2)]
    assert done == [(_iid(1), DOM_A), (_iid(2), DOM_A)]


def test_2_the_range_derives_every_domain_with_the_one_function_the_preflight_uses(
        monkeypatch, tmp_path, built):
    _range_world(monkeypatch, tmp_path, [{"domain": DOM_A}, {"domain": DOM_A}])
    done = _writes(monkeypatch)
    asked: list = []
    real = gateway._export_notice_domain

    async def counting(ingest_id, row, rec):
        asked.append(ingest_id)
        return await real(ingest_id, row, rec)

    monkeypatch.setattr(gateway, "_export_notice_domain", counting)
    r = _post({"range": RANGE, "profile": "t", "check_only": True})
    assert r.status_code == 200 and r.json()["notice_ids"] == [_iid(1), _iid(2)]
    assert asked == [_iid(1), _iid(2), _iid(1), _iid(2)]    # the range's look, then the preflight's
    assert done == []                                        # stored value agreed: nothing to repair


def test_2_control_a_null_row_of_another_domain_is_dropped_and_still_written_back(
        monkeypatch, tmp_path, built):
    _range_world(monkeypatch, tmp_path, [{}, {}])
    Ledger.domains = {_iid(2): DOM_B}
    done = _writes(monkeypatch)
    r = _post({"range": RANGE, "profile": "t", "check_only": True})
    assert r.json()["notice_ids"] == [_iid(1)] and _iid(2) not in r.text
    assert (_iid(2), DOM_B) in done                     # next range keeps it in the store


def test_2_a_failed_write_back_loses_neither_a_notice_nor_the_scope(monkeypatch, tmp_path, built):
    _range_world(monkeypatch, tmp_path, [{}, {}])
    Ledger.domains = {_iid(2): DOM_B}

    def down(i, d):
        raise RuntimeError("db down")

    monkeypatch.setattr(ist, "set_domain", down)
    r = _post({"range": RANGE, "profile": "t", "check_only": True})
    assert r.status_code == 200 and r.json()["notice_ids"] == [_iid(1)] and _iid(2) not in r.text


# 3. the page bound ----------------------------------------------------------------------------

def test_3_the_page_bound_refuses_and_states_the_bound_only(monkeypatch, tmp_path, built):
    _range_world(monkeypatch, tmp_path, [{"created_at": MID + i} for i in range(6)], page=1)
    _writes(monkeypatch)
    seen = _spy(monkeypatch)
    monkeypatch.setattr(gateway, "_EXPORT_RANGE_MAX_PAGES", 3)
    r = _post({"range": RANGE, "profile": "t", "check_only": True})
    assert r.status_code == 422 and r.json()["detail"]["error"] == "export_range_scan_bound"
    assert len(seen) == 3                               # three pages read, never a fourth
    nums = set(re.findall(r"\d+", r.text)) - {"422"}
    assert nums == {"3"}                                # the bound, and no count of anything else
    for n in range(1, 7):
        assert _iid(n) not in r.text


def test_3_control_under_the_bound_the_same_range_is_served(monkeypatch, tmp_path, built):
    _range_world(monkeypatch, tmp_path, [{"created_at": MID + i} for i in range(6)], page=1)
    _writes(monkeypatch)
    monkeypatch.setattr(gateway, "_EXPORT_RANGE_MAX_PAGES", 7)
    r = _post({"range": RANGE, "profile": "t", "check_only": True})
    assert r.status_code == 200 and len(r.json()["notice_ids"]) == 6


def test_3_the_refusal_formats_no_count_in_source():
    src = (ROOT / "src" / "iagent" / "gateway.py").read_text(encoding="utf-8")
    i = src.index('"export_range_scan_bound"')
    block = src[i:i + 260]
    assert "_EXPORT_RANGE_MAX_PAGES" in block and "len(" not in block and "pages}" not in block


# 4. ids equals range --------------------------------------------------------------------------

def test_4_the_same_notices_by_ids_and_by_range_with_stored_domains(monkeypatch, tmp_path, built):
    _range_world(monkeypatch, tmp_path, [{"domain": DOM_A}, {}, {"domain": DOM_B}])
    Ledger.domains = {_iid(3): DOM_B}
    _writes(monkeypatch)
    by_range = _post({"range": RANGE, "profile": "t", "check_only": True}).json()
    by_ids = _post({"notice_ids": [_iid(1), _iid(2)], "profile": "t", "check_only": True}).json()
    assert by_range["notice_ids"] == [_iid(1), _iid(2)]
    assert by_range["notices"] == by_ids["notices"] == 2
    assert by_range["unexportable"] == by_ids["unexportable"]


# 5. the writer --------------------------------------------------------------------------------

def test_5_set_domain_refuses_blank_and_leaves_events_alone():
    for blank in ("", "  ", None):
        with pytest.raises(ValueError):
            ist.set_domain("x", blank)
    src = (ROOT / "src" / "iagent" / "ingest_status.py").read_text(encoding="utf-8")
    body = src[src.index("def set_domain"):src.index("def fail_stalled")]
    assert "kind <> 'event'" in body and "IS DISTINCT FROM" in body


def test_5_every_return_of_the_promotion_task_filer_notes_the_domain():
    src = (ROOT / "src" / "iagent" / "gateway.py").read_text(encoding="utf-8")
    i = src.index("async def _file_or_find_document_promotion_task")
    j = src.index("\nasync def ", i + 10)
    body = src[i:j]
    returns = len(re.findall(r"^\s+return\b", body, re.M))
    assert body.count("await _note_receipt_domain(") >= 4 and returns >= 4
    # the post-filing write is BEST EFFORT at every return: no strict flag anywhere, the helper
    # cannot raise, and the strict step is the clear BEFORE filing
    assert "strict" not in body
    assert "strict" not in src[src.index("async def _note_receipt_domain"):src.index("async def _clear_stale_receipt_domain")].split('"""')[2]
    assert body.index("_clear_stale_receipt_domain(") < body.index("_note_receipt_domain(")


def test_5_the_column_and_its_index_are_in_the_migration_and_the_ddl():
    for rel in ("src/iagent/ingest_status.py", "sql/create_ingest_status_projection.sql"):
        t = (ROOT / rel).read_text(encoding="utf-8")
        assert "ADD COLUMN IF NOT EXISTS domain TEXT" in t, rel
        assert "idx_isp_domain_created" in t and "(domain, created_at, id)" in t, rel


# 6. a receipt whose resolution found no domain is marked and leaves the scan; filing replaces the marker -------------------------------------

def _no_domain_world(monkeypatch, tmp_path, junk):
    """`junk` receipts that no record and no task names, then the caller's own notice, one per
    page, with a bound of 3 pages."""
    specs = [{"created_at": MID + i} for i in range(junk)] + [{"created_at": MID + junk, "domain": DOM_A}]
    _range_world(monkeypatch, tmp_path, specs, page=1)
    done = _writes(monkeypatch)
    real = gateway._export_notice_domain

    async def derive(ingest_id, row, rec):
        if ingest_id == _iid(junk + 1):
            return await real(ingest_id, row, rec)
        return None

    monkeypatch.setattr(gateway, "_export_notice_domain", derive)
    monkeypatch.setattr(gateway, "_EXPORT_RANGE_MAX_PAGES", 3)
    return done


def _range():
    return _post({"range": RANGE, "profile": "t", "check_only": True})


def test_6a_a_caller_under_the_cap_is_not_refused_by_receipts_that_belong_to_no_domain(
        monkeypatch, tmp_path, built):
    done = _no_domain_world(monkeypatch, tmp_path, junk=4)       # more than the bound, fewer than two
    first = _range()                                              # pays the write-back, may refuse
    assert first.status_code == 422 and first.json()["detail"]["error"] == "export_range_scan_bound"
    second = _range()
    assert second.status_code == 200 and second.json()["notice_ids"] == [_iid(5)]
    assert {i for i, d in done if d == ist.NO_DOMAIN} == {_iid(n) for n in (1, 2, 3, 4)}
    third = _range()                                              # nothing left to write back
    assert third.status_code == 200 and len(done) == 4


def test_6a_control_with_rows_left_NULL_the_same_caller_is_refused_again(monkeypatch, tmp_path, built):
    _no_domain_world(monkeypatch, tmp_path, junk=4)
    monkeypatch.setattr(ist, "set_no_domain", lambda i: False)    # the marker is never written
    assert _range().status_code == 422
    assert _range().status_code == 422                            # and it does not get better


def test_6b_a_receipt_marked_no_domain_that_later_gets_a_task_is_found_by_its_domains_range(
        monkeypatch, tmp_path, built):
    _no_domain_world(monkeypatch, tmp_path, junk=1)
    assert _range().json()["notice_ids"] == [_iid(2)]
    assert _range_world.rows[0]["domain"] == ist.NO_DOMAIN        # marked, and out of the scan
    ist.set_domain(_iid(1), DOM_A)                                # the filer files its task
    async def filed(*a, **k):                                     # the open task now names DOM_A
        return DOM_A

    monkeypatch.setattr(gateway, "_export_notice_domain", filed)
    r = _range()
    assert r.status_code == 200 and r.json()["notice_ids"] == [_iid(1), _iid(2)]
    assert _range_world.rows[0]["domain"] == DOM_A


def test_6b_control_a_marked_receipt_is_not_found_by_any_domains_range(monkeypatch, tmp_path, built):
    _no_domain_world(monkeypatch, tmp_path, junk=1)
    _range()
    assert _range_world.rows[0]["domain"] == ist.NO_DOMAIN
    assert _iid(1) not in _range().text


def test_6_the_marker_is_not_a_domain_and_no_cell_can_match_it(monkeypatch):
    with pytest.raises(ValueError):
        ist.set_domain("x", ist.NO_DOMAIN)
    sqls: list = []

    class Cur:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, sql, params): sqls.append((" ".join(sql.split()), params))
        def fetchall(self): return []
        rowcount = 1

    class Conn:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def cursor(self, **k): return Cur()
        def commit(self): pass

    monkeypatch.setattr(ist, "_pg_connect", lambda: Conn())
    ist.list_by_created(0, 9, 5, domains={"A", ist.NO_DOMAIN})   # a cell spelled like the marker
    assert sqls[-1][1][2] == ["A"]
    ist.set_no_domain("x")
    assert "domain IS NULL" in sqls[-1][0] and sqls[-1][1] == (ist.NO_DOMAIN, "x")
    ist.set_domain("x", "A")
    assert "IS DISTINCT FROM" in sqls[-1][0]                      # replaces the marker, not only NULL


def test_6b_filing_replaces_the_marker_through_the_best_effort_writer(monkeypatch, tmp_path, built):
    _no_domain_world(monkeypatch, tmp_path, junk=1)
    _range()
    assert _range_world.rows[0]["domain"] == ist.NO_DOMAIN                  # marked
    _run(gateway._note_receipt_domain(_iid(1), DOM_A))         # the filer files its task
    assert _range_world.rows[0]["domain"] == DOM_A                          # no longer "no domain"


def test_6c_a_marked_row_whose_filing_write_fails_ends_at_NULL_not_at_the_marker(
        monkeypatch, tmp_path, built):
    _no_domain_world(monkeypatch, tmp_path, junk=1)
    _range()
    assert _range_world.rows[0]["domain"] == ist.NO_DOMAIN

    def down(i, d):
        raise RuntimeError("db down")

    monkeypatch.setattr(ist, "set_domain", down)
    _run(gateway._note_receipt_domain(_iid(1), DOM_A))         # retried, then repaired
    assert _range_world.rows[0]["domain"] is None                           # NULL: resolved again next time


# 7. a stored domain the preflight no longer derives does not fail the range export -----------------

def _task_superseded(monkeypatch):
    """The review task was superseded / expired without a decision: no record, no OPEN task."""
    from src.iagent import human_tasks as ht
    monkeypatch.setattr(ht, "get_task_open_state",
                        lambda t: {"audience": f"document_promotion:{DOM_A}", "open": False})


def _in_review(n, **over):
    return {"status": "in_review", "domain": DOM_A, **over}     # not promoted: no decision record


def test_7_a_stored_domain_whose_task_was_superseded_is_not_listed_and_the_export_is_not_a_422(
        monkeypatch, tmp_path, built):
    _range_world(monkeypatch, tmp_path, [_in_review(1), _in_review(2)])
    _writes(monkeypatch)
    _task_superseded(monkeypatch)
    by_range = _post({"range": RANGE, "profile": "t", "check_only": True})
    by_ids = _post({"notice_ids": [_iid(1), _iid(2)], "profile": "t", "check_only": True})
    assert by_range.status_code == 200 and by_range.json()["notice_ids"] == []   # not a failure
    assert by_range.json()["unexportable"] == []           # the range never listed what it refuses
    assert {u["reason"] for u in by_ids.json()["unexportable"]} == {"not_available"}   # same answer


def test_7_control_the_same_rows_with_an_open_task_are_listed(monkeypatch, tmp_path, built):
    _range_world(monkeypatch, tmp_path, [_in_review(1), _in_review(2)])
    _writes(monkeypatch)
    r = _post({"range": RANGE, "profile": "t", "check_only": True})
    assert r.status_code == 200 and r.json()["notice_ids"] == [_iid(1), _iid(2)]
    assert {u["reason"] for u in r.json()["unexportable"]} == {"state_not_exportable"}


def test_7_one_superseded_row_among_good_ones_drops_alone(monkeypatch, tmp_path, built):
    _range_world(monkeypatch, tmp_path, [_in_review(1), _in_review(2)])
    _writes(monkeypatch)
    from src.iagent import human_tasks as ht
    monkeypatch.setattr(ht, "get_task_open_state",
                        lambda t: {"audience": f"document_promotion:{DOM_A}", "open": _iid(2) in t})
    r = _post({"range": RANGE, "profile": "t", "check_only": True})
    assert r.status_code == 200 and r.json()["notice_ids"] == [_iid(2)]


def test_7_the_range_and_the_preflight_call_one_domain_function():
    src = (ROOT / "src" / "iagent" / "gateway.py").read_text(encoding="utf-8")
    a = src.index("async def _export_range_ids")
    b = src.index("async def _export_preflight")
    c = src.index("\nasync def ", b + 10)
    assert "await _receipt_domain(" in src[a:b] and "await _receipt_domain(" in src[b:c]
    assert "_export_notice_domain(" not in src[a:b] and "_export_notice_domain(" not in src[b:c]


# 8. a failed domain write at filing is retried or repaired, never left stale ---------------------

def _run(coro):
    import asyncio
    return asyncio.run(coro)


def test_8_a_write_that_fails_twice_is_retried_and_lands(monkeypatch):
    calls: list = []

    def flaky(i, d):
        calls.append(d)
        if len(calls) < 3:
            raise RuntimeError("db blip")
        return True

    monkeypatch.setattr(ist, "set_domain", flaky)
    monkeypatch.setattr(ist, "clear_domain", lambda i: pytest.fail("repaired though the retry landed"))
    _run(gateway._note_receipt_domain("x", "B"))
    assert calls == ["B", "B", "B"]


def test_8_a_write_that_never_lands_is_repaired_to_NULL_so_no_stale_domain_hides_the_notice(monkeypatch):
    cleared: list = []

    def down(i, d):
        raise RuntimeError("db down")

    monkeypatch.setattr(ist, "set_domain", down)
    monkeypatch.setattr(ist, "clear_domain", lambda i: cleared.append(i) or True)
    _run(gateway._note_receipt_domain("x", "B"))      # re-class A -> B: A must not stay
    assert cleared == ["x"]


def test_8_when_neither_the_write_nor_the_repair_lands_the_post_filing_write_only_logs(monkeypatch):
    """The task is already filed: a 503 here would fail a call whose filing succeeded."""
    def down(*a):
        raise RuntimeError("db down")

    monkeypatch.setattr(ist, "set_domain", down)
    monkeypatch.setattr(ist, "clear_domain", down)
    _run(gateway._note_receipt_domain("x", "B"))                    # no raise


def test_8_control_a_reader_never_raises_on_the_same_failure(monkeypatch):
    def down(*a):
        raise RuntimeError("db down")

    monkeypatch.setattr(ist, "set_domain", down)
    monkeypatch.setattr(ist, "clear_domain", down)
    _run(gateway._note_receipt_domain("x", "B"))                    # best effort: no raise


def test_8_control_a_clean_write_is_one_call_and_no_repair(monkeypatch):
    calls: list = []
    monkeypatch.setattr(ist, "set_domain", lambda i, d: calls.append((i, d)) or True)
    monkeypatch.setattr(ist, "clear_domain", lambda i: pytest.fail("repaired a clean write"))
    _run(gateway._note_receipt_domain("x", "B"))
    assert calls == [("x", "B")]


def test_8_the_repaired_row_is_then_found_by_the_new_domains_range(monkeypatch, tmp_path, built):
    _range_world(monkeypatch, tmp_path, [{"domain": "elsewhere"}])      # stale: the re-class to A failed
    _writes(monkeypatch)
    r = _post({"range": RANGE, "profile": "t", "check_only": True})
    assert r.json()["notice_ids"] == []                                 # the stale value hides it
    _run(gateway._note_receipt_domain(_iid(1), DOM_A))     # the retry lands
    assert _range_world.rows[0]["domain"] == DOM_A
    r = _post({"range": RANGE, "profile": "t", "check_only": True})
    assert r.json()["notice_ids"] == [_iid(1)]


def test_8_no_domain_writes_nothing_at_all(monkeypatch):
    for blank in (None, "", "  "):
        monkeypatch.setattr(ist, "set_domain", lambda i, d: pytest.fail(f"wrote {d!r}"))
        monkeypatch.setattr(ist, "clear_domain", lambda i: pytest.fail("cleared"))
        _run(gateway._note_receipt_domain("x", blank))


# ---------------------------------------------------------------------------
# 9. the stored domain is cleared BEFORE a task is filed against another one
# ---------------------------------------------------------------------------

def test_9_a_differing_stored_domain_is_cleared_before_filing(monkeypatch):
    cleared: list = []
    monkeypatch.setattr(ist, "clear_domain", lambda i: cleared.append(i) or True)
    _run(gateway._clear_stale_receipt_domain("x", "A", "B"))            # re-class A -> B
    _run(gateway._clear_stale_receipt_domain("x", ist.NO_DOMAIN, "B"))  # the marker
    assert cleared == ["x", "x"]


def test_9_control_the_same_domain_or_none_is_not_touched(monkeypatch):
    monkeypatch.setattr(ist, "clear_domain", lambda i: pytest.fail("cleared a value that agrees"))
    _run(gateway._clear_stale_receipt_domain("x", "B", "B"))
    _run(gateway._clear_stale_receipt_domain("x", None, "B"))


def test_9_a_clear_that_fails_is_retried_then_503_and_nothing_is_filed(monkeypatch):
    from fastapi import HTTPException
    calls: list = []

    def down(i):
        calls.append(i)
        raise RuntimeError("db down")

    monkeypatch.setattr(ist, "clear_domain", down)
    with pytest.raises(HTTPException) as ei:
        _run(gateway._clear_stale_receipt_domain("x", "A", "B"))
    assert ei.value.status_code == 503 and ei.value.detail["error"] == "receipt_domain_unwritten"
    assert len(calls) == gateway._RECEIPT_DOMAIN_ATTEMPTS


def test_9_a_clear_that_fails_once_is_retried_and_lands(monkeypatch):
    calls: list = []

    def flaky(i):
        calls.append(i)
        if len(calls) < 2:
            raise RuntimeError("blip")
        return True

    monkeypatch.setattr(ist, "clear_domain", flaky)
    _run(gateway._clear_stale_receipt_domain("x", "A", "B"))
    assert len(calls) == 2


def test_9_re_class_whose_later_write_fails_leaves_NULL_never_the_old_domain(monkeypatch, tmp_path, built):
    """The reviewer's variant: g+1 files against B and the write of B fails. The row was cleared
    first, so it ends at NULL (found by BOTH callers' ranges), not at A."""
    _no_domain_world(monkeypatch, tmp_path, junk=1)
    _range_world.rows[0]["domain"] = DOM_A
    _run(gateway._clear_stale_receipt_domain(_iid(1), DOM_A, DOM_B))
    assert _range_world.rows[0]["domain"] is None

    def down(i, d):
        raise RuntimeError("db down")

    monkeypatch.setattr(ist, "set_domain", down)
    monkeypatch.setattr(ist, "clear_domain", lambda i: (_ for _ in ()).throw(RuntimeError("down")))
    _run(gateway._note_receipt_domain(_iid(1), DOM_B))     # the filing's write fails
    assert _range_world.rows[0]["domain"] is None


def test_9_the_filer_clears_before_it_registers_the_task():
    src = inspect.getsource(gateway._file_or_find_document_promotion_task)
    assert "_clear_stale_receipt_domain(" in src
    assert src.index("_clear_stale_receipt_domain(") < src.index("human_tasks.task_exists(")
    assert src.index("_clear_stale_receipt_domain(") < src.index("human_tasks.register_task(")


def test_9_with_no_projection_store_configured_the_filer_neither_writes_nor_refuses(monkeypatch):
    """The store is unconfigured (a chart without the projection): there is no stored domain to
    scope or to clear, and no range can run. Filing must not turn that into a 503."""
    def unconfigured(*a, **k):
        raise ist.IngestStatusConfigError("no dsn")

    monkeypatch.setattr(ist, "set_domain", unconfigured)
    monkeypatch.setattr(ist, "clear_domain", unconfigured)
    _run(gateway._note_receipt_domain("x", "B"))
    _run(gateway._clear_stale_receipt_domain("x", "A", "B"))
