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


def test_record_received_writes_the_declared_content_kind_not_only_the_file_format():
    """review-audience fix: `content_kind` (the DECLARED, registry-level kind) is a column of
    its own, separate from `kind` (the file format). Omitted, it defaults to None (old-row
    shape); declared, it is both returned AND passed to the INSERT."""
    cm, conn, cur = _fake_conn()
    with mock.patch.object(ist, "_pg_connect", return_value=cm):
        row = ist.record_received(ingest_id=_INGEST_ID, sha256="abc123", kind="pdf",
                                   object_prefix="ingress-user/pdf/abc123/",
                                   submitted_by="alice@example.com", on_behalf_of="alice@example.com",
                                   source="notice.pdf", content_kind="pcn")
    assert row["content_kind"] == "pcn"
    assert row["kind"] == "pdf", "kind stays the file format, unchanged"
    sql, params = cur.execute.call_args[0][0], cur.execute.call_args[0][1]
    assert "content_kind" in sql
    assert params["content_kind"] == "pcn"


def test_record_received_defaults_content_kind_to_none_when_undeclared():
    cm, _, _ = _fake_conn()
    with mock.patch.object(ist, "_pg_connect", return_value=cm):
        row = ist.record_received(ingest_id=_INGEST_ID, sha256="abc123", kind="pdf",
                                   object_prefix="ingress-user/pdf/abc123/",
                                   submitted_by="alice@example.com", on_behalf_of="alice@example.com",
                                   source="notice.pdf")
    assert row["content_kind"] is None


_EVENT_INGEST_ID = "evt-" + "cd" * 32  # gateway.py's own shape: "evt-" + 64 lowercase hex


def test_record_received_accepts_kind_event_not_only_pdf_cad():
    """2026-10-06 (roll #20 item 4): the event branch's `kind` is 'event', not a file format --
    `record_received`'s own closed-set check (KINDS) is the only gate this value passes
    through, so KINDS had to widen even though 'event' is not a ContentKind leaf."""
    cm, conn, _ = _fake_conn()
    with mock.patch.object(ist, "_pg_connect", return_value=cm):
        row = ist.record_received(ingest_id=_EVENT_INGEST_ID, sha256="abc123", kind=ist.EVENT,
                                   object_prefix="", submitted_by="alice@example.com",
                                   on_behalf_of="alice@example.com", source="events")
    assert row["kind"] == "event"
    conn.commit.assert_called_once()


def test_record_received_on_conflict_does_nothing_and_returns_the_existing_row():
    """ON CONFLICT (id) DO NOTHING (roll #20 item 4): a repeat POST /ingest/events for an
    event_id that already has a row must not crash on the primary key -- it must leave the
    existing row alone and return WHAT IS ACTUALLY THERE (including its case_id), never the
    attempted-but-not-written dict."""
    existing = {
        "id": _EVENT_INGEST_ID, "sha256": "abc123", "kind": "event", "object_prefix": "",
        "submitted_by": "alice@example.com", "on_behalf_of": "alice@example.com",
        "source": "events", "status": "case_opened", "extracted_count": None,
        "extracted_total": None, "duplicate_of": None, "detail": None,
        "created_at": 1, "updated_at": 2, "content_kind": None, "case_id": "evt-001",
    }
    cm, conn, cur = _fake_conn()
    # rowcount == 0 is how the code detects "ON CONFLICT DO NOTHING actually fired"; the second
    # cursor (RealDictCursor, opened only on conflict) is what the positive-controlled fetch
    # below exercises. record_received's own code does `cur2 = conn.cursor(...); with cur2:
    # cur2.execute(...)` -- i.e. the SECOND conn.cursor() call's return value is used directly
    # as the context manager AND as the thing .execute/.fetchone are called on (unlike the
    # first conn.cursor() call, used as `with conn.cursor() as cur:`) -- so cur2 itself, a
    # MagicMock (which supports __enter__/__exit__ out of the box), is what goes in the second
    # slot below, never a separate context-manager wrapper around it.
    cur.rowcount = 0
    cur2 = mock.MagicMock()
    cur2.fetchone.return_value = existing
    first_cm = mock.MagicMock()
    first_cm.__enter__ = mock.Mock(return_value=cur)
    first_cm.__exit__ = mock.Mock(return_value=False)
    conn.cursor.side_effect = [first_cm, cur2]
    with mock.patch.object(ist, "_pg_connect", return_value=cm):
        row = ist.record_received(ingest_id=_EVENT_INGEST_ID, sha256="abc123", kind=ist.EVENT,
                                   object_prefix="", submitted_by="alice@example.com",
                                   on_behalf_of="alice@example.com", source="events")
    assert row["id"] == _EVENT_INGEST_ID
    assert row["status"] == "case_opened", "the row ACTUALLY there, not the attempted 'received'"
    assert row["case_id"] == "evt-001"
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
#
# 2026-10-03 (ingest/origin seam, lane/01-seam): SDK 0.9.7's INGEST_STAGES renamed its third
# rung 'awaiting_disposition' -> 'review' -- this repo's AWAITING_DISPOSITION/'awaiting_
# disposition' is renamed to match. `REVIEW` is therefore no longer an old, dropped name: it
# is the CURRENT third rung, so the old "not hasattr(ist, 'REVIEW')" assertion below is
# retired along with it (CLASSIFIED/EXTRACTED/STATUSES are unrelated and still gone).
# ===========================================================================
def test_the_stage_vocabulary_is_cas_six_stages_in_order():
    assert ist.STAGES == ("received", "extracting", "review", "promoted",
                          "rejected", "failed")
    assert not hasattr(ist, "CLASSIFIED")
    assert not hasattr(ist, "EXTRACTED")
    assert not hasattr(ist, "STATUSES"), "nothing in-repo imports the old alias; dropped, not kept"


def test_the_stage_vocabulary_matches_the_sdk_directly():
    """Seal against ca's SDK tuple ITSELF (iagent_mesh.ingest.INGEST_STAGES), never a restated
    literal -- so a future SDK rename reds this test instead of silently drifting out of step,
    the same hazard the module docstring's 'mirrored here rather than imported' already names."""
    from iagent_mesh.ingest import INGEST_STAGES

    assert ist.STAGES == INGEST_STAGES


def test_duplicate_case_opened_and_awaiting_origin_stay_out_of_band():
    """Three out-of-band statuses, each a legal `update_status` target and none a rung on the
    STAGES ladder (sealed separately against the SDK's own tuple above): `duplicate`;
    `case_opened` (roll #20 item 4, the event branch's own next step after `received`);
    `awaiting_origin` (architect ruling 2026-10-02, a deliberately domainless kind at review)."""
    assert ist.ALL_STATUSES == ist.STAGES + (ist.DUPLICATE, ist.CASE_OPENED, ist.AWAITING_ORIGIN)
    assert ist.CASE_OPENED not in ist.STAGES
    assert ist.AWAITING_ORIGIN not in ist.STAGES


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


def test_update_status_accepts_case_opened_and_writes_the_case_id():
    """Requirement 9 (roll #20 item 4): case_opened is a legal update_status target (it is in
    ALL_STATUSES though not in STAGES), and `case_id` rides along in the SAME write, COALESCEd
    like detail/extracted_count so a later stage move never has to restate it."""
    cm, conn, cur = _fake_conn()
    with mock.patch.object(ist, "_pg_connect", return_value=cm):
        ist.update_status(_INGEST_ID, ist.CASE_OPENED, case_id="evt-001")
    conn.commit.assert_called_once()
    sql, params = cur.execute.call_args[0][0], cur.execute.call_args[0][1]
    assert "case_id = COALESCE(%s, case_id)" in sql, f"SQL was: {sql}"
    assert params[0] == "case_opened"
    assert "evt-001" in params


def test_update_status_still_refuses_an_unknown_stage_after_case_opened_was_added():
    """Positive control for the test above: widening ALL_STATUSES to admit case_opened must not
    have widened it to admit everything -- an unrecognized stage name is still refused."""
    with mock.patch.object(ist, "_pg_connect") as pg:
        with pytest.raises(ValueError):
            ist.update_status(_INGEST_ID, "case_closed", detail="x")
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


def test_get_status_for_includes_case_id_when_present():
    row = {"id": "evt-001-row", "sha256": "abc123", "kind": "event", "status": "case_opened",
           "submitted_by": "alice@example.com", "on_behalf_of": "alice@example.com",
           "case_id": "evt-001"}
    cm, _, cur = _fake_conn(row)
    with mock.patch.object(ist, "_pg_connect", return_value=cm):
        out = ist.get_status_for("evt-001-row", caller_id="alice@example.com")
    assert out["case_id"] == "evt-001"
    sql = cur.execute.call_args[0][0]
    assert "case_id" in sql, f"SQL was: {sql}"


# ---------------------------------------------------------------------------
# get_status_for against a REAL sqlite WHERE clause (not a string match on the SQL)
# ---------------------------------------------------------------------------
class _SqliteCursor:
    def __init__(self, db):
        self._cur = db.cursor()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=()):
        self._cur.execute(sql.replace("%s", "?"), tuple(params))

    def fetchone(self):
        row = self._cur.fetchone()
        if row is None:
            return None
        return {d[0]: v for d, v in zip(self._cur.description, row)}


class _SqliteConn:
    def __init__(self, db):
        self._db = db

    def cursor(self, cursor_factory=None):
        return _SqliteCursor(self._db)


class _SqliteConnCm:
    def __init__(self, db):
        self._conn = _SqliteConn(db)

    def __enter__(self):
        return self._conn

    def __exit__(self, *exc):
        return False


def _status_columns():
    """The column list get_status_for SELECTs, parsed from the statement it executes."""
    cm, _, cur = _fake_conn(None)
    with mock.patch.object(ist, "_pg_connect", return_value=cm):
        ist.get_status_for("x", caller_id="y")
    sql = cur.execute.call_args[0][0]
    head = sql.split("FROM", 1)[0].split("SELECT", 1)[1]
    return [c.strip() for c in head.split(",") if c.strip()]


_OTHER_STAGE = ist.RECEIVED
_ROWS = [
    # id, submitted_by, on_behalf_of, status, origin_suggestion
    ("A", "alice", None, ist.AWAITING_ORIGIN, None),
    ("B", "svc-dropper", "bob", ist.AWAITING_ORIGIN, '{"suggested": {"owner_domain": "X"}}'),
    ("C", "carol", "mallory", _OTHER_STAGE, None),
    ("D", "mallory", None, ist.AWAITING_ORIGIN, None),
]


@pytest.fixture
def scoped_status():
    """Call the REAL ist.get_status_for over an in-memory sqlite table of the fixture rows."""
    import sqlite3

    db = sqlite3.connect(":memory:")
    cols = _status_columns()
    db.execute("CREATE TABLE ingest_status_projection (%s)" % ", ".join(f"{c} TEXT" for c in cols))
    for rid, sub, obo, status, sugg in _ROWS:
        vals = {"id": rid, "submitted_by": sub, "on_behalf_of": obo, "status": status,
                "origin_suggestion": sugg}
        db.execute(
            "INSERT INTO ingest_status_projection (%s) VALUES (%s)"
            % (", ".join(vals), ", ".join("?" for _ in vals)),
            tuple(vals.values()),
        )

    def call(ingest_id, caller):
        with mock.patch.object(ist, "_pg_connect", return_value=_SqliteConnCm(db)):
            return ist.get_status_for(ingest_id, caller_id=caller)

    yield call
    db.close()


def test_get_status_for_submitter_gets_own_row(scoped_status):
    out = scoped_status("A", "alice")
    assert out is not None and out["id"] == "A"


def test_get_status_for_on_behalf_of_principal_gets_the_row_with_parsed_suggestion(scoped_status):
    out = scoped_status("B", "bob")
    assert out is not None and out["id"] == "B"
    assert out["origin_suggestion"] == {"suggested": {"owner_domain": "X"}}


@pytest.mark.parametrize("ingest_id,caller", [
    ("A", "mallory"), ("B", "mallory"),
    ("B", "alice"), ("C", "alice"), ("D", "alice"),
])
def test_get_status_for_non_owner_gets_none_not_another_users_row(scoped_status, ingest_id, caller):
    """SECURITY: a caller who is neither submitted_by nor on_behalf_of gets None --
    indistinguishable from 'no such ingest' (existence-oracle safe). The WHERE clause decides."""
    out = scoped_status(ingest_id, caller)
    assert out is None
    # a leaked row (right or wrong) must red, never pass
    assert out is None or out["id"] == ingest_id


@pytest.mark.parametrize("ingest_id,caller", [("C", "mallory"), ("D", "mallory")])
def test_get_status_for_control_same_caller_is_admitted_where_scope_admits(scoped_status, ingest_id, caller):
    """Control: mallory is on_behalf_of C and submitter of D, so she gets exactly that row --
    the None above is the WHERE deciding, not an empty table."""
    out = scoped_status(ingest_id, caller)
    assert out is not None and out["id"] == ingest_id


@pytest.mark.parametrize("caller", ["alice", "bob", "carol", "mallory", "svc-dropper"])
def test_get_status_for_unknown_id_is_none_for_every_caller(scoped_status, caller):
    assert scoped_status("NO-SUCH-ID", caller) is None


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
