"""The admission limit for durable answers (ADR-0072 5, ruled 2026-11-16).

At most `limit` answers run at once; the rest WAIT in arrival order and are never dropped. A
release hands its slot straight to the head waiter, so a newcomer can never barge past the
queue. The limit is a per-deployment value (`IAGENT_ANSWER_LIMIT`), read once when the gate is
built: a values change is applied by a pod roll. In-process: one gate per service replica.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time

logger = logging.getLogger("iagent.answer_admission")

ENV = "IAGENT_ANSWER_LIMIT"
QUEUE_ENV = "IAGENT_ANSWER_QUEUE_MAX"


class AdmissionWithdrawn(Exception):
    """A waiting answer was withdrawn before it was admitted."""


def answer_limit_from_env() -> int:
    """An int >= 1 as is; anything else gives 1 (an unsized deployment runs one answer at a time)."""
    raw = os.environ.get(ENV)
    try:
        val = int(str(raw).strip())
        if val >= 1:
            return val
    except (TypeError, ValueError):
        pass
    logger.warning("%s=%r is not an integer >= 1; admitting one answer at a time", ENV, raw)
    return 1


def answer_queue_max_from_env() -> int:
    """An int >= 0 as is (0 = no queue: anything over the limit is refused at once); anything
    else gives 0."""
    raw = os.environ.get(QUEUE_ENV)
    try:
        val = int(str(raw).strip())
        if val >= 0:
            return val
    except (TypeError, ValueError):
        pass
    logger.warning("%s=%r is not an integer >= 0; the queue holds none", QUEUE_ENV, raw)
    return 0


class _Entry:
    __slots__ = ("answer_id", "arrived_at", "seq", "fut")

    def __init__(self, answer_id: str, arrived_at: float, seq: int) -> None:
        self.answer_id, self.arrived_at, self.seq, self.fut = answer_id, arrived_at, seq, None

    def key(self) -> tuple:
        return (self.arrived_at, self.seq)


class AdmissionGate:
    def __init__(self, limit: int, queue_max: int = 0) -> None:
        self._limit = int(limit)
        self._queue_max = int(queue_max)
        self._holders: set[str] = set()
        self._waiters: list[_Entry] = []   # ordered by (arrived_at, seq)
        self._seq = 0
        self._refused: dict[str, dict] = {}
        self._withdrawn: dict[str, None] = {}

    # -- bookkeeping ---------------------------------------------------------------------
    def _find(self, answer_id: str) -> _Entry | None:
        for e in self._waiters:
            if e.answer_id == answer_id:
                return e
        return None

    def knows(self, answer_id: str) -> bool:
        return answer_id in self._holders or self._find(answer_id) is not None

    def _enqueue(self, answer_id: str, arrived_at: float) -> None:
        self._seq += 1
        e = _Entry(answer_id, float(arrived_at), self._seq)
        k = e.key()
        i = len(self._waiters)
        while i > 0 and self._waiters[i - 1].key() > k:
            i -= 1
        self._waiters.insert(i, e)

    @staticmethod
    def _bound(d: dict) -> None:
        while len(d) > 256:
            d.pop(next(iter(d)))

    # -- entry ---------------------------------------------------------------------------
    def try_enter(self, answer_id: str, arrived_at: float) -> str:
        """Synchronous and atomic: the ONLY place the full check happens."""
        if answer_id in self._holders:
            return "admitted"
        if self._find(answer_id) is not None:
            return "queued"
        if len(self._holders) < self._limit and not self._waiters:
            self._holders.add(answer_id)
            return "admitted"
        if len(self._waiters) >= self._queue_max:
            self._refused[answer_id] = {"reason": "queue_full", "limit": self._limit,
                                        "queue_max": self._queue_max}
            self._bound(self._refused)
            return "busy"
        self._enqueue(answer_id, arrived_at)
        return "queued"

    def reenter(self, answer_id: str, arrived_at: float) -> None:
        """A restarted answer the gate no longer knows: back in by its first arrival, never
        refused (an admitted answer is never dropped)."""
        if self.knows(answer_id):
            return
        if len(self._holders) < self._limit and not self._waiters:
            self._holders.add(answer_id)
        else:
            self._enqueue(answer_id, arrived_at)

    def refused(self, answer_id: str) -> dict | None:
        return self._refused.get(answer_id)

    async def acquire(self, answer_id: str, arrived_at: float | None = None) -> None:
        if answer_id in self._withdrawn:
            raise AdmissionWithdrawn(answer_id)
        if answer_id in self._holders:
            return
        if self._find(answer_id) is None:
            self.reenter(answer_id, time.time() if arrived_at is None else arrived_at)
            if answer_id in self._holders:
                return
        e = self._find(answer_id)
        if e.fut is None:
            e.fut = asyncio.get_running_loop().create_future()
        try:
            await e.fut
        except asyncio.CancelledError:
            # Cancelled while waiting: leave the queue. If the handoff already made this
            # answer a holder in the same tick, pass the slot on so it never leaks.
            self.leave(answer_id)
            raise

    # -- exit ----------------------------------------------------------------------------
    def release(self, answer_id: str) -> None:
        if answer_id not in self._holders:
            return
        self._holders.discard(answer_id)
        # Hand the slot straight to the lowest-(arrived_at, seq) waiter: it never passes
        # through "free".
        while self._waiters and len(self._holders) < self._limit:
            e = self._waiters.pop(0)
            self._holders.add(e.answer_id)
            if e.fut is not None and not e.fut.done():
                e.fut.set_result(None)

    def leave(self, answer_id: str) -> None:
        """Whatever the answer's attempt held, give it up: its queue place or its slot."""
        e = self._find(answer_id)
        if e is not None:
            self._waiters.remove(e)
        self.release(answer_id)

    def withdraw(self, answer_id: str) -> bool:
        e = self._find(answer_id)
        if e is None:
            return False
        self._waiters.remove(e)
        self._withdrawn[answer_id] = None
        self._bound(self._withdrawn)
        if e.fut is not None and not e.fut.done():
            e.fut.set_exception(AdmissionWithdrawn(answer_id))
        return True

    def position(self, answer_id: str) -> int | None:
        for i, e in enumerate(self._waiters, 1):
            if e.answer_id == answer_id:
                return i
        return None

    def state(self) -> dict:
        return {"limit": self._limit, "queue_max": self._queue_max,
                "running": len(self._holders), "waiting": len(self._waiters)}


_GATE: AdmissionGate | None = None


def get_gate() -> AdmissionGate:
    global _GATE
    if _GATE is None:
        _GATE = AdmissionGate(answer_limit_from_env(), answer_queue_max_from_env())
    return _GATE


def reset_gate_for_tests(limit: int | None = None, queue_max: int | None = None) -> AdmissionGate:
    global _GATE
    _GATE = AdmissionGate(limit if limit is not None else answer_limit_from_env(),
                          queue_max if queue_max is not None else answer_queue_max_from_env())
    return _GATE
