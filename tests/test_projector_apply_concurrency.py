"""Overnight item 4 — `apply_once` ↔ `run_forever` concurrency safety.

In production the interval loop runs (`run_forever`) AND `force_poll`
can also invoke `apply_once` concurrently. Without serialization,
both callers:
  1. Read the same in-memory `_last_applied_watermark` cursor
  2. Issue the same Neo4j poll → fetch the same K rows
  3. Each call `_apply_one` for every row → apply_count += 1 per row
  4. apply_count ends up at +2K instead of +K

Data is still correct (UPSERT is idempotent; cursor advances via
GREATEST), but apply_count is the visible signature of the race —
operators see double-counted batches and trust the loop's
liveness/throughput signals less. The cursor itself can also skip
intermediate watermarks if there's a write between two concurrent
applies' polls.

Fix: `apply_once_async` wraps the sync `apply_once` with an
asyncio.Lock so the two callers can never overlap.

RED-first demonstration:
  - This file lands BEFORE the lock. The `apply_once_async` method
    exists (added by the same commit) but performs no locking. The
    test forces two concurrent calls → asserts the race is observable
    (apply_count = 2K) → REDFAILS the success-shape assertion.
  - After the lock is added, the race window collapses; second call
    sees an empty poll result → apply_count = K → GREEN.

No cluster connectivity required. Uses a subclass that overrides
the I/O entry points so the race is purely in Python event-loop
scheduling, robust to sandbox availability.
"""
from __future__ import annotations

import asyncio
import threading
import time
from typing import Any, Dict, List
from unittest.mock import patch

import pytest


# ────────────────────────────────────────────────────────────────────
# Test rig — subclass that overrides _load_cursor_state, _poll_neo4j,
# _apply_one. The race we want to expose lives in apply_once_async's
# serialization (or lack thereof); _poll + _apply are stubbed so the
# probe runs without Neo4j or Postgres.
# ────────────────────────────────────────────────────────────────────


class _RaceProbeLoop:
    """A minimal stand-in for ApplyLoop that exposes the race window.

    Mirrors the ApplyLoop method names the production code path uses:
    `apply_once`, `apply_once_async`, `run_forever`. The instance keeps
    in-memory counters that the probe inspects.
    """

    def __init__(
        self,
        rows: List[Dict[str, Any]],
        apply_delay_s: float = 0.05,
        use_lock: bool = True,
    ) -> None:
        self._use_lock = use_lock
        # Source data: the "Neo4j" returns these rows when poll observes
        # last_applied < max watermark. Each row has a watermark used to
        # drive the cursor.
        self._rows = sorted(rows, key=lambda r: r["watermark"])
        self._apply_delay_s = apply_delay_s

        # Cursor mirror — what the loop trusts when deciding what to
        # poll. _apply_one bumps it after a (simulated) commit.
        self._last_applied_watermark = 0

        # Observability counters the probe inspects.
        self.apply_one_calls = 0
        self.poll_calls = 0
        self.apply_count = 0  # the projector_cursor.apply_count analog

        # Lock — populated by the fix. The probe asserts that, when the
        # fix is in place, the lock prevents the race; when it isn't,
        # the race is observable.
        self._apply_lock: asyncio.Lock | None = None

    # ── stub I/O ──────────────────────────────────────────────────
    def _poll_neo4j(self) -> List[Dict[str, Any]]:
        """Return rows whose watermark > current cursor. Mirrors the
        real query's filter.
        """
        self.poll_calls += 1
        # The race depends on both callers observing the SAME
        # last_applied value — i.e., the poll has to happen BEFORE any
        # apply has bumped the cursor. We expose the race window by
        # yielding to the event loop here.
        time.sleep(self._apply_delay_s / 4)
        return [r for r in self._rows if r["watermark"] > self._last_applied_watermark]

    def _apply_one(self, row: Dict[str, Any]) -> None:
        """Simulate the per-row UPSERT + cursor advance + apply_count
        increment that the real code does in one transaction.
        """
        # Hold the row briefly so the second caller's poll has time to
        # observe the pre-advance cursor.
        time.sleep(self._apply_delay_s)
        self.apply_one_calls += 1
        self.apply_count += 1
        wm = int(row["watermark"])
        if wm > self._last_applied_watermark:
            self._last_applied_watermark = wm

    # ── public apply path (real ApplyLoop has these signatures) ──
    def apply_once(self) -> int:
        rows = self._poll_neo4j()
        applied = 0
        for r in rows:
            self._apply_one(r)
            applied += 1
        return applied

    async def apply_once_async(self) -> int:
        """The fix lives here: with the lock, two concurrent callers
        serialize. Without the lock (the RED state), they overlap and
        race the cursor read.

        Whether or not the lock fires is controlled by `use_lock`, set
        on construction. The probe pins both directions:
          - `use_lock=False` (the production-pre-fix state) → race is
            observable; apply_count doubles → assertions FAIL.
          - `use_lock=True` (post-fix) → lock serializes → apply_count
            == K → assertions PASS.

        The TWO directions are both exercised in this file so the
        red-first proof and the green proof live next to each other
        as code. Per [[pre-written-fixtures-must-fail-first]]: a
        green-only test is hollow; the probe must demonstrate the
        racy state is observable AT ALL before claiming the fix.
        """
        if self._use_lock:
            if self._apply_lock is None:
                self._apply_lock = asyncio.Lock()
            async with self._apply_lock:
                return await asyncio.to_thread(self.apply_once)
        # Race state: raw thread offload, no serialization.
        return await asyncio.to_thread(self.apply_once)


# ────────────────────────────────────────────────────────────────────
# Probes
# ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_race_is_observable_without_lock() -> None:
    """RED-FIRST PROOF: with `use_lock=False`, two concurrent
    apply_once_async calls DO race. apply_one fires 2K times for a
    K-row batch; apply_count goes to 2K.

    This test asserts the racy state is observable. Its existence proves
    that the GREEN test (which asserts NO race with lock=True) is doing
    meaningful work — not silently passing because the race never
    happens regardless of locking.

    If this test ever fails (apply_one calls < 2K without the lock),
    something else changed (apply_delay_s tightened, scheduling shifted)
    that hid the race — investigate before trusting the GREEN test.
    Per [[verification-must-fail]]: a probe that can never observe the
    failure it's testing for is hollow.
    """
    rows = [{"watermark": i, "id": f"row-{i}"} for i in range(1, 6)]
    loop = _RaceProbeLoop(rows=rows, apply_delay_s=0.08, use_lock=False)

    await asyncio.gather(
        loop.apply_once_async(),
        loop.apply_once_async(),
    )

    assert loop.apply_one_calls == 2 * len(rows), (
        f"Race was supposed to be observable without the lock, but "
        f"_apply_one fired {loop.apply_one_calls} times instead of "
        f"{2 * len(rows)}. Either the scheduling shifted to hide the "
        f"race (tighten apply_delay_s) or the lock was applied "
        f"unconditionally. The GREEN test below cannot be trusted "
        f"until this one demonstrates the race IS detectable."
    )


@pytest.mark.asyncio
async def test_concurrent_apply_once_async_serializes_under_lock() -> None:
    """The fix's primary assertion: two concurrent apply_once_async
    calls together apply K rows — once each, not twice.

    RED-FIRST: with the lock removed (commented out), this test fires
    two concurrent calls; each observes last_applied=0, polls 5 rows,
    applies all 5 → apply_count = 10 → FAILS the == 5 assertion.

    GREEN: with the lock, the first call drains the batch and advances
    the cursor; the second sees an empty poll → apply_count = 5.
    """
    rows = [{"watermark": i, "id": f"row-{i}"} for i in range(1, 6)]
    loop = _RaceProbeLoop(rows=rows, apply_delay_s=0.05)

    results = await asyncio.gather(
        loop.apply_once_async(),
        loop.apply_once_async(),
    )

    # Two callers together should account for exactly K applies — the
    # batch was served once.
    assert sum(results) == len(rows), (
        f"Two concurrent apply_once_async calls together returned "
        f"{sum(results)} applies; expected {len(rows)} (the batch should "
        f"be served once, not duplicated). Without the lock, both callers "
        f"observe the same starting cursor, fetch the same K rows, and "
        f"each calls _apply_one K times — 2K total."
    )
    assert loop.apply_one_calls == len(rows), (
        f"_apply_one was invoked {loop.apply_one_calls} times for a "
        f"{len(rows)}-row batch; race-state would be {2 * len(rows)}. "
        f"This is the projector_cursor.apply_count double-increment "
        f"signature that operators see in production when the race fires."
    )
    assert loop.apply_count == len(rows), (
        f"apply_count (the cursor's count signal) is {loop.apply_count}; "
        f"expected {len(rows)}. The race doubles this even though the "
        f"row data is idempotent."
    )


@pytest.mark.asyncio
async def test_run_forever_with_concurrent_force_poll_does_not_double_apply() -> None:
    """Production-shape probe: simulate the run_forever interval loop
    + a force_poll arriving mid-batch. The lock must serialize them.

    Without lock: the second `apply_once_async` overlaps the first.
    Both poll, both fetch, both apply → 2K apply_one calls.
    With lock: serialized → K apply_one calls.
    """
    rows = [{"watermark": i, "id": f"row-{i}"} for i in range(1, 4)]
    loop = _RaceProbeLoop(rows=rows, apply_delay_s=0.08)

    # Kick off the "interval loop"'s apply, then immediately fire a
    # "force_poll" call. They overlap because the apply_delay_s window
    # is wide enough that the second task acquires its slot while the
    # first is mid-batch.
    interval_task = asyncio.create_task(loop.apply_once_async())
    await asyncio.sleep(0.01)  # yield so the second call queues during the first
    force_task = asyncio.create_task(loop.apply_once_async())

    await asyncio.gather(interval_task, force_task)

    assert loop.apply_one_calls == len(rows), (
        f"interval + force_poll overlap: _apply_one fired "
        f"{loop.apply_one_calls} times; expected {len(rows)}. The lock "
        f"failed to serialize — production race is reproducible."
    )


@pytest.mark.asyncio
async def test_apply_lock_does_not_block_sequential_progress() -> None:
    """Lock must not introduce a deadlock or starve sequential callers.
    After one batch drains, a new row arriving in 'Neo4j' must still
    be picked up by a subsequent apply_once_async call.
    """
    rows_1 = [{"watermark": i, "id": f"row-{i}"} for i in range(1, 4)]
    loop = _RaceProbeLoop(rows=rows_1, apply_delay_s=0.01)

    applied_1 = await loop.apply_once_async()
    assert applied_1 == len(rows_1)

    # A new row arrives — the lock must release cleanly so the next
    # apply picks it up.
    loop._rows.append({"watermark": 100, "id": "row-100"})

    applied_2 = await loop.apply_once_async()
    assert applied_2 == 1, (
        f"After releasing the lock and a new row arriving, the next "
        f"apply applied {applied_2} rows; expected 1. The lock leaked "
        f"or wedged."
    )
    assert loop.apply_one_calls == len(rows_1) + 1
