"""A row whose run has finished and that has NO leaf waits for a kind (architect ruling 2026-10-22):
"a row whose run has finished and that has NO leaf goes to awaiting_kind (reason: kind_not_identified).
Never left at extracting."

The live instance: a TI PDF drop's Dagster run ended SUCCESS after posting `extracting`, posted nothing
else, and the row sat at `extracting` (leafless) until a person picked a kind 18 minutes later. The
manifest-leaf backstop only acts when a manifest carries a `leaf` block, so a run that left none was
nobody's. `_ingest_kind_unidentified_tick` holds such a row at `awaiting_kind` with `hold_reason`
`kind_not_identified` (served by the status route only at that stage); a pick from there relaunches as
built on 10-21 (sidecar first, attempt + 1, reason `leaf_applied`).

THE WRITES ARE THE REAL ONES: `list_leafless_extracting`, `hold_for_kind`, `set_leaf` and
`list_pending_retries` run as written against the in-memory interpreter of
tests/test_the_leaf_is_on_the_row_and_the_dropper_can_correct_it.py (each WHERE guard applies only if
its text is in the SQL, so a mutant of the SQL is caught), the sidecar and the manifests are a fake
S3, and Dagster is a fake `_get_run_status`.

Run: PYTHONPATH="src;." python -m pytest tests/test_a_finished_run_with_no_leaf_waits_for_a_kind.py -q -p no:cacheprovider
"""
from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("httpx")
pytest.importorskip("fastapi")

from src.iagent import gateway  # noqa: E402
from src.iagent import ingest_status as ist  # noqa: E402
from tests.test_a_leaf_set_while_running_relaunches_as_the_leaf import (  # noqa: E402,F401
    RUN, _Clock, _dagster, _run, _watchdog,
)
from tests.test_the_leaf_is_on_the_row_and_the_dropper_can_correct_it import (  # noqa: E402,F401
    ALICE, DOCTOOLS, ID, PREFIX, SIDECAR_KEY, _as, _leaf, db, put_sidecar, read_sidecar,
)

KEY = f"{PREFIX}generated/doc_pdf/doc-tools@61f74dc/manifest.json"
DETAIL = "the run finished without identifying the kind; pick pcn or pdn"


def _manifests(db, monkeypatch, manifests=None):
    """The drop's S3 as the passes see it: the versioned manifests under `generated/` (`manifests`:
    key -> dict, default none) next to the fake sidecar store."""
    manifests = manifests or {}

    class S3:
        def list_objects_v2(self, **kw):
            return {"Contents": [{"Key": k, "LastModified": i} for i, k in enumerate(manifests)],
                    "IsTruncated": False}

        def get_object(self, **kw):
            return db.s3.get_object(**kw)

        def put_object(self, **kw):
            return db.s3.put_object(**kw)

    monkeypatch.setattr(gateway, "_build_s3_client", lambda: S3())
    monkeypatch.setattr(gateway, "_read_extraction_manifest", lambda k: manifests[k])


def _tick():
    return asyncio.run(gateway._ingest_kind_unidentified_tick())


def _ti(db, monkeypatch, *, run="SUCCESS", manifests=None, **row):
    """THE TI SHAPE: a leafless pdf drop at `extracting` with its run id, whose Dagster run is `run`
    (None = unreachable) and which left `manifests` (default none) behind."""
    db.add(status="extracting", run_id=RUN, **row)
    _manifests(db, monkeypatch, manifests)
    return _dagster(monkeypatch, {RUN: _run(run)} if run else {})


def _status(id=ID):
    r = _as(ALICE).get(f"/ingest/{id}/status")
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("run", ["SUCCESS", "FAILURE", "CANCELED"])
def test_a_finished_run_with_no_leaf_is_held_at_awaiting_kind_and_the_dropper_sees_why(
        db, monkeypatch, run):
    """Defends the ruling at the TI shape: a leafless pdf row whose run is terminal (success, failure
    or cancel alike) and left no manifest goes to awaiting_kind with reason kind_not_identified, no
    candidates and a detail, attempt unchanged and NO sidecar write; the dropper's status says so."""
    _ti(db, monkeypatch, run=run)
    assert _tick() == [ID]
    row = db.rows[ID]
    assert row["status"] == "awaiting_kind" and row["hold_reason"] == "kind_not_identified"
    assert row["leaf_candidates"] == "[]" and row["detail"] == DETAIL
    assert row["attempt"] == 1 and row["run_id"] == RUN and row["content_kind"] == "pdf"
    assert db.s3.puts == []
    body = _status()
    assert body["stage"] == "awaiting_kind" and body["hold_reason"] == "kind_not_identified"
    assert body["leaf"] is None and body["leaf_candidates"] == []


@pytest.mark.parametrize("run", ["STARTED", "QUEUED", None], ids=["started", "queued", "unreachable"])
def test_a_run_that_may_still_be_running_is_not_held(db, monkeypatch, run):
    """Control for the pair above: same row, same pass; only the run differs (still running, still
    queued, or Dagster unreachable) -> fail closed, the row is byte-unchanged."""
    _ti(db, monkeypatch, run=run)
    before = db.snap()
    assert _tick() == []
    assert db.snap() == before and db.s3.puts == []


def test_a_leafed_row_is_not_held_by_this_pass(db, monkeypatch):
    """Defends the leaf guard: a row that already carries a leaf (content_kind pcn) at extracting
    with a finished run is the relaunch pass's / the watchdog's, never held for want of a kind."""
    _ti(db, monkeypatch, content_kind="pcn", leaf_source="declared")
    before = db.snap()
    assert _tick() == []
    assert db.snap() == before


def test_a_row_that_cannot_have_a_leaf_is_untouched(db, monkeypatch):
    """Defends leaf-capability: a cad row (no content_kind, not a pdf) has no leaf to wait for, so a
    finished run leaves it alone."""
    _ti(db, monkeypatch, kind="cad", content_kind=None)
    before = db.snap()
    assert _tick() == []
    assert db.snap() == before


def test_a_row_with_no_run_id_is_untouched(db, monkeypatch):
    """Defends the run-id guard: a row that has posted no run id cannot be said to have a finished
    run; the extracting watchdog owns it."""
    _ti(db, monkeypatch, run="SUCCESS")
    db.rows[ID]["run_id"] = None
    before = db.snap()
    assert _tick() == []
    assert db.snap() == before


def test_the_hold_requires_the_run_the_caller_saw_finish(db):
    """Defends the race guard in the SQL: with `expect_run_id` the write matches only while the row's
    run is that run -- a relaunch that landed meanwhile (a new run id) wins and the row is unchanged;
    the matching run holds it."""
    db.add(status="extracting", run_id="new")
    before = db.snap()
    held = ist.hold_for_kind(ID, candidates=[], detail=DETAIL, expect_run_id="old",
                             from_statuses=[ist.EXTRACTING])
    assert held is False and db.snap() == before
    held = ist.hold_for_kind(ID, candidates=[], detail=DETAIL, expect_run_id="new",
                             from_statuses=[ist.EXTRACTING])
    assert held is True and db.rows[ID]["status"] == "awaiting_kind"
    assert db.rows[ID]["hold_reason"] == "kind_not_identified"


def test_a_hold_reason_must_be_a_code():
    """Defends the input: a reason that is not a REASON_CODE_RE code is a ValueError, before any SQL."""
    with pytest.raises(ValueError):
        ist.hold_for_kind(ID, candidates=[], detail="d", reason="Not A Code",
                          from_statuses=[ist.EXTRACTING])


def test_a_finished_run_whose_manifest_names_a_confident_title_relaunches_as_that_leaf(
        db, monkeypatch):
    """Defends parity with the manifest backstop: a finished run that DID leave a confident `leaf`
    block is relaunched as that kind (sidecar rewritten first, attempt 2, reason leaf_applied), not
    held as kind_not_identified."""
    _ti(db, monkeypatch, manifests={KEY: {"ingest_id": ID,
                                          "leaf": {"leaf": "PCN", "outcome": "title"}}})
    assert _tick() == [ID]
    row = db.rows[ID]
    assert row["status"] == "received" and row["attempt"] == 2
    assert row["content_kind"] == "pcn" and row["leaf_source"] == "title"
    assert row["retry_reason"] == ist.REASON_LEAF_APPLIED and row["hold_reason"] is None
    assert read_sidecar(db.s3)["content_kind"] == "pcn" and db.s3.puts == [SIDECAR_KEY]


def test_then_the_pick_relaunches_as_built_last_night(db, monkeypatch):
    """Defends item 3, "a pick from there relaunches as built last night": after the hold, the dropper
    picks pcn -> 200, stage received, attempt 2, reason leaf_applied, sidecar rewritten to pcn, and
    doc-tools' GET /ingest/retries lists `{id}-a2` with reason leaf_applied."""
    _ti(db, monkeypatch)
    assert _tick() == [ID]
    r = _leaf(_as(ALICE), "pcn")
    assert r.status_code == 200, r.text
    assert r.json()["stage"] == "received"
    row = db.rows[ID]
    assert row["status"] == "received" and row["attempt"] == 2
    assert row["retry_reason"] == ist.REASON_LEAF_APPLIED and row["content_kind"] == "pcn"
    assert read_sidecar(db.s3)["content_kind"] == "pcn" and db.s3.puts == [SIDECAR_KEY]
    lst = _as(DOCTOOLS).get("/ingest/retries")
    assert lst.status_code == 200, lst.text
    assert [(e["ingest_id"], e["run_key"], e["reason"]) for e in lst.json()["retries"]] == [
        (ID, f"{ID}-a2", "leaf_applied")]


def test_hold_reason_is_served_only_at_awaiting_kind_and_only_for_a_leaf_capable_row(db):
    """Defends the wire: the column can be stale after a pick, so the body says null at every stage but
    awaiting_kind; and the key is absent (no claim) for a cad row, like the other leaf keys."""
    db.add(status="extracting", hold_reason="kind_not_identified")
    body = _status()
    assert "hold_reason" in body and body["hold_reason"] is None
    db.rows[ID]["status"] = "awaiting_kind"
    assert _status()["hold_reason"] == "kind_not_identified"
    db.rows[ID].update(status="awaiting_kind", kind="cad", content_kind=None)
    cad = _status()
    assert "hold_reason" not in cad and "leaf" not in cad


def test_the_pass_runs_on_the_relaunch_cadence_and_its_off_switch(monkeypatch):
    """Defends the cadence: the new pass rides the relaunch pass's 60 s interval (once per interval,
    again after it), and INGEST_LEAF_RELAUNCH_INTERVAL_SECONDS <= 0 turns it off too."""
    calls, clock = _watchdog(monkeypatch, 60)
    seen = []

    async def _unidentified():
        seen.append(1)
        return []

    monkeypatch.setattr(gateway, "_ingest_kind_unidentified_tick", _unidentified)
    asyncio.run(gateway._ingest_watchdog_tick(10, 10))
    clock.now += 59
    asyncio.run(gateway._ingest_watchdog_tick(10, 10))
    assert len(calls) == 1 and len(seen) == 1
    clock.now += 1
    asyncio.run(gateway._ingest_watchdog_tick(10, 10))
    assert len(calls) == 2 and len(seen) == 2
    monkeypatch.setenv("INGEST_LEAF_RELAUNCH_INTERVAL_SECONDS", "0")
    clock.now += 1000
    asyncio.run(gateway._ingest_watchdog_tick(10, 10))
    assert len(calls) == 2 and len(seen) == 2


def test_the_migration_and_the_sql_file_agree_on_hold_reason():
    """Defends the mirror: the column is in both the in-code migration and the SQL file."""
    from pathlib import Path
    sql = (Path(__file__).resolve().parents[1] / "sql" / "create_ingest_status_projection.sql"
           ).read_text(encoding="utf-8")
    stmt = "ADD COLUMN IF NOT EXISTS hold_reason TEXT"
    assert stmt in sql and stmt in ist._MIGRATION_SQL
