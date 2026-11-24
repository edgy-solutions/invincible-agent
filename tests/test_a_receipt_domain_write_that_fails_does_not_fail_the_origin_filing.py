"""Gov's must-fix on #407, through the ROUTE: the receipt-domain write runs AFTER the promotion
task is filed, so when it fails (the write AND its repair) the filing still answers as filed. The
retry of the same request files nothing new. Exactly one open task, and the answer names it.

The strict step is the clear BEFORE filing (`_clear_stale_receipt_domain`); the helper-level seals
are in tests/routing/test_the_receipt_carries_its_domain_so_the_scope_sits_in_the_query.py. This
file drives the origin path: `/ingest/{id}/retry` on a row at `awaiting_origin` with an accepted
origin (the harness is the filing-state test's own)."""
from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("httpx")
pytest.importorskip("fastapi")
from src.iagent import gateway  # noqa: E402
from src.iagent import ingest_status as ist  # noqa: E402
from tests.test_promotion_filing_is_a_function_of_state import (  # noqa: E402,F401
    ALICE, _ID, _REF, _as, _clear_overrides, _retry, world,
)





def _origin_world(world):
    world.row.update(status="awaiting_origin", extraction_ref=_REF)
    world.origin = {"owner_domain": "sustainment"}


def _accept(world):
    """The origin path's filing, as the accept route calls it: `{"promotion": <its answer>}`."""
    return {"promotion": asyncio.run(gateway._file_promotion_if_ready(_ID, requested_by=ALICE))}


def _store_down(monkeypatch, *, times):
    """set_domain and clear_domain both raise for the first `times` calls, then land."""
    calls = {"n": 0}

    def down(*a, **k):
        calls["n"] += 1
        if calls["n"] <= times:
            raise RuntimeError("db down")
        return True

    monkeypatch.setattr(ist, "set_domain", down)
    monkeypatch.setattr(ist, "clear_domain", down)
    return calls


_ALL_FAIL = gateway._RECEIPT_DOMAIN_ATTEMPTS + 1      # every write attempt, then the repair


def test_a_failed_post_filing_write_still_answers_filed_and_the_retry_files_nothing_more(world, monkeypatch):
    _origin_world(world)
    calls = _store_down(monkeypatch, times=_ALL_FAIL)

    first = _accept(world)
    assert first["promotion"]["filed"] is True, first               # the task IS filed: no refusal
    assert first["promotion"]["task_status"] == "FILED"
    assert calls["n"] == _ALL_FAIL                                  # the failure really happened
    assert world.row["status"] == "review"
    [kw] = world.registered
    task_id = kw["task_id"]
    assert first["promotion"]["task_id"] == task_id                 # the answer names the task

    again = _accept(world)                                          # the SAME request, retried
    assert again["promotion"] is None                               # a row at review is not touched
    assert [k["task_id"] for k in world.registered] == [task_id]    # exactly one open task


def test_a_failed_post_filing_write_does_not_fail_the_retry_route_either(world, monkeypatch):
    _origin_world(world)
    calls = _store_down(monkeypatch, times=_ALL_FAIL)
    r = _retry(world)
    assert r.status_code == 200, r.text                             # not 503 promotion_not_filed
    assert r.json()["task_status"] == "FILED" and r.json()["stage"] == "review"
    assert calls["n"] == _ALL_FAIL
    assert len(world.registered) == 1 and world.row["status"] == "review"


def test_control_nothing_failing_files_the_same_single_task(world, monkeypatch):
    _origin_world(world)
    calls = _store_down(monkeypatch, times=0)
    first = _accept(world)
    assert first["promotion"]["filed"] is True and first["promotion"]["task_status"] == "FILED"
    assert calls["n"] == 1                                          # one clean write, no repair
    [kw] = world.registered
    assert first["promotion"]["task_id"] == kw["task_id"]
    assert _accept(world)["promotion"] is None
    assert len(world.registered) == 1
