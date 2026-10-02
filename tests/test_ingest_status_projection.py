"""ingest_status.py — the ingest_status_projection CRUD, same shape as human_task_projection
(tests/test_human_tasks_recipients.py is the template this file mirrors, including the
direct-file-load harness so the module never needs a real PROJECTOR_POSTGRES_DSN or a live
psycopg2 connection).

Covers (ADR-0041 §8):
  - level-1 dedupe: find_primary_by_sha is a hit/miss, scoped to non-duplicate rows
  - record_duplicate_arrival's message shape: "already processed on <date> from <source>"
  - record_received rejects an undeclared kind (never a silent pass-through to SQL)
  - get_status_for is existence-oracle-safe: scoped to submitted_by OR on_behalf_of = caller,
    a non-owner gets None (never another user's row), mirroring
    test_resolution_lookup_is_caller_scoped_not_an_existence_oracle exactly.

Run:  MSYS_NO_PATHCONV=1 uv run --frozen pytest tests/test_ingest_status_projection.py -q -p no:cacheprovider
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest import mock

import pytest

_MOD = Path(__file__).resolve().parents[1] / "src" / "iagent" / "ingest_status.py"
_spec = importlib.util.spec_from_file_location("iagent_ingest_status", _MOD)
ist = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ist)  # type: ignore[union-attr]


def _fake_conn(fetchone_row=None):
    cur = mock.MagicMock()
    cur.fetchone.return_value = fetchone_row
    cur_cm = mock.MagicMock()
    cur_cm.__enter__ = mock.Mock(return_value=cur)
    cur_cm.__exit__ = mock.Mock(return_value=False)
    conn = mock.MagicMock()
    conn.cursor.return_value = cur_cm
    conn_cm = mock.MagicMock()
    conn_cm.__enter__ = mock.Mock(return_value=conn)
    conn_cm.__exit__ = mock.Mock(return_value=False)
    return conn_cm, conn, cur


# ===========================================================================
# Level-1 dedupe: find_primary_by_sha
# ===========================================================================
def test_find_primary_by_sha_hit_returns_the_original_row():
    row = {"id": "abc123", "sha256": "abc123", "kind": "pdf", "object_prefix": "ingress-user/pdf/abc123/",
           "submitted_by": "alice@example.com", "on_behalf_of": "alice@example.com",
           "source": "notice.pdf", "status": "received", "created_at": 1785000000000}
    cm, _, cur = _fake_conn(row)
    with mock.patch.object(ist, "_pg_connect", return_value=cm):
        out = ist.find_primary_by_sha("abc123")
    assert out["id"] == "abc123"
    assert out["source"] == "notice.pdf"
    # scoped to non-duplicate rows -- positive control that the query excludes DUPLICATE
    sql, params = cur.execute.call_args[0][0], cur.execute.call_args[0][1]
    assert "status != %s" in sql, f"dedupe lookup must exclude duplicate rows; SQL was: {sql}"
    assert ist.DUPLICATE in params


def test_find_primary_by_sha_miss_returns_none():
    cm, _, _ = _fake_conn(None)
    with mock.patch.object(ist, "_pg_connect", return_value=cm):
        assert ist.find_primary_by_sha("never-seen-sha") is None


def test_find_primary_by_sha_rejects_empty_input_without_touching_the_db():
    with mock.patch.object(ist, "_pg_connect") as pg:
        assert ist.find_primary_by_sha("") is None
        pg.assert_not_called()


# ===========================================================================
# record_received -- kind must be declared and in the closed set (never LLM-classified)
# ===========================================================================
_INGEST_ID = "sha256:" + "ab" * 32


def test_record_received_rejects_an_undeclared_kind_before_any_db_touch():
    with mock.patch.object(ist, "_pg_connect") as pg:
        with pytest.raises(ValueError):
            ist.record_received(ingest_id=_INGEST_ID, sha256="x", kind="docx", object_prefix="p",
                                 submitted_by="alice@example.com", on_behalf_of="alice@example.com")
        pg.assert_not_called()


@pytest.mark.parametrize("bad_id", [
    "abc123",                      # bare hex, the OLD spelling this seam used to mint
    "sha256:" + "AB" * 32,          # upper case
    "sha256:" + "ab" * 31 + "a",    # 63 hex
])
def test_record_received_rejects_a_misspelled_ingest_id_before_any_db_touch(bad_id):
    """The seam mints ids with promotion.ingest_id_for; an id in the old bare-hex spelling (or
    any other mis-spelling) would make a later document_promotion sweep delete nothing."""
    with mock.patch.object(ist, "_pg_connect") as pg:
        with pytest.raises(ValueError):
            ist.record_received(ingest_id=bad_id, sha256="abc123", kind="pdf",
                                 object_prefix="ingress-user/pdf/abc123/",
                                 submitted_by="alice@example.com", on_behalf_of="alice@example.com")
        pg.assert_not_called()


def test_record_received_writes_a_received_row_at_the_ingest_id_as_id():
    cm, conn, _ = _fake_conn()
    with mock.patch.object(ist, "_pg_connect", return_value=cm):
        row = ist.record_received(ingest_id=_INGEST_ID, sha256="abc123", kind="pdf",
                                   object_prefix="ingress-user/pdf/abc123/",
                                   submitted_by="alice@example.com", on_behalf_of="alice@example.com",
                                   source="notice.pdf")
    assert row["id"] == _INGEST_ID, "a primary row is content-addressed: id == promotion.ingest_id_for"
    assert row["sha256"] == "abc123", "sha256 keeps its OWN column, the bare-hex dedupe key"
    assert row["status"] == ist.RECEIVED
    conn.commit.assert_called_once()


# ===========================================================================
# record_duplicate_arrival -- the caller-facing message shape (ADR-0041 §8's exact wording)
# ===========================================================================
def test_duplicate_arrival_message_names_the_date_and_source():
    original = {"id": "abc123", "created_at": 1767225600000,  # 2026-01-01T00:00:00Z
                "source": "notice.pdf"}
    cm, conn, _ = _fake_conn()
    with mock.patch.object(ist, "_pg_connect", return_value=cm):
        row = ist.record_duplicate_arrival(
            sha256="abc123", kind="pdf", object_prefix="ingress-user/pdf/abc123/",
            submitted_by="bob@example.com", on_behalf_of="bob@example.com",
            source="notice-copy.pdf", original=original)
    assert row["status"] == ist.DUPLICATE
    assert row["duplicate_of"] == "abc123"
    assert row["id"] != "abc123", "a duplicate-arrival row gets its OWN id, never overwrites the original"
    assert row["detail"] == "already processed on 2026-01-01 from notice.pdf"
    conn.commit.assert_called_once()


def test_duplicate_arrival_message_handles_a_missing_source():
    original = {"id": "abc123", "created_at": 1767225600000, "source": None}
    cm, _, _ = _fake_conn()
    with mock.patch.object(ist, "_pg_connect", return_value=cm):
        row = ist.record_duplicate_arrival(
            sha256="abc123", kind="pdf", object_prefix="ingress-user/pdf/abc123/",
            submitted_by="bob@example.com", on_behalf_of="bob@example.com",
            source=None, original=original)
    assert row["detail"] == "already processed on 2026-01-01 from unknown source"


# ===========================================================================
# The stage vocabulary -- mirrors iagent_mesh.ingest.INGEST_STAGES (ca b68926a); the OLD
# rungs (classified/extracted/review) are gone, and nothing in this repo consumed them (grep
# census at implementation time: no import of ingest_status.CLASSIFIED/EXTRACTED/REVIEW/
# STATUSES anywhere in src/ or tests/ besides this module's own definition).
# ===========================================================================
def test_the_stage_vocabulary_is_cas_six_stages_in_order():
    assert ist.STAGES == ("received", "extracting", "awaiting_disposition", "promoted",
                          "rejected", "failed")
    assert not hasattr(ist, "CLASSIFIED")
    assert not hasattr(ist, "EXTRACTED")
    assert not hasattr(ist, "REVIEW")
    assert not hasattr(ist, "STATUSES"), "nothing in-repo imports the old alias; dropped, not kept"


def test_duplicate_stays_out_of_band():
    assert ist.ALL_STATUSES == ist.STAGES + (ist.DUPLICATE,)


# ===========================================================================
# update_status -- rejected/failed require a non-blank detail (ca's IngestStatus rule)
# ===========================================================================
def test_update_status_writes_a_promoted_row_with_no_detail_required():
    cm, conn, _ = _fake_conn()
    with mock.patch.object(ist, "_pg_connect", return_value=cm):
        ist.update_status(_INGEST_ID, ist.PROMOTED, detail="record abc")
    conn.commit.assert_called_once()


@pytest.mark.parametrize("stage", [ist.REJECTED, ist.FAILED])
def test_update_status_refuses_rejected_or_failed_without_a_detail(stage):
    with mock.patch.object(ist, "_pg_connect") as pg:
        with pytest.raises(ValueError):
            ist.update_status(_INGEST_ID, stage)
        pg.assert_not_called()


@pytest.mark.parametrize("stage", [ist.REJECTED, ist.FAILED])
def test_update_status_refuses_rejected_or_failed_with_a_blank_detail(stage):
    with mock.patch.object(ist, "_pg_connect") as pg:
        with pytest.raises(ValueError):
            ist.update_status(_INGEST_ID, stage, detail="   ")
        pg.assert_not_called()


def test_update_status_refuses_an_unknown_stage():
    with mock.patch.object(ist, "_pg_connect") as pg:
        with pytest.raises(ValueError):
            ist.update_status(_INGEST_ID, "classified", detail="x")
        pg.assert_not_called()


# ===========================================================================
# get_status_for -- existence-oracle-safe caller scoping (mirrors
# test_resolution_lookup_is_caller_scoped_not_an_existence_oracle exactly)
# ===========================================================================
def test_get_status_for_owner_gets_the_row():
    row = {"id": "abc123", "sha256": "abc123", "kind": "pdf", "status": "received",
           "submitted_by": "alice@example.com", "on_behalf_of": "alice@example.com"}
    cm, _, _ = _fake_conn(row)
    with mock.patch.object(ist, "_pg_connect", return_value=cm):
        out = ist.get_status_for("abc123", caller_id="alice@example.com")
    assert out["status"] == "received"


def test_get_status_for_non_owner_gets_none_not_another_users_row():
    """SECURITY property: the query is scoped to submitted_by OR on_behalf_of = caller, so a
    caller who is neither can only ever get None -- indistinguishable from 'no such ingest'.
    A non-owner probing another user's ingest id must not be able to confirm it exists."""
    cm, _, cur = _fake_conn(None)
    with mock.patch.object(ist, "_pg_connect", return_value=cm):
        out = ist.get_status_for("SOMEONE-ELSES-INGEST", caller_id="mallory@example.com")
    assert out is None
    sql, params = cur.execute.call_args[0][0], cur.execute.call_args[0][1]
    assert "submitted_by = %s" in sql and "on_behalf_of = %s" in sql, f"SQL was: {sql}"
    assert "mallory@example.com" in params


def test_get_status_for_rejects_empty_inputs_without_touching_the_db():
    with mock.patch.object(ist, "_pg_connect") as pg:
        assert ist.get_status_for("", caller_id="alice@example.com") is None
        assert ist.get_status_for("abc123", caller_id="") is None
        pg.assert_not_called()


if __name__ == "__main__":
    import sys
    failed = 0
    for name, fn in sorted((k, v) for k, v in globals().items() if k.startswith("test_")):
        try:
            fn()
            print(f"PASS {name}")
        except BaseException as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {exc!r}")
    print(f"\n{failed} failed")
    sys.exit(1 if failed else 0)
