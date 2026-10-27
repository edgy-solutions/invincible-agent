"""The retry join (2026-10-16): `retry_failed` re-opens a failed document row and
`list_pending_retries` is how doc-tools' sensor finds it again. The route tests stub
`retry_failed`, so nothing else asserts the two agree. This does, on the SQL TEXT each sends.

The join: the UPDATE leaves a row at `status = 'received'` with `attempt` one higher than a first
attempt's 1 (so attempt >= 2); the SELECT takes `status = 'received' AND attempt > 1 AND kind <>
'event'`. Event rows are excluded from both sides. The column's floor is the DDL's
`attempt INTEGER NOT NULL DEFAULT 1`, in the SQL file and in the copy ingest_status.py applies.

Arms:
  update    sets status 'received' and attempt = attempt + 1; guards on 'failed' and kind <> 'event'.
  select    status = 'received', attempt > 1, kind <> 'event'.
  join      the status the UPDATE writes is the status the SELECT reads; the bound the SELECT uses
            (attempt > 1) is below what the UPDATE yields from the DDL default (1 + 1).
  ddl       attempt INTEGER NOT NULL DEFAULT 1 in sql/create_ingest_status_projection.sql and in
            ingest_status.py.

Run: uv run pytest tests/test_a_retried_row_is_the_row_the_listing_selects.py -v
"""
from __future__ import annotations

import re
from pathlib import Path
from unittest import mock

import pytest

pytest.importorskip("fastapi")
from src.iagent import ingest_status as ist  # noqa: E402

_REPO = Path(__file__).resolve().parents[1]
_ID = "a" * 64
_DDL_COL = re.compile(r"ADD COLUMN IF NOT EXISTS attempt\s+INTEGER\s+NOT NULL\s+DEFAULT\s+(\d+)\s*;")


def _norm(sql: str) -> str:
    return " ".join(sql.split())


def _fake_conn(fetchone=None, fetchall=()):
    cur = mock.MagicMock()
    cur.fetchone.return_value = fetchone
    cur.fetchall.return_value = list(fetchall)
    cur_cm = mock.MagicMock()
    cur_cm.__enter__ = mock.Mock(return_value=cur)
    cur_cm.__exit__ = mock.Mock(return_value=False)
    conn = mock.MagicMock()
    conn.cursor.return_value = cur_cm
    conn_cm = mock.MagicMock()
    conn_cm.__enter__ = mock.Mock(return_value=conn)
    conn_cm.__exit__ = mock.Mock(return_value=False)
    return conn_cm, cur


def _update_sql() -> str:
    cm, cur = _fake_conn(fetchone=(2,))
    with mock.patch.object(ist, "_pg_connect", return_value=cm):
        assert ist.retry_failed(_ID, now_ms=5) == 2
    return _norm(cur.execute.call_args[0][0])


def _select_sql() -> str:
    cm, cur = _fake_conn()
    with mock.patch.object(ist, "_pg_connect", return_value=cm):
        ist.list_pending_retries(limit=5)
    return _norm(cur.execute.call_args[0][0])


def test_the_update_reopens_at_received_and_bumps_the_attempt():
    sql = _update_sql()
    assert sql.startswith("UPDATE ingest_status_projection")
    assert "status = 'received'" in sql.split("WHERE")[0]
    assert "attempt = attempt + 1" in sql.split("WHERE")[0]


def test_the_update_matches_only_a_failed_non_event_row():
    where = _update_sql().split("WHERE", 1)[1]
    assert "status = 'failed'" in where
    assert "kind <> 'event'" in where


def test_the_select_takes_received_retried_non_event_rows():
    where = _select_sql().split("WHERE", 1)[1]
    assert "status = 'received'" in where
    assert "attempt > 1" in where
    assert "kind <> 'event'" in where


def test_the_status_the_update_writes_is_the_status_the_select_reads():
    wrote = re.search(r"SET status = '(\w+)'", _update_sql())
    read = re.search(r"WHERE status = '(\w+)'", _select_sql())
    assert wrote and read and wrote.group(1) == read.group(1) == "received"


def test_a_first_retry_from_the_ddl_default_is_above_the_selects_bound():
    default = int(_DDL_COL.search((_REPO / "sql" / "create_ingest_status_projection.sql")
                                  .read_text(encoding="utf-8")).group(1))
    bound = int(re.search(r"attempt > (\d+)", _select_sql()).group(1))
    assert default + 1 > bound >= default


def test_the_sql_file_declares_attempt_integer_not_null_default_1():
    text = (_REPO / "sql" / "create_ingest_status_projection.sql").read_text(encoding="utf-8")
    assert [m for m in _DDL_COL.findall(text)] == ["1"]


def test_the_copy_ingest_status_applies_declares_the_same_column():
    src = (_REPO / "src" / "iagent" / "ingest_status.py").read_text(encoding="utf-8")
    assert [m for m in _DDL_COL.findall(src)] == ["1"]
