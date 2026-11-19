"""#443 follow-up (gov's should-fix): the strict clear of a stale receipt domain belongs where a task
would be FILED, not where one is FOUND.

`_clear_stale_receipt_domain` used to run before `task_exists`. A call that found the task already
open filed nothing, yet a clear that could not land answered it 503 "nothing was filed; retry" (or
`filed: False` on the origin path). It now runs immediately before `register_task`:

  * claim: an open task + a stored domain that differs + a store that cannot clear -> the call
    answers ALREADY_FILED (the post-filing note repairs or logs; it never refuses);
  * control: a task WOULD be filed + the same store -> still 503 `receipt_domain_unwritten`, and
    nothing is registered (the fail-closed step is intact, only its position moved);
  * control: a task would be filed and the clear lands -> it lands BEFORE the registration.

The position is also sealed on the source, so a mutant that puts the call back above `task_exists`
goes red here (and the behaviour tests go red with it)."""
from __future__ import annotations

import asyncio
import inspect

import pytest

pytest.importorskip("httpx")
pytest.importorskip("fastapi")
from fastapi import HTTPException  # noqa: E402

from src.iagent import gateway  # noqa: E402
from src.iagent import human_tasks as ht  # noqa: E402
from src.iagent import ingest_status as ist  # noqa: E402
from tests.test_promotion_filing_is_a_function_of_state import (  # noqa: E402,F401
    _ID, _REF, world,
)

_DOMAIN = "SUSTAINMENT"
_STORED = "OLDDOMAIN"            # differs from the task's domain: the clear has work to do


def _call(world):
    return asyncio.run(gateway._file_or_find_document_promotion_task(
        _ID, world.row, requested_by="svc:doc-tools", extraction_ref=_REF, domain=_DOMAIN))


def _row_at_review(world):
    world.row.update(status="review", extraction_ref=_REF, domain=_STORED)


def _open_task(world, monkeypatch):
    task_id = gateway._promotion_task_id(_ID, 0)
    world.registered.append({"task_id": task_id})
    monkeypatch.setattr(ht, "get_open_task_payload", lambda t: {"content_kind": "pdf"})
    return task_id


def _store(monkeypatch, *, clear_works):
    events: list = []

    def clear(i):
        events.append("clear")
        if not clear_works:
            raise RuntimeError("db down")
        return True

    def setd(i, d):
        events.append("set")
        raise RuntimeError("db down")

    monkeypatch.setattr(ist, "clear_domain", clear)
    monkeypatch.setattr(ist, "set_domain", setd)
    return events


def test_a_call_that_finds_the_task_open_is_not_refused_by_a_clear_that_cannot_land(world, monkeypatch):
    _row_at_review(world)
    task_id = _open_task(world, monkeypatch)
    _store(monkeypatch, clear_works=False)
    out = _call(world)                                         # no HTTPException
    assert out == (task_id, "ALREADY_FILED")
    assert [k["task_id"] for k in world.registered] == [task_id]   # and nothing more was filed


def test_control_a_task_that_would_be_filed_still_fails_closed_when_the_clear_cannot_land(world, monkeypatch):
    _row_at_review(world)
    _store(monkeypatch, clear_works=False)
    with pytest.raises(HTTPException) as exc:
        _call(world)
    assert exc.value.status_code == 503
    assert exc.value.detail["error"] == "receipt_domain_unwritten"
    assert world.registered == []                              # nothing was filed


def test_control_when_a_task_is_filed_the_clear_lands_before_the_registration(world, monkeypatch):
    _row_at_review(world)
    events = _store(monkeypatch, clear_works=True)
    real = ht.register_task

    def register(**kw):
        events.append("register")
        return real(**kw)

    monkeypatch.setattr(ht, "register_task", register)
    out = _call(world)
    assert out[1] == "FILED"
    assert events.index("clear") < events.index("register"), events


def test_the_clear_has_one_call_site_between_the_find_and_the_filing():
    src = inspect.getsource(gateway._file_or_find_document_promotion_task)
    assert src.count("_clear_stale_receipt_domain(") == 1
    at = src.index("_clear_stale_receipt_domain(")
    assert src.index("human_tasks.task_exists(") < at < src.index("human_tasks.register_task(")
