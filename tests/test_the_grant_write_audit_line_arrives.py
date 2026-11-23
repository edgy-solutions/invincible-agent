"""An approved access grant is recorded in the decision ledger (it no longer writes a file in the
pod). Until ADR-0062 section 7's engine-r merge replaces this path with a commit, its audit is the
ledger row plus one line: who asked, who approved, what, when (architect, 2026-10-28; the ledger,
2026-11-15). The line must ARRIVE -- the BFF's root handler sits at WARNING -- so it has its own
logger, made to arrive the same way as the other BFF audit loggers."""
from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest

pytest.importorskip("psycopg2")
from src.iagent import human_tasks as ht  # noqa: E402
from tests.test_an_approved_access_grant_is_in_the_ledger_not_a_file import (  # noqa: E402,F401
    FakeLedgerDb, world,
)

NAME = "iagent.audit.grant_write"


def _lines(caplog):
    return [r.getMessage() for r in caplog.records if r.name == NAME]


def test_arm1_the_logger_is_effectively_at_info():
    assert logging.getLogger(NAME).getEffectiveLevel() <= logging.INFO


def test_arm2_a_new_grant_writes_one_line_naming_who_what_and_when(world, caplog):
    caplog.set_level(logging.INFO, logger=NAME)
    out = ht.write_grant_and_sync(
        subject="user-a", asset="doc-1", granted_by="grantor-b", reason="r",
    )
    assert out["ok"]
    lines = _lines(caplog)
    assert len(lines) == 1, lines
    assert "granted_by=grantor-b" in lines[0]
    assert "subject=user-a" in lines[0]
    assert "asset=doc-1" in lines[0]
    assert re.search(r"at=\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", lines[0]), lines[0]


def test_arm3_a_duplicate_grant_logs_nothing_and_records_nothing_new(world, caplog):
    ht.write_grant_and_sync(subject="user-a", asset="doc-1", granted_by="grantor-b", reason="r")
    caplog.clear()
    caplog.set_level(logging.INFO, logger=NAME)
    ht.write_grant_and_sync(subject="user-a", asset="doc-1", granted_by="grantor-c", reason="r")
    assert _lines(caplog) == []
    assert [g["granted_by"] for g in ht.ledger_grants()] == ["grantor-b"]


def test_arm4_human_tasks_wires_the_arrival():
    src = Path(ht.__file__).read_text(encoding="utf-8")
    assert "_ensure_the_audit_line_actually_ARRIVES(_grant_audit_log)" in src
