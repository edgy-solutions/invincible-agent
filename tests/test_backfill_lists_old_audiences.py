"""`backfill_promotion_origin.py --list-old-audiences` (ruling Q6, architect, 2026-10-10).

Lists LIVE `document_promotion` tasks whose audience `promotion.domain_of` refuses. It only lists.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

from src.iagent import promotion


def _backfill_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "backfill_promotion_origin.py"
    spec = importlib.util.spec_from_file_location("backfill_promotion_origin", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _row(n, audience, *, subject_ref=None, payload=None, created_at=None, task_id=None):
    return {"task_id": task_id or f"document_promotion:sha256:{n}", "audience": audience,
            "subject_ref": subject_ref, "payload": payload if payload is not None else {},
            "created_at": created_at if created_at is not None else n}


def test_arm1_only_non_domain_audiences_are_listed():
    mod = _backfill_module()
    rows = [_row(1, "document_promotion:SUSTAINMENT"),
            _row(2, "aud:sustainment-approvers"),
            _row(3, "document_promotion:"),
            _row(4, "document_promotion"),
            _row(5, "")]
    got = mod.old_audience_tasks(rows)
    assert [t["audience"] for t in got] == [
        "aud:sustainment-approvers", "document_promotion:", "document_promotion", ""]


def test_arm2_the_predicate_is_domain_of(monkeypatch):
    mod = _backfill_module()
    rows = [_row(1, "aud:x"), _row(2, "")]
    assert len(mod.old_audience_tasks(rows)) == 2
    monkeypatch.setattr(promotion, "domain_of", lambda audience: "ANY")
    assert mod.old_audience_tasks(rows) == []


def test_arm3_proposed_domain_order_and_normalisation():
    mod = _backfill_module()
    rows = [
        _row(1, "aud:a", payload={"review_pool": "finance", "domain": "safety"}),
        _row(2, "aud:b", payload={"domain": "  safety "}),
        _row(3, "aud:c", payload={}),
        _row(4, "aud:d", payload={"review_pool": "  ", "domain": "cost"}),
        _row(5, "aud:e", payload='{"review_pool": " sustainment "}'),
        _row(6, "document_promotion:FINANCE-looking", payload={}),
        _row(7, "aud:document_promotion:FINANCE", payload={}),
    ]
    got = {t["task_id"][-1]: t for t in mod.old_audience_tasks(rows)}
    assert (got["1"]["proposed_domain"], got["1"]["proposed_from"]) == ("FINANCE", "review_pool")
    assert (got["2"]["proposed_domain"], got["2"]["proposed_from"]) == ("SAFETY", "payload_domain")
    assert (got["3"]["proposed_domain"], got["3"]["proposed_from"]) == (None, "undecided")
    assert (got["4"]["proposed_domain"], got["4"]["proposed_from"]) == ("COST", "payload_domain")
    assert (got["5"]["proposed_domain"], got["5"]["proposed_from"]) == (
        "SUSTAINMENT", "review_pool")
    # the audience text is never a source of the proposal
    assert (got["7"]["proposed_domain"], got["7"]["proposed_from"]) == (None, "undecided")


def test_arm4_ingest_id_from_subject_ref_else_task_id_suffix():
    mod = _backfill_module()
    rows = [_row(1, "aud:a", subject_ref="sha256:aaa", task_id="document_promotion:sha256:zzz"),
            _row(2, "aud:b", subject_ref=None, task_id="document_promotion:sha256:bbb")]
    got = {t["task_id"]: t for t in mod.old_audience_tasks(rows)}
    assert got["document_promotion:sha256:zzz"]["ingest_id"] == "sha256:aaa"
    assert got["document_promotion:sha256:bbb"]["ingest_id"] == "sha256:bbb"


def test_arm5_one_row_per_recipient_lists_once():
    mod = _backfill_module()
    rows = [_row(1, "aud:a", task_id="document_promotion:sha256:t1", created_at=5),
            _row(1, "aud:a", task_id="document_promotion:sha256:t1", created_at=5),
            _row(1, "aud:a", task_id="document_promotion:sha256:t1", created_at=5),
            _row(2, "aud:b", task_id="document_promotion:sha256:t0", created_at=5)]
    got = mod.old_audience_tasks(rows)
    assert [t["task_id"] for t in got] == ["document_promotion:sha256:t0",
                                           "document_promotion:sha256:t1"]


def test_arm6_list_and_apply_are_mutually_exclusive(monkeypatch):
    mod = _backfill_module()
    monkeypatch.setattr(sys, "argv", ["x", "--list-old-audiences", "--apply"])
    with pytest.raises(SystemExit) as ei:
        mod.main()
    assert ei.value.code == 2


def _fake_psycopg2(rows, executed):
    class Cur:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, sql, *a): executed.append(sql)
        def fetchall(self): return rows

    class Conn:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def cursor(self): return Cur()

    return types.SimpleNamespace(connect=lambda dsn: Conn())


def _env(monkeypatch, *, dsn=True):
    monkeypatch.delenv("BACKFILL_ACTOR", raising=False)
    if dsn:
        monkeypatch.setenv("PROJECTOR_POSTGRES_DSN", "postgresql://fake")
    else:
        monkeypatch.delenv("PROJECTOR_POSTGRES_DSN", raising=False)
    monkeypatch.setattr(sys, "argv", ["x", "--list-old-audiences"])


def test_arm7_cli_exit_codes_and_summary(monkeypatch, capsys):
    mod = _backfill_module()

    _env(monkeypatch, dsn=False)
    assert mod.main() == 2

    executed: list = []
    _env(monkeypatch)
    rows = [("document_promotion:sha256:a", "aud:old", "sha256:a", {"review_pool": "cost"}, 10),
            ("document_promotion:sha256:b", "document_promotion:SAFETY", "sha256:b", {}, 11),
            ("document_promotion:sha256:c", "aud:old2", None, {}, 12)]
    monkeypatch.setitem(sys.modules, "psycopg2", _fake_psycopg2(rows, executed))
    assert mod.main() == 1
    out = capsys.readouterr().out
    assert "old_audience_tasks=2 undecided=1" in out
    assert "\t".join(["document_promotion:sha256:a", "sha256:a", "aud:old", "COST",
                      "review_pool", "10"]) in out
    assert "DISTINCT ON (task_id)" in executed[0] and "status = 'pending'" in executed[0]

    _env(monkeypatch)
    ok = [("document_promotion:sha256:b", "document_promotion:SAFETY", "sha256:b", {}, 11)]
    monkeypatch.setitem(sys.modules, "psycopg2", _fake_psycopg2(ok, []))
    assert mod.main() == 0
    assert "old_audience_tasks=0 undecided=0" in capsys.readouterr().out
