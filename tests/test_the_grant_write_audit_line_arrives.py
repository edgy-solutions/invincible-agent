"""`write_grant_and_sync` writes a reader grant into the pod's asset_grants.yaml and never commits
it, so until ADR-0062 §7's engine-r merge replaces it, its only audit is one line: who, what, when
(architect, 2026-10-28). The line must ARRIVE -- the BFF's root handler sits at WARNING -- so it
has its own logger, made to arrive the same way as the other BFF audit loggers."""
from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("psycopg2")
from src.iagent import human_tasks as ht  # noqa: E402

NAME = "iagent.audit.grant_write"


@pytest.fixture
def grants_file(tmp_path, monkeypatch):
    p = tmp_path / "asset_grants.yaml"
    p.write_text("grants: []\n", encoding="utf-8")
    monkeypatch.setattr(ht, "_ASSET_GRANTS_FILE", str(p))
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    return p


def _lines(caplog):
    return [r.getMessage() for r in caplog.records if r.name == NAME]


def test_arm1_the_logger_is_effectively_at_info():
    assert logging.getLogger(NAME).getEffectiveLevel() <= logging.INFO


def test_arm2_a_new_grant_writes_one_line_naming_who_what_and_when(grants_file, caplog):
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


def test_arm3_a_duplicate_grant_writes_nothing_and_logs_nothing(grants_file, caplog):
    ht.write_grant_and_sync(subject="user-a", asset="doc-1", granted_by="grantor-b", reason="r")
    caplog.clear()
    caplog.set_level(logging.INFO, logger=NAME)
    ht.write_grant_and_sync(subject="user-a", asset="doc-1", granted_by="grantor-c", reason="r")
    assert _lines(caplog) == []
    assert grants_file.read_text(encoding="utf-8").count("subject: user-a") == 1


def test_arm4_human_tasks_wires_the_arrival():
    src = Path(ht.__file__).read_text(encoding="utf-8")
    assert "_ensure_the_audit_line_actually_ARRIVES(_grant_audit_log)" in src
