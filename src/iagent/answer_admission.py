"""The admission limit for durable answers (ADR-0072 5, ruled 2026-11-16).

At most `limit` answers run at once; the rest WAIT in arrival order and are never dropped. A
release hands its slot straight to the head waiter, so a newcomer can never barge past the
queue. The limit is a per-deployment value (`IAGENT_ANSWER_LIMIT`), read once when the gate is
built: a values change is applied by a pod roll. In-process: one gate per service replica.

A place may be RESERVED by the BFF before its first model call (amendment 2: admission comes
before intent extraction) and CLAIMED later by the workflow's `run`. An UNCLAIMED entry expires
(`IAGENT_ANSWER_RESERVATION_LEASE_S` for a holder, `IAGENT_ANSWER_WAITER_IDLE_S` for a waiter
nobody reads), so a dead BFF cannot leak a slot. A CLAIMED entry never expires.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time

logger = logging.getLogger("iagent.answer_admission")

ENV = "IAGENT_ANSWER_LIMIT"
QUEUE_ENV = "IAGENT_ANSWER_QUEUE_MAX"
LEASE_ENV = "IAGENT_ANSWER_RESERVATION_LEASE_S"
WAITER_IDLE_ENV = "IAGENT_ANSWER_WAITER_IDLE_S"
DEFAULT_LEASE_S = 300.0       # above /route_intent's 180 s timeout
DEFAULT_WAITER_IDLE_S = 30.0  # the BFF reads its place every 0.25 s


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


def _seconds_from_env(name: str, default: float) -> float:
    """A number > 0 as is; anything else logs a warning and gives the default."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        val = float(str(raw).strip())
        if val > 0:
            return val
    except (TypeError, ValueError):
        pass
    logger.warning("%s=%r is not a number > 0; using %s", name, raw, default)
    return default


def reservation_lease_from_env() -> float:
    return _seconds_from_env(LEASE_ENV, DEFAULT_LEASE_S)


def waiter_idle_from_env() -> float:
    return _seconds_from_env(WAITER_IDLE_ENV, DEFAULT_WAITER_IDLE_S)


class _Entry:
    """A queue place. `claimed`: `run` owns it, so it never expires. `touched`: the gate clock
    at the last `reserve`/`snapshot` read."""
    __slots__ = ("answer_id", "arrived_at", "seq", "fut", "claimed", "touched")

    def __init__(self, answer_id: str, arrived_at: float, seq: int, touched: float = 0.0) -> None:
        self.answer_id, self.arrived_at, self.seq, self.fut = answer_id, arrived_at, seq, None
        self.claimed, self.touched = False, touched

    def key(self) -> tuple:
        return (self.arrived_at, self.seq)


class _Hold:
    """A running slot. `since`: the gate clock when it became a holder (its lease starts
    there). `admitted_at`: the wall clock then (the queue wait is measured to it)."""
    __slots__ = ("arrived_at", "since", "admitted_at", "claimed")

    def __init__(self, arrived_at: float, since: float, admitted_at: float, claimed: bool) -> None:
        self.arrived_at, self.since, self.admitted_at, self.claimed = (
            arrived_at, since, admitted_at, claimed)


class AdmissionGate:
    def __init__(self, limit: int, queue_max: int = 0, *, lease_s: float = DEFAULT_LEASE_S,
                 waiter_idle_s: float = DEFAULT_WAITER_IDLE_S, clock=time.monotonic) -> None:
        self._limit = int(limit)
        self._queue_max = int(queue_max)
        self._lease_s = float(lease_s)
        self._waiter_idle_s = float(waiter_idle_s)
        self._clock = clock
        self._holders: dict[str, _Hold] = {}
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

    def _sweep(self) -> None:
        """Expire UNCLAIMED entries, lazily at the start of every operation (no timer). An idle
        waiter leaves the queue; a holder past its lease releases through `_release`, so its
        slot passes straight to the queue head. A claimed entry never expires."""
        now = self._clock()
        for e in [e for e in self._waiters
                  if not e.claimed and now - e.touched >= self._waiter_idle_s]:
            self._waiters.remove(e)
            logger.warning("unclaimed waiter %s untouched for %ss: left the queue",
                           e.answer_id, self._waiter_idle_s)
        for aid in [a for a, h in self._holders.items()
                    if not h.claimed and now - h.since >= self._lease_s]:
            logger.warning("unclaimed reservation %s past its %ss lease: slot released",
                           aid, self._lease_s)
            self._release(aid)

    def _hold(self, answer_id: str, arrived_at: float, claimed: bool = False) -> None:
        self._holders[answer_id] = _Hold(float(arrived_at), self._clock(), time.time(), claimed)

    def knows(self, answer_id: str) -> bool:
        self._sweep()
        return answer_id in self._holders or self._find(answer_id) is not None

    def touch(self, answer_id: str) -> None:
        """A read of a waiting reservation: somebody is still looking at it."""
        self._sweep()
        e = self._find(answer_id)
        if e is not None:
            e.touched = self._clock()

    def arrived_at(self, answer_id: str) -> float | None:
        self._sweep()
        h = self._holders.get(answer_id)
        if h is not None:
            return h.arrived_at
        e = self._find(answer_id)
        return None if e is None else e.arrived_at

    def admitted_at(self, answer_id: str) -> float | None:
        h = self._holders.get(answer_id)
        return None if h is None else h.admitted_at

    def claim(self, answer_id: str) -> dict | None:
        """`run` takes an entry the gate already knows (a reservation): its ORIGINAL arrived_at
        and its current decision come back, and it never expires. None when the gate does not
        know the id."""
        self._sweep()
        h = self._holders.get(answer_id)
        if h is not None:
            h.claimed = True
            return {"arrived_at": h.arrived_at, "decision": "admitted"}
        e = self._find(answer_id)
        if e is not None:
            e.claimed = True
            return {"arrived_at": e.arrived_at, "decision": "queued"}
        return None

    def release_unclaimed(self, answer_id: str) -> bool:
        """The BFF gives a reservation back. A claimed entry is `run`'s, which releases it."""
        self._sweep()
        h = self._holders.get(answer_id)
        e = self._find(answer_id)
        if h is None and e is None:
            return False
        if (h is not None and h.claimed) or (e is not None and e.claimed):
            return False
        self.leave(answer_id)
        return True

    def _enqueue(self, answer_id: str, arrived_at: float) -> None:
        self._seq += 1
        e = _Entry(answer_id, float(arrived_at), self._seq, self._clock())
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
        self._sweep()
        if answer_id in self._holders:
            return "admitted"
        if self._find(answer_id) is not None:
            return "queued"
        if len(self._holders) < self._limit and not self._waiters:
            self._hold(answer_id, arrived_at)
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
            self._hold(answer_id, arrived_at)
        else:
            self._enqueue(answer_id, arrived_at)

    def refused(self, answer_id: str) -> dict | None:
        return self._refused.get(answer_id)

    async def acquire(self, answer_id: str, arrived_at: float | None = None) -> None:
        self._sweep()
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
        self._sweep()
        self._release(answer_id)

    def _release(self, answer_id: str) -> None:
        if answer_id not in self._holders:
            return
        del self._holders[answer_id]
        # Hand the slot straight to the lowest-(arrived_at, seq) waiter: it never passes
        # through "free".
        while self._waiters and len(self._holders) < self._limit:
            e = self._waiters.pop(0)
            self._hold(e.answer_id, e.arrived_at, e.claimed)
            if e.fut is not None and not e.fut.done():
                e.fut.set_result(None)

    def leave(self, answer_id: str) -> None:
        """Whatever the answer's attempt held, give it up: its queue place or its slot."""
        self._sweep()
        e = self._find(answer_id)
        if e is not None:
            self._waiters.remove(e)
        self._release(answer_id)

    def withdraw(self, answer_id: str) -> bool:
        self._sweep()
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
        self._sweep()
        for i, e in enumerate(self._waiters, 1):
            if e.answer_id == answer_id:
                return i
        return None

    def state(self) -> dict:
        self._sweep()
        return {"limit": self._limit, "queue_max": self._queue_max,
                "running": len(self._holders), "waiting": len(self._waiters)}


_GATE: AdmissionGate | None = None


def _gate_from_env(limit: int | None = None, queue_max: int | None = None, **kw) -> AdmissionGate:
    return AdmissionGate(limit if limit is not None else answer_limit_from_env(),
                         queue_max if queue_max is not None else answer_queue_max_from_env(),
                         lease_s=reservation_lease_from_env(),
                         waiter_idle_s=waiter_idle_from_env(), **kw)


def get_gate() -> AdmissionGate:
    global _GATE
    if _GATE is None:
        _GATE = _gate_from_env()
    return _GATE


def reset_gate_for_tests(limit: int | None = None, queue_max: int | None = None,
                         **kw) -> AdmissionGate:
    global _GATE
    _GATE = _gate_from_env(limit, queue_max, **kw)
    return _GATE
