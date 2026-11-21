"""A schema-lag error fails the projector batch; it never skips the artifact.

db-init (the SQL) is a post-upgrade hook, so it runs after the projector Deployment has
rolled. In that window an upsert names a column that does not exist yet (`intent_ms`, and
`duration_ms` before it). `apply_once` used to skip such a row and advance the cursor past it,
losing the answer from the projection for good. A missing column is not a bad artifact.
"""
from __future__ import annotations

import pathlib
import sys

import psycopg2
import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from iagent.projector.apply_loop import ApplyLoop  # noqa: E402


def _pg_error(code: str) -> psycopg2.Error:
    # pgcode is a read-only attribute on a real psycopg2 error; subclass to carry one.
    class _E(psycopg2.Error):
        pgcode = code
    return _E("boom")


def _loop(exc: BaseException):
    loop = ApplyLoop.__new__(ApplyLoop)
    loop.calls = {"skip": 0, "advance": 0}
    loop._resync_cursor_from_postgres = lambda: None
    loop._poll_neo4j = lambda: [{"id": "a1", "watermark": 7}]

    def _boom(art):
        raise exc

    loop._apply_one = _boom

    def _skip(**kw):
        loop.calls["skip"] += 1

    def _adv(w):
        loop.calls["advance"] += 1

    loop._record_skip = _skip
    loop._advance_cursor = _adv
    return loop


@pytest.mark.parametrize("code", ["42703", "42P01"])
def test_a_schema_lag_error_raises_and_is_neither_skipped_nor_advanced(code):
    err = _pg_error(code)
    loop = _loop(err)
    with pytest.raises(psycopg2.Error):
        loop.apply_once()
    assert loop.calls == {"skip": 0, "advance": 0}


@pytest.mark.parametrize("exc", [ValueError("bad json"), _pg_error("23505")])
def test_an_ordinary_bad_artifact_is_still_skipped_and_the_cursor_advances(exc):
    loop = _loop(exc)
    assert loop.apply_once() == 0
    assert loop.calls == {"skip": 1, "advance": 1}
