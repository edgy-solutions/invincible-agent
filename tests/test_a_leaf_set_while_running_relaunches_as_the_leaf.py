"""A leaf set while the run is in flight relaunches the row AS THE LEAF (architect ruling 2026-10-21).

doc-tools reads the kind ONLY from the drop's S3 sidecar (`{object_prefix}manifest.json`), so a PDF
drop whose leaf (pcn|pdn) is set while its Dagster run is in flight ran as `pdf` and stranded; and
every BFF "relaunch" (row -> `received`, `attempt` + 1, listed by GET /ingest/retries) re-read the SAME
sidecar. The fix: the BFF rewrites the sidecar to the leaf FIRST, then re-opens the row with reason
`leaf_applied`; `_ingest_leaf_relaunch_tick` does it for a row whose leaf was set in place once its
run has finished. The invariant: the sidecar is rewritten ONLY at a relaunch, so "sidecar kind == row
leaf" means "already applied" -> never relaunch again.

THE WRITES ARE THE REAL ONES: `list_leafed_relaunch_candidates`, `relaunch_as_leaf`, `set_leaf` and
`list_pending_retries` run as written against the in-memory interpreter of
tests/test_the_leaf_is_on_the_row_and_the_dropper_can_correct_it.py (each WHERE guard applies only if
its text is in the SQL), the sidecar is a fake S3, and Dagster is a fake `_get_run_status`.

Run: PYTHONPATH="src;." python -m pytest tests/test_a_leaf_set_while_running_relaunches_as_the_leaf.py -q -p no:cacheprovider
"""
from __future__ import annotations

import asyncio
import json
import time as _real_time
import types
from unittest import mock

import pytest

pytest.importorskip("httpx")
pytest.importorskip("fastapi")

from src.iagent import content_kinds as ck  # noqa: E402
from src.iagent import gateway  # noqa: E402
from src.iagent import ingest_status as ist  # noqa: E402
from tests.test_the_leaf_is_on_the_row_and_the_dropper_can_correct_it import (  # noqa: E402,F401
    ALICE, DOCTOOLS, ID, PREFIX, SIDECAR_KEY, _as, _leaf, db, drop_sidecar, put_sidecar,
    read_sidecar,
)
from tests._can_drop_open import can_drop_open  # noqa: F401

pytestmark = pytest.mark.usefixtures("can_drop_open")

RUN = "run-1"


def _dagster(monkeypatch, answers):
    """`answers`: run_id -> the `runOrError` answer (a dict) the fake Dagster gives; mutable, so a
    test can flip a run to SUCCESS between ticks. Unknown run ids answer {} (unreachable)."""
    async def _get_run_status(run_id):
        return answers.get(run_id, {})

    monkeypatch.setattr(gateway, "_get_run_status", _get_run_status)
    return answers


def _run(status):
    return {"__typename": "Run", "status": status}


def _tick():
    return asyncio.run(gateway._ingest_leaf_relaunch_tick())


def _inflight(db, monkeypatch, *, pick, status="extracting", run_id=RUN, run="SUCCESS", **row):
    """THE 9d8e8a6f SHAPE: a pdf drop whose run is (or was) in flight; with `pick`, ALICE picks pcn
    while the row is at `received` (recorded in place), then the run posts `status` with its run id."""
    db.add(status="received", **row)
    if pick:
        r = _leaf(_as(ALICE), "pcn")
        assert r.status_code == 200, r.text
        assert r.json()["stage"] == "received"
        assert db.s3.puts == []  # the pick in place writes no sidecar: only a relaunch does
    db.rows[ID]["status"] = status
    db.rows[ID]["run_id"] = run_id
    return _dagster(monkeypatch, {RUN: _run(run)} if run else {})


@pytest.mark.parametrize("pick", [True, False], ids=["leaf_picked", "no_leaf_control"])
def test_a_leaf_picked_while_the_run_was_in_flight_relaunches_as_the_leaf_and_a_no_leaf_row_does_not(
        db, monkeypatch, pick):
    """Defends the whole path with no human act after the pick. The pair shares its setup, so the
    control (no pick) differs ONLY in the leaf: the leafed row is relaunched once (sidecar rewritten
    to pcn first, row re-opened at received, attempt 2, reason leaf_applied, leaf columns kept, and
    listed to doc-tools as `{id}-a2` with reason leaf_applied); the leafless one is untouched -- the
    pass never relaunches a row that has no leaf, and writes no sidecar."""
    _inflight(db, monkeypatch, pick=pick)
    before_row, before_side = db.snap(), db.s3.objects[SIDECAR_KEY]
    reg = ck.by_kind("pcn")
    # the candidate listing itself: a row with no leaf is never a candidate, whatever the sidecar says
    assert [c["id"] for c in ist.list_leafed_relaunch_candidates()] == ([ID] if pick else [])
    done = _tick()
    if not pick:
        assert done == []
        assert db.snap() == before_row and db.s3.objects[SIDECAR_KEY] == before_side
        assert db.s3.puts == []
        return
    assert done == [ID]
    row = db.rows[ID]
    assert row["status"] == "received" and row["attempt"] == 2
    assert row["retry_reason"] == ist.REASON_LEAF_APPLIED
    assert row["content_kind"] == "pcn" and row["leaf_source"] == "corrected"
    assert row["leaf_set_by"] == ALICE
    side = read_sidecar(db.s3)
    assert side["content_kind"] == "pcn" and side["domain_type"] == reg.domain
    assert side["metadata"]["content_kind"] == "pcn"
    old = drop_sidecar()
    for k in set(old) - {"content_kind", "domain_type", "metadata"}:
        assert side[k] == old[k], k
    assert db.s3.puts == [SIDECAR_KEY]
    lst = _as(DOCTOOLS).get("/ingest/retries")
    assert lst.status_code == 200, lst.text
    assert [(e["ingest_id"], e["attempt"], e["run_key"], e["content_kind"], e["reason"])
            for e in lst.json()["retries"]] == [(ID, 2, f"{ID}-a2", "pcn", "leaf_applied")]


@pytest.mark.parametrize("running", ["STARTED", "QUEUED"])
def test_a_run_still_running_is_not_relaunched_and_the_next_tick_after_it_ends_is(
        db, monkeypatch, running):
    """Defends fail-closed: a run that may still be reading the sidecar is never relaunched; the very
    next tick after Dagster says SUCCESS does."""
    answers = _inflight(db, monkeypatch, pick=True, run=running)
    before = db.snap()
    assert _tick() == []
    assert db.snap() == before and db.s3.puts == []
    answers[RUN] = _run("SUCCESS")
    assert _tick() == [ID]
    assert db.rows[ID]["attempt"] == 2


def test_a_second_tick_after_the_relaunch_does_nothing(db, monkeypatch):
    """Defends NO LOOP: once the sidecar names the leaf ("already applied"), the row -- which sits at
    received/extracting again with the same leaf -- is not relaunched again."""
    _inflight(db, monkeypatch, pick=True)
    assert _tick() == [ID]
    assert _tick() == []
    # even once the relaunched run is posted extracting and finished, the sidecar already says pcn
    db.rows[ID]["status"] = "extracting"
    db.rows[ID]["run_id"] = "run-2"
    _dagster(monkeypatch, {"run-2": _run("SUCCESS")})
    assert _tick() == []
    assert db.rows[ID]["attempt"] == 2 and db.s3.puts == [SIDECAR_KEY]


def test_a_declared_leaf_drop_whose_run_ended_silent_is_not_relaunched(db, monkeypatch):
    """Defends the other side of the sidecar-equals-leaf guard: a drop that DECLARED pcn (sidecar
    already pcn) whose leaf run ended without a stage post is the watchdog's, not this pass's."""
    db.add(status="extracting", content_kind="pcn", leaf_source="declared", run_id=RUN)
    put_sidecar(db.s3, content_kind="pcn", domain_type="SUSTAINMENT")
    _dagster(monkeypatch, {RUN: _run("SUCCESS")})
    before = db.snap()
    assert _tick() == []
    assert db.snap() == before and db.s3.puts == []


def test_a_timeout_failed_row_with_a_leaf_is_rescued_and_another_failure_is_not(db, monkeypatch):
    """Defends the failed arm: the watchdog's `timeout` is the BFF's own provisional mark, so a leafed
    row that stranded past the extracting timeout is relaunched (failure cleared); any other reason
    code is the pipeline's verdict and stays failed."""
    _inflight(db, monkeypatch, pick=True, status="failed")
    db.rows[ID]["failure"] = {"reason_code": "other_reason", "message": "x"}
    before = db.snap()
    assert _tick() == []
    assert db.snap() == before and db.s3.puts == []
    db.rows[ID]["failure"] = {"reason_code": "timeout", "message": "t"}
    assert _tick() == [ID]
    row = db.rows[ID]
    assert row["status"] == "received" and row["attempt"] == 2 and row["failure"] is None
    assert row["retry_reason"] == ist.REASON_LEAF_APPLIED


@pytest.mark.parametrize("case", ["unreachable", "run_not_found", "no_run_id"])
def test_a_run_nobody_can_vouch_for_finished_is_not_relaunched(db, monkeypatch, case):
    """Defends fail closed: Dagster unreachable ({}), RunNotFoundError, and a row with no run_id are
    never relaunched."""
    answers = _inflight(db, monkeypatch, pick=True, run_id=None if case == "no_run_id" else RUN)
    if case == "unreachable":
        answers[RUN] = {}
    elif case == "run_not_found":
        answers[RUN] = {"__typename": "RunNotFoundError", "message": "gone"}
    before = db.snap()
    assert _tick() == []
    assert db.snap() == before and db.s3.puts == []


def test_a_pick_at_awaiting_kind_rewrites_the_sidecar_at_once_and_reopens_the_row(db):
    """Defends (b): a held row has no run to wait for, so the pick itself rewrites the sidecar to the
    leaf, THEN re-opens the row (attempt 2, reason leaf_applied) -- no tick needed."""
    db.add(status="awaiting_kind", run_id=RUN)
    r = _leaf(_as(ALICE), "pcn")
    assert r.status_code == 200, r.text
    row = db.rows[ID]
    assert row["status"] == "received" and row["attempt"] == 2
    assert row["retry_reason"] == ist.REASON_LEAF_APPLIED and row["content_kind"] == "pcn"
    side = read_sidecar(db.s3)
    assert side["content_kind"] == "pcn" and side["metadata"]["content_kind"] == "pcn"
    assert side["domain_type"] == ck.by_kind("pcn").domain
    assert db.s3.puts == [SIDECAR_KEY]


def test_a_sidecar_that_cannot_be_written_refuses_the_pick_and_writes_nothing_to_the_row(db):
    """Defends sidecar-first: if the sidecar cannot be rewritten the pick is 503 sidecar_unwritable and
    the row is byte-unchanged (a re-opened row over an old sidecar would re-run as the old kind)."""
    db.add(status="awaiting_kind")
    db.s3.put_error = RuntimeError("s3 down")
    before = db.snap()
    r = _leaf(_as(ALICE), "pcn")
    assert r.status_code == 503, r.text
    assert "sidecar_unwritable" in r.text
    assert db.snap() == before


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now

    def __getattr__(self, name):
        return getattr(_real_time, name)


def _watchdog(monkeypatch, interval):
    calls = []

    async def _relaunch():
        calls.append(1)
        return []

    async def _backstop(older):
        return []

    async def _unidentified():
        return []

    monkeypatch.setattr(gateway, "_ingest_leaf_relaunch_tick", _relaunch)
    monkeypatch.setattr(gateway, "_ingest_leaf_backstop_tick", _backstop)
    monkeypatch.setattr(gateway, "_ingest_kind_unidentified_tick", _unidentified)
    monkeypatch.setattr(ist, "fail_stalled", lambda **kw: [])
    monkeypatch.setattr(gateway, "_leaf_relaunch_last_at", None)
    clock = _Clock()
    monkeypatch.setattr(gateway, "time", clock)
    monkeypatch.setenv("INGEST_LEAF_RELAUNCH_INTERVAL_SECONDS", str(interval))
    return calls, clock


def test_the_relaunch_pass_runs_on_its_own_interval_not_the_watchdogs(monkeypatch):
    """Defends the cadence: within one watchdog tick sequence the relaunch pass runs once, not again
    inside INGEST_LEAF_RELAUNCH_INTERVAL_SECONDS, and again after it."""
    calls, clock = _watchdog(monkeypatch, 60)
    asyncio.run(gateway._ingest_watchdog_tick(10, 10))
    assert len(calls) == 1
    clock.now += 59
    asyncio.run(gateway._ingest_watchdog_tick(10, 10))
    assert len(calls) == 1
    clock.now += 1
    asyncio.run(gateway._ingest_watchdog_tick(10, 10))
    assert len(calls) == 2


@pytest.mark.parametrize("interval", [0, -5])
def test_a_non_positive_interval_disables_the_relaunch_pass(monkeypatch, interval):
    """Defends the off switch: INGEST_LEAF_RELAUNCH_INTERVAL_SECONDS <= 0 never runs the pass."""
    calls, clock = _watchdog(monkeypatch, interval)
    for _ in range(2):
        clock.now += 1000
        asyncio.run(gateway._ingest_watchdog_tick(10, 10))
    assert calls == []


def test_a_persons_retry_clears_the_reason_and_a_relaunch_names_it():
    """Defends the label: `retry_failed`'s UPDATE clears retry_reason (a person's retry is never
    leaf_applied); `relaunch_as_leaf` writes it and touches no leaf column; it validates its input."""
    cur = mock.MagicMock()
    cur.__enter__.return_value = cur
    cur.fetchone.return_value = (2,)
    conn = mock.MagicMock()
    conn.__enter__.return_value = conn
    conn.cursor.return_value = cur
    with mock.patch.object(ist, "_pg_connect", return_value=conn):
        assert ist.retry_failed(ID) == 2
    sql = " ".join(cur.execute.call_args[0][0].split())
    assert "retry_reason = NULL" in sql
    with pytest.raises(ValueError):
        ist.relaunch_as_leaf(ID, leaf="pdf", from_status="received", expect_attempt=1)
    with pytest.raises(ValueError):
        ist.relaunch_as_leaf(ID, leaf="pcn", from_status="review", expect_attempt=1)


def test_the_migration_and_the_sql_file_agree_on_retry_reason():
    """Defends the mirror: the column is in both the in-code migration and the SQL file."""
    from pathlib import Path
    sql = (Path(__file__).resolve().parents[1] / "sql" / "create_ingest_status_projection.sql"
           ).read_text(encoding="utf-8")
    stmt = "ADD COLUMN IF NOT EXISTS retry_reason TEXT"
    assert stmt in sql and stmt in ist._MIGRATION_SQL


# --------------------------------------------------------------------------------------------
# a person's Retry rewrites the sidecar too (Part D)
# --------------------------------------------------------------------------------------------
def _failed_leafed(db, monkeypatch, **row):
    db.add(status="failed", content_kind="pcn", leaf_source="corrected", run_id=RUN,
           failure={"reason_code": "pipeline", "message": "x"}, **row)
    return _dagster(monkeypatch, {RUN: _run("SUCCESS")})


def test_a_retry_of_a_leafed_failed_row_rewrites_the_sidecar_so_the_tick_adds_no_second_run(
        db, monkeypatch):
    """Defends the invariant "the sidecar is rewritten at every relaunch": a Retry reopens a failed
    row whose leaf was corrected in place over a pdf sidecar; the sensor's -aN launch reads the
    sidecar, so it is rewritten to the leaf by the Retry itself, and the 60 s pass then finds nothing
    (otherwise it would launch -aN+1, two runs and the first the wrong kind)."""
    _failed_leafed(db, monkeypatch)
    r = _as(ALICE).post(f"/ingest/{ID}/retry")
    assert r.status_code == 200, r.text
    assert db.rows[ID]["status"] == "received" and db.rows[ID]["attempt"] == 2
    assert db.rows[ID]["retry_reason"] is None
    side = read_sidecar(db.s3)
    assert side["content_kind"] == "pcn" and side["domain_type"] == ck.by_kind("pcn").domain
    assert side["metadata"]["content_kind"] == "pcn"
    assert _tick() == []
    assert db.rows[ID]["attempt"] == 2


def test_a_retry_whose_sidecar_cannot_be_written_is_503_and_the_row_stays_failed(db, monkeypatch):
    """Defends sidecar-first on Retry: no rewrite, no reopen -- the row is byte-unchanged."""
    _failed_leafed(db, monkeypatch)
    db.s3.put_error = RuntimeError("s3 down")
    before = db.snap()
    r = _as(ALICE).post(f"/ingest/{ID}/retry")
    assert r.status_code == 503 and "sidecar_unwritable" in r.text, r.text
    assert db.snap() == before


def test_a_retry_of_a_failed_row_with_no_leaf_touches_no_sidecar(db):
    """Control for the pair above: a pdf row (no leaf) is reopened exactly as before and no
    sidecar is written."""
    db.add(status="failed", content_kind="pdf", failure={"reason_code": "pipeline", "message": "x"})
    r = _as(ALICE).post(f"/ingest/{ID}/retry")
    assert r.status_code == 200, r.text
    assert db.rows[ID]["status"] == "received" and db.rows[ID]["attempt"] == 2
    assert db.s3.puts == []
