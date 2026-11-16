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
    anything different; `set_no_domain` marks only a NULL), and record what they were asked."""
    done: list = []
    rows = {r["id"]: r for r in _range_world.rows}

    def set_domain(i, d):
        done.append((i, d))
        changed = rows[i].get("domain") != d
        rows[i]["domain"] = d
        return changed

    def set_no_domain(i):
        done.append((i, ist.NO_DOMAIN))
        if rows[i].get("domain") is None:
            rows[i]["domain"] = ist.NO_DOMAIN
            return True
        return False

    monkeypatch.setattr(ist, "set_domain", set_domain)
    monkeypatch.setattr(ist, "set_no_domain", set_no_domain)
    return done


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


def test_2_a_backfilled_receipt_is_found_by_range_without_the_old_derivation(monkeypatch, tmp_path, built):
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
    assert asked == [_iid(1), _iid(2)] and done == []   # preflight's own look only: the scan added none


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


def test_5_the_column_and_its_index_are_in_the_migration_and_the_ddl():
    for rel in ("src/iagent/ingest_status.py", "sql/create_ingest_status_projection.sql"):
        t = (ROOT / rel).read_text(encoding="utf-8")
        assert "ADD COLUMN IF NOT EXISTS domain TEXT" in t, rel
        assert "idx_isp_domain_created" in t and "(domain, created_at, id)" in t, rel


# 6. a receipt that resolves to no domain leaves the scan -------------------------------------

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
