"""A FORMAT CHANGE TO A PERSISTED VALUE IS A MIGRATION — the cursor wedge, sealed.

THE LIVE DEFECT (found 2026-08-07, dead since the cursor change landed). The sensor switched from a
lexicographic `StartAfter` cursor (a bare S3 key) to a LastModified one (`<iso>|<key>`). The CODE
changed; the VALUE already sitting in Dagster's cursor storage did not. Every tick then compared an
ISO timestamp against a bare key:

    "2026-08-07T03:31:28+00:00|sustainment/…"  >  "sustainment/inbound/zz_look/…"   ->  False

`'2' < 's'`, so EVERY object was filtered out, forever — and the sensor reported *"no new extractions
(review.json) after cursor …"*, which is false and looks perfectly healthy. Sixteen artifacts sat
unprocessed behind a green-looking sensor.

**THE MIGRATION BUG WEARS THE COSTUME OF THE BUG THE MIGRATION FIXED.** The lexicographic cursor was
replaced *precisely because* its failure mode was silent skipping. The replacement reintroduced
silent skipping through its own changeover. Same symptom, opposite cause, invisible either way.

Run:  uv run --frozen python -m pytest tests/test_sensor_cursor_migration.py -q
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_SENSOR = _ROOT / "src" / "iagent" / "defs" / "extraction_review_sensor.py"
_spec = importlib.util.spec_from_file_location("ers_cursor", _SENSOR)
ers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ers)  # type: ignore[union-attr]

_OLD = "sustainment/inbound/zz_look/generated/zz_look_pdf/review.json"
_WHEN = datetime(2026, 7, 29, 22, 0, 59, 989000, tzinfo=timezone.utc)


class _S3:
    def __init__(self, known=None):
        self._known = known or {}

    def head_object(self, Bucket, Key):  # noqa: N803
        if Key not in self._known:
            raise RuntimeError("NoSuchKey")
        return {"LastModified": self._known[Key]}


# ===========================================================================
# THE TWO FORMS ARE DISTINGUISHABLE — everything else depends on this
# ===========================================================================
@pytest.mark.parametrize("cur,is_current", [
    (f"{_WHEN.isoformat()}|{_OLD}", True),
    (_OLD, False),                                   # the pre-migration form
    ("sustainment/inbound/x/review.json", False),
    ("not-a-timestamp|some/key", False),             # has the separator, not the shape
    ("", False),
])
def test_the_two_cursor_forms_are_told_apart(cur, is_current):
    """A probe that cannot tell the forms apart cannot migrate. Note `not-a-timestamp|some/key`:
    checking only for the `|` separator would call that current and re-wedge on a near-miss."""
    assert ers._is_current_cursor_form(cur) is is_current


# ===========================================================================
# THE MIGRATION — faithful, automatic, nothing re-fires
# ===========================================================================
def test_an_old_form_cursor_is_TRANSLATED_not_compared_across():
    """The old cursor named the last KEY processed, so that object's LastModified is exactly the
    timestamp the new cursor should carry. Faithful: nothing re-fires, nothing is newly skipped."""
    got = ers._migrate_cursor(_S3({_OLD: _WHEN}), "processing-artifacts", _OLD)
    assert got == f"{_WHEN.isoformat()}|{_OLD}"


def test_a_current_form_cursor_is_left_ALONE():
    cur = f"{_WHEN.isoformat()}|{_OLD}"
    assert ers._migrate_cursor(_S3(), "processing-artifacts", cur) == cur


@pytest.mark.parametrize("empty", ["", None, "   "])
def test_no_cursor_stays_no_cursor(empty):
    """A first run must not be mistaken for a wedge — the migration only fires on an alien VALUE."""
    assert ers._migrate_cursor(_S3(), "processing-artifacts", empty) is None


def test_an_UNTRANSLATABLE_cursor_RAISES_rather_than_guessing():
    """Both guesses are bad, so neither is taken: treating it as no-cursor re-fires the whole corpus
    into humans' queues, and adopting `now` skips anything in flight. An operator setting the cursor
    is a declared intent; either guess is an accident."""
    with pytest.raises(ers._CursorUnmigratable) as ei:
        ers._migrate_cursor(_S3(), "processing-artifacts", _OLD)
    msg = str(ei.value)
    assert "wedged, not idle" in msg, "the refusal must deny the 'idle' reading explicitly"
    assert "<iso8601>|<key>" in msg, "the refusal must state the FORM the operator has to supply"


# ===========================================================================
# THE REGRESSION ITSELF — the exact live comparison, pinned
# ===========================================================================
def test_the_live_wedge_is_reproduced_and_then_undone():
    """THE BUG, as it actually was in the sandbox. Without the migration the newest object compares
    BELOW a stored bare key and `_list_new_review_jsons` returns EMPTY; with it, the object is seen.

    This asserts the wedge first — a seal that only shows the fixed state cannot prove it fixed
    anything.
    """
    newest = {"Key": "sustainment/inbound/witness/generated/x/review.json",
              "LastModified": datetime(2026, 8, 7, 3, 31, 28, 333000, tzinfo=timezone.utc)}
    listing = [newest]

    # WEDGED: raw comparison against the pre-migration cursor.
    assert not (ers._cursor_of(newest) > _OLD), (
        "the wedge did not reproduce — an ISO timestamp must sort BELOW a key starting with a letter"
    )
    wedged = [o for o in listing if ers._cursor_of(o) > _OLD]
    assert wedged == [], "expected the pre-migration cursor to filter out everything"

    # UNWEDGED: the same comparison after translation.
    migrated = ers._migrate_cursor(_S3({_OLD: _WHEN}), "processing-artifacts", _OLD)
    seen = [o for o in listing if ers._cursor_of(o) > migrated]
    assert seen == [newest], "after migration the new artifact must be visible to the sensor"


# ===========================================================================
# THE SENSOR ITSELF — behavioural, because a source check does not bite
# ===========================================================================
# THIS SECTION EXISTS BECAUSE THE FIRST VERSION OF THIS FILE DID NOT BITE. It sealed the helpers and
# then asserted, against the sensor's SOURCE, that "CURSOR WEDGED" appeared before "no new
# extractions". Deleting the `_migrate_cursor` CALL — the realistic regression, and the exact state
# the sandbox was in — left both strings sitting in the surviving try/except and all thirteen tests
# stayed green. A grep proves presence; it never proves behaviour. So the sensor is driven.
class _ListS3:
    """S3 stand-in covering both calls the sensor makes: the listing and the migration's head."""

    def __init__(self, objects, known_heads=None):
        self._objects = objects
        self._heads = known_heads or {}

    def get_paginator(self, _op):
        objects = self._objects

        class _P:
            @staticmethod
            def paginate(**_kw):
                return [{"Contents": objects}]

        return _P()

    def head_object(self, Bucket, Key):  # noqa: N803
        if Key not in self._heads:
            raise RuntimeError("NoSuchKey")
        return {"LastModified": self._heads[Key]}

    def get_object(self, Bucket, Key):  # noqa: N803
        import json as _j
        body = _j.dumps({"doc_id": "IPCN25300X", "review_items": []}).encode()
        return {"Body": type("B", (), {"read": staticmethod(lambda: body)})()}


_NEWEST = {"Key": "sustainment/inbound/witness/generated/x/review.json",
           "ETag": '"abc123"',
           "LastModified": datetime(2026, 8, 7, 3, 31, 28, 333000, tzinfo=timezone.utc)}


def _drive(monkeypatch, cursor, s3):
    """Run the real sensor function against a stored cursor."""
    from dagster import build_sensor_context  # noqa: PLC0415

    monkeypatch.setattr(ers, "_s3_client", lambda: s3)
    ctx = build_sensor_context(cursor=cursor)
    return ers.extraction_review_sensor(ctx)


def test_the_SENSOR_sees_the_artifact_through_a_pre_migration_cursor(monkeypatch):
    """THE CLAIM. With the old-form cursor stored — the sandbox's actual state — the sensor must
    still dispatch the new artifact. Before the migration it dispatched NOTHING, for over a week."""
    s3 = _ListS3([_NEWEST], known_heads={_OLD: _WHEN})
    result = _drive(monkeypatch, _OLD, s3)
    keys = [r.run_key for r in getattr(result, "run_requests", []) or []]
    assert keys, (
        "the sensor dispatched nothing through a pre-migration cursor — that IS the wedge, and it is "
        "what 'no new extractions' was covering for"
    )
    assert _NEWEST["Key"] in keys[0]


def test_the_SENSOR_reports_a_WEDGE_not_an_IDLE_when_it_cannot_migrate(monkeypatch):
    """The defect was not the comparison — it was the MESSAGE. 'no new extractions' is what an idle
    sensor says, so the wedge was indistinguishable from health. These two must never share a
    phrasing, and the distinction is asserted on what the sensor RETURNS."""
    s3 = _ListS3([_NEWEST], known_heads={})          # the old cursor's object is gone
    result = _drive(monkeypatch, _OLD, s3)
    reason = getattr(result, "skip_message", None) or str(result)
    assert "WEDGED" in reason, f"a wedged cursor reported as {reason!r}"
    assert "no new extractions" not in reason, (
        "the wedge is being reported in the IDLE sensor's words — the exact lie this seal forbids")


def test_a_current_form_cursor_still_filters_normally(monkeypatch):
    """The migration must not become a bypass: a well-formed cursor AHEAD of the listing still skips,
    or the guard would have turned the wedge into a re-fire-everything loop."""
    ahead = f"{datetime(2026, 8, 8, tzinfo=timezone.utc).isoformat()}|zzz"
    result = _drive(monkeypatch, ahead, _ListS3([_NEWEST]))
    reason = getattr(result, "skip_message", None) or str(result)
    assert "no new extractions" in reason
    assert "WEDGED" not in reason


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
