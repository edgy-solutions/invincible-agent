"""The BFF's client for the durable answer path (IAGENT_ANSWER_PATH=durable).

It speaks the same four reads `_generate_dagster_stream_inner` makes of Dagster, in the same
return shapes, so the stream's body does not know which backend it polls. The reads all come
from ONE `snapshot` call per poll tick (cached for `snapshot_ttl_s`).
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Callable

import httpx

logger = logging.getLogger(__name__)


class DurableAnswers:
    poll_interval_s = 0.25

    def __init__(self, ingress_url: str, *,
                 client_factory: Callable[[], httpx.AsyncClient] = lambda: httpx.AsyncClient(timeout=30.0),
                 snapshot_ttl_s: float = 0.2) -> None:
        self._ingress = ingress_url.rstrip("/")
        self._client_factory = client_factory
        self._ttl = snapshot_ttl_s
        self._cache: dict[str, tuple[float, dict]] = {}

    async def launch(self, op_config: dict) -> str | None:
        answer_id = str(uuid.uuid4())
        try:
            async with self._client_factory() as client:
                resp = await client.post(
                    f"{self._ingress}/SupervisorAnswer/{answer_id}/run/send", json=op_config)
                resp.raise_for_status()
            return answer_id
        except Exception as exc:  # noqa: BLE001 -- like _launch_supervisor_job: None on any error
            logger.error("Failed to launch the durable answer via Restate: %s", exc)
            return None

    async def _fetch(self, answer_id: str) -> dict | None:
        try:
            async with self._client_factory() as client:
                resp = await client.post(
                    f"{self._ingress}/SupervisorAnswer/{answer_id}/snapshot", json={})
                resp.raise_for_status()
                snap = resp.json()
            return snap if isinstance(snap, dict) else None
        except Exception as exc:  # noqa: BLE001
            logger.warning("durable answer snapshot read failed for %s: %s", answer_id, exc)
            return None

    async def _snapshot(self, answer_id: str) -> dict | None:
        hit = self._cache.get(answer_id)
        now = time.monotonic()
        if hit is not None and now - hit[0] < self._ttl:
            return hit[1]
        snap = await self._fetch(answer_id)
        if snap is not None:
            self._cache[answer_id] = (now, snap)
            if len(self._cache) > 256:
                self._cache.pop(next(iter(self._cache)))
        return snap

    async def get_run_status(self, answer_id: str) -> dict:
        snap = await self._snapshot(answer_id)
        if snap is None:
            return {}
        return {"__typename": "Run", "status": snap.get("status")}

    async def get_run_events(self, answer_id: str) -> list:
        snap = await self._snapshot(answer_id)
        return [] if snap is None else list(snap.get("events") or [])

    async def get_step_stats(self, answer_id: str) -> list[dict]:
        snap = await self._snapshot(answer_id)
        if snap is None:
            return []
        return [{"stepKey": s.get("stepKey"), "status": s.get("status"), "endTime": s.get("endTime")}
                for s in snap.get("steps") or []]

    async def get_ui_payload_output(self, answer_id: str) -> dict:
        # Always a fresh read: the payload is the answer, never a cached tick's.
        snap = await self._fetch(answer_id)
        result = (snap or {}).get("result") or {}
        if result.get("payload") is None:
            return {"error": "Durable answer has no UI payload"}
        return {"payload": result["payload"], "referenced_uris": result.get("referenced_uris") or []}
