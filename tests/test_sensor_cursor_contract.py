"""SENSOR CURSOR CONTRACT — chronological cursor + content-addressed run_key.

Both properties are adopted from dag-tools' S3SensorComponent so the two sensors AGREE
(`dag_tools/components/s3_sensor`: "chronological S3 keys using LastModified", run_key =
ETag + key). Two live incidents in one day are pinned here as named regressions:

  LEXICOGRAPHIC CURSOR lost work, silently and permanently. `StartAfter` skips everything
  sorting BELOW the cursor: a drop at `.../onsemi_look/...` was invisible behind a cursor
  at `.../onsemi_run6/...` ('l' < 'r'), and `.../inbound/generated/...` behind the same
  cursor ('g' < 'o'). Sort position is not arrival order.

  DERIVED RUN_KEY ate notices. run_key was `doc_id`, an LLM-extracted header field; when
  the header model degraded, every PDF in one inbox derived "inbound" and Dagster's
  run-key dedup discarded all but the first — no run, no failure, no log line. A
  model-derived value must never key deterministic machinery.

Run:  uv run --frozen python -m pytest tests/test_sensor_cursor_contract.py -q
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_SENSOR = _ROOT / "src" / "iagent" / "defs" / "extraction_review_sensor.py"
_spec = importlib.util.spec_from_file_location("ers_cursor", _SENSOR)
ers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ers)  # type: ignore[union-attr]

_T0 = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)


def _obj(key: str, minutes: int, etag: str = "aaa"):
    return {"Key": key, "ETag": f'"{etag}"', "LastModified": _T0 + timedelta(minutes=minutes)}


class _FakeS3:
    """Minimal paginator over a fixed object list."""

    def __init__(self, objects):
        self._objects = objects

    def get_paginator(self, _op):
        objs = self._objects

        class _P:
            def paginate(self, **_kw):
                return [{"Contents": list(objs)}]

        return _P()


def _list(objects, since=None):
    return ers._list_new_review_jsons(_FakeS3(objects), "b", "sustainment/", since)


# ── REGRESSION 1: a LOW-SORTING key that arrives LATER must still fire ──────
def test_late_arrival_that_sorts_low_is_not_skipped():
    """THE onsemi_look / inbound-generated incident. Under a lexicographic cursor these
    were invisible forever because their keys sort below it. Arrival order is what
    'new' means."""
    early = _obj("sustainment/inbound/onsemi_run6/generated/review.json", 0)
    late_low = _obj("sustainment/inbound/generated/review.json", 5)     # 'g' < 'o'
    cursor = ers._cursor_of(early)
    out = _list([early, late_low], since=cursor)
    assert [o["Key"] for o in out] == [late_low["Key"]], (
        "a later-arriving object whose key sorts BELOW the cursor was skipped — this is "
        "the lexicographic-cursor bug that silently lost two real notices"
    )


def test_second_low_sorting_incident_onsemi_look():
    early = _obj("sustainment/inbound/onsemi_run6/generated/review.json", 0)
    late_low = _obj("sustainment/inbound/onsemi_look/generated/review.json", 3)   # 'l' < 'r'
    out = _list([early, late_low], since=ers._cursor_of(early))
    assert [o["Key"] for o in out] == [late_low["Key"]]


# ── the other two of the three-object seal ─────────────────────────────────
def test_untouched_old_object_is_skipped():
    """Already-seen work must NOT re-fire on every tick."""
    seen = _obj("sustainment/a/generated/review.json", 0)
    assert _list([seen], since=ers._cursor_of(seen)) == []


def test_rewritten_object_fires_again():
    """A re-extraction REPLACES review.json: same key, later LastModified, new content.
    That is new work and must be seen."""
    first = _obj("sustainment/a/generated/review.json", 0, etag="aaa")
    rewritten = _obj("sustainment/a/generated/review.json", 9, etag="bbb")
    out = _list([first, rewritten], since=ers._cursor_of(first))
    assert [o["Key"] for o in out] == [rewritten["Key"]]
    assert ers._run_key_of(rewritten) != ers._run_key_of(first), (
        "a rewritten artifact must get a NEW run_key or Dagster dedup swallows the re-run"
    )


# ── REGRESSION 2: content-addressed identity, never a derived field ─────────
def test_two_notices_sharing_a_derived_doc_id_no_longer_collide():
    """THE "inbound" incident. Two DIFFERENT documents whose header pass failed both
    derived doc_id 'inbound'. Keyed on doc_id they deduped to one run and a real notice
    vanished; keyed on content+key they are distinct."""
    a = _obj("sustainment/inbound/generated/DiodesA_pdf/review.json", 1, etag="aaa")
    b = _obj("sustainment/inbound/generated/QorvoB_pdf/review.json", 2, etag="bbb")
    assert ers._run_key_of(a) != ers._run_key_of(b)


def test_identical_content_at_the_same_key_dedups():
    """Idempotency is preserved: the same artifact seen twice is ONE run."""
    o1 = _obj("sustainment/a/generated/review.json", 0, etag="same")
    o2 = _obj("sustainment/a/generated/review.json", 4, etag="same")
    assert ers._run_key_of(o1) == ers._run_key_of(o2)


def test_run_key_carries_content_and_location():
    o = _obj("sustainment/x/generated/review.json", 0, etag="deadbeef")
    rk = ers._run_key_of(o)
    assert "deadbeef" in rk and "sustainment/x/generated/review.json" in rk
    assert '"' not in rk, "S3 returns ETags quoted; the quotes must be stripped"


def test_cursor_is_time_ordered_not_name_ordered():
    """The property in one line: cursor ordering must follow arrival, not the alphabet."""
    zzz_early = _obj("sustainment/zzz/generated/review.json", 0)
    aaa_late = _obj("sustainment/aaa/generated/review.json", 1)
    assert ers._cursor_of(zzz_early) < ers._cursor_of(aaa_late)


def test_cursor_ties_are_broken_by_key():
    """Two artifacts landing in the same instant must not shadow each other."""
    x = _obj("sustainment/a/generated/review.json", 0)
    y = _obj("sustainment/b/generated/review.json", 0)
    assert ers._cursor_of(x) != ers._cursor_of(y)
    assert [o["Key"] for o in _list([x, y], since=ers._cursor_of(x))] == [y["Key"]]


def test_non_review_artifacts_are_ignored():
    keep = _obj("sustainment/a/generated/review.json", 1)
    noise = _obj("sustainment/a/generated/manifest.json", 2)
    assert [o["Key"] for o in _list([keep, noise])] == [keep["Key"]]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
