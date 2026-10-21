"""Engine O joins an identical model call that is still running, instead of starting another.

Architect ruling 2026-10-20: "Engine O dedupes identical in-flight calls (prompt hash; a retry
joins the running call instead of starting another)".

MEASURED 2026-10-20 (sandbox revision 199, Engine O log 03:30-04:16Z): 55 completed
`ClassifyDomainIntent` calls, max 52,553 ms. On the two runs whose calls outlived the caller's
30 s budget, Engine A re-posted the same prompt 4 and 8 times and Engine O completed every
abandoned call, each a full model call. A CACHE WOULD HAVE CAUGHT NONE OF THEM: every repeat
arrived while the first call was still running. So this is a map of calls in flight, not a
store of answers -- the key is gone the moment the call finishes.

Pure: no import of baml_client. The key is a hash of the rendered HTTP request body, so two
calls are "identical" exactly when the model would be sent identical bytes. Nothing but the
function name and the first eight hex of the hash is ever logged.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import weakref


class CoalescingClient:
    """Wraps Engine O's BAML async client so an identical call made while the first is still
    running joins it instead of starting a second model call."""

    def __init__(self, inner, *, log=None):
        self._inner = inner
        self._log = log or logging.getLogger(__name__)
        # PER EVENT LOOP: a task belongs to the loop that created it and must never be
        # awaited from another.
        self._by_loop: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()
        self._warned: set = set()

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if name[:1].isupper() and callable(attr):
            async def _coalesced(*args, **kwargs):
                return await self._call(name, attr, args, kwargs)

            _coalesced.__name__ = name
            return _coalesced
        return attr

    def inflight_count(self) -> int:
        """Entries in flight on the current loop (for tests)."""
        return len(self._by_loop.get(asyncio.get_running_loop(), {}))

    async def _key(self, name, args, kwargs):
        try:
            rendered = getattr(self._inner.request, name)(*args, **kwargs)
            if hasattr(rendered, "__await__"):
                rendered = await rendered
            body = rendered.body
            if hasattr(body, "raw"):
                raw = body.raw()
                data = raw if isinstance(raw, bytes) else str(raw).encode()
            elif hasattr(body, "text"):
                data = body.text().encode()
            else:
                data = json.dumps(body.json(), sort_keys=True).encode()
            return hashlib.sha256(name.encode() + b"\0" + data).hexdigest()
        except Exception as exc:  # noqa: BLE001 -- coalescing is never load-bearing
            if name not in self._warned:
                self._warned.add(name)
                self._log.warning(
                    "inflight: cannot render %s's request (%s) — calls run uncoalesced",
                    name, exc,
                )
            return None

    async def _call(self, name, fn, args, kwargs):
        key = await self._key(name, args, kwargs)
        if key is None:
            return await fn(*args, **kwargs)
        loop = asyncio.get_running_loop()
        inflight = self._by_loop.setdefault(loop, {})
        task = inflight.get(key)
        if task is not None:
            self._log.info("inflight: %s joined the running call sha8=%s", name, key[:8])
            return await asyncio.shield(task)
        task = asyncio.ensure_future(fn(*args, **kwargs))
        inflight[key] = task

        def _done(t, _key=key, _map=inflight):
            if _map.get(_key) is t:
                del _map[_key]
            if not t.cancelled():
                t.exception()  # retrieve it: an exception nobody awaits must not warn

        task.add_done_callback(_done)
        # THE SHIELD IS THE POINT: when the first caller is cancelled (its client went away)
        # the model call keeps running, and a retry joins it.
        return await asyncio.shield(task)
