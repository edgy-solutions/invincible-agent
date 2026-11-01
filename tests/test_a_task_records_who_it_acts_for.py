"""register_task records `on_behalf_of` on every projection row, apart from `requested_by`.

ADR-0063 / OpenDDIL ADR-0052 s5. "" is legal (a service-origin finding) and is not a refusal.
"""
from __future__ import annotations

import pathlib
from unittest import mock

_P = pathlib.Path(__file__).resolve().parents[1] / "src" / "iagent" / "human_tasks.py"
from iagent import human_tasks as ht  # noqa: E402


def _cm(value):
    cm = mock.MagicMock()
    cm.__enter__ = mock.Mock(return_value=value)
    cm.__exit__ = mock.Mock(return_value=False)
    return cm


def _register(**over):
    rows, sqls = [], []
    conn = mock.MagicMock()
    conn.cursor.return_value = _cm(mock.MagicMock())
    kw = dict(kind="workflow_ack", task_id="c-1~1:s1", audience="aud:x", title="t", summary="s",
              requested_by="svc:x")
    kw.update(over)
    with mock.patch.object(ht, "_resolve_audience_actors", return_value=["a@x", "b@x"]), \
         mock.patch.object(ht, "_pg_connect", return_value=_cm(conn)), \
         mock.patch.object(ht.psycopg2.extras, "execute_values",
                           side_effect=lambda c, sql, vals: (sqls.append(sql), rows.extend(vals))):
        ht.register_task(**kw)
    return rows, sqls[0]


def _value(row, sql):
    cols = [c.strip() for c in sql.split("(", 1)[1].split(")", 1)[0].split(",")]
    return row[cols.index("on_behalf_of")]


def test_every_recipient_row_stores_the_passed_value_stripped():
    rows, sql = _register(on_behalf_of="  alice@x ")
    assert len(rows) == 2 and {_value(r, sql) for r in rows} == {"alice@x"}


def test_CONTROL_the_default_stores_the_empty_string_and_is_no_refusal():
    rows, sql = _register()
    assert {_value(r, sql) for r in rows} == {""}
    assert {_value(r, sql) for r in _register(on_behalf_of=None)[0]} == {""}


def test_the_column_is_added_idempotently_in_both_homes():
    want = "ADD COLUMN IF NOT EXISTS on_behalf_of TEXT NOT NULL DEFAULT ''"
    assert want in ht._MIGRATION_SQL
    sql_file = (_P.parents[2] / "sql" / "create_human_task_projection.sql").read_text("utf-8")
    assert want in sql_file
