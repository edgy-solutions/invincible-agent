"""The graph menu read pages by cursor instead of capping at one `limit`.

Live, the Predicate collection held 644 rows and a single `limit:500` read served
the current cortex version as 33 of its 49 capabilities. The read now pages with
Weaviate's `after` cursor, and any failed page makes the whole read None.
"""
from __future__ import annotations

import json
import logging
import re

from tests.test_graph_menu_source import _MESH, _Resp, _gms, _install, _row


class _Paging:
    """A Weaviate fake that honours `limit:N` and `after:"id"` over id-ordered rows."""

    def __init__(self, n, *, fail_page=None, fail_with="raise"):
        self.rows = [
            dict(_row(input_uri=f"{_MESH}Cap{i:03d}"), _additional={"id": f"id-{i:03d}"})
            for i in range(n)
        ]
        self.queries = []
        self.fail_page = fail_page
        self.fail_with = fail_with

    def urlopen(self, req, timeout=None):
        url = req if isinstance(req, str) else req.full_url
        if "/v1/schema/" in url:
            return _Resp({"properties": [{"name": "verb_iri"}, {"name": "frontend_id"}]})
        q = json.loads(req.data.decode())["query"]
        self.queries.append(q)
        if self.fail_page is not None and len(self.queries) == self.fail_page:
            if self.fail_with == "raise":
                raise OSError("connection reset")
            return _Resp({"errors": [{"message": "boom"}]})
        limit = int(re.search(r"limit:(\d+)", q).group(1))
        m = re.search(r'after:"([^"]*)"', q)
        rows = self.rows
        if m:
            rows = [r for r in rows if r["_additional"]["id"] > m.group(1)]
        return _Resp({"data": {"Get": {"Predicate": rows[:limit]}}})


def _caps(entries):
    return {c["subject_uri"] for c in entries["cortex"]["capabilities"]}


def test_seven_rows_page_size_three_reads_every_row(monkeypatch):
    m = _gms()
    fake = _install(monkeypatch, m, _Paging(7))
    entries = m.fetch_registered_entries(limit=3)
    assert _caps(entries) == {f"{_MESH}Cap{i:03d}" for i in range(7)}
    assert len(fake.queries) == 3


def test_an_exact_multiple_reads_all_and_stops_on_the_empty_page(monkeypatch):
    m = _gms()
    fake = _install(monkeypatch, m, _Paging(6))
    entries = m.fetch_registered_entries(limit=3)
    assert len(_caps(entries)) == 6
    assert len(fake.queries) == 3
    assert "after:" in fake.queries[2]


def test_the_second_page_carries_the_first_pages_last_id(monkeypatch):
    m = _gms()
    fake = _install(monkeypatch, m, _Paging(7))
    m.fetch_registered_entries(limit=3)
    assert "after:" not in fake.queries[0]
    assert 'after:"id-002"' in fake.queries[1]
    assert 'after:"id-005"' in fake.queries[2]


def test_a_second_page_exception_returns_None_not_the_first_menu(monkeypatch):
    m = _gms()
    _install(monkeypatch, m, _Paging(7, fail_page=2, fail_with="raise"))
    assert m.fetch_registered_entries(limit=3) is None


def test_a_second_page_graphql_error_returns_None_not_the_first_menu(monkeypatch):
    m = _gms()
    _install(monkeypatch, m, _Paging(7, fail_page=2, fail_with="errors"))
    assert m.fetch_registered_entries(limit=3) is None


def test_max_rows_logs_TRUNCATED_and_terminates(monkeypatch):
    m = _gms()
    fake = _install(monkeypatch, m, _Paging(50))
    seen = []

    class _H(logging.Handler):
        def emit(self, record):
            seen.append(record)

    h = _H(level=logging.WARNING)
    m.logger.addHandler(h)  # the module logger does not propagate to caplog
    try:
        entries = m.fetch_registered_entries(limit=3, max_rows=7)
    finally:
        m.logger.removeHandler(h)
    assert any("TRUNCATED at max_rows=7" in r.getMessage() for r in seen)
    assert len(fake.queries) == 3  # 3, 6, 9 rows read; 9 >= 7 stops
    assert len(_caps(entries)) == 9


def test_the_additional_key_does_not_leak_into_entries(monkeypatch):
    m = _gms()
    _install(monkeypatch, m, _Paging(4))
    entries = m.fetch_registered_entries(limit=3)
    assert "_additional" not in json.dumps(entries)
