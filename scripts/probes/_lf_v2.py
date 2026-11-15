"""The one Langfuse read the probes share: v2 observations, paged by cursor.

Langfuse Cloud removed the v1 read APIs (`/api/public/traces`, v1 `/api/public/observations`)
and legacy ingestion on 2026-11-16. Measured against Cloud on 2026-11-14:
  - `traceId=` filters (an absent trace id returns 0; every hit carries the asked id);
  - each observation carries `traceId`, `parentObservationId`, `isRootObservation`, `userId`,
    `sessionId` and `environment`;
  - `metadata` comes back only with `fields=core,basic,metadata`;
  - an unknown field group is IGNORED, not refused, so a typo there fails silently;
  - no field group serves the trace's `tags`.

Credentials come from the environment only. Never print them, or the host.
"""
from __future__ import annotations

import datetime as dt
import os
import time

import requests
from requests.auth import HTTPBasicAuth

PAGE_PAUSE_S = 2.5  # the general API bucket is 30 requests a minute on Hobby


def base() -> str:
    return (os.environ.get("LANGFUSE_BASE_URL") or os.environ["LANGFUSE_HOST"]).rstrip("/")


def auth() -> HTTPBasicAuth:
    return HTTPBasicAuth(os.environ["LANGFUSE_PUBLIC_KEY"], os.environ["LANGFUSE_SECRET_KEY"])


def iso(t: float) -> str:
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).isoformat().replace("+00:00", "Z")


def observations(*, trace_id: str | None = None, since_s: float | None = None,
                 fields: str = "core,basic", max_pages: int = 10) -> tuple[int, list[dict]]:
    """(last http status, observations). Pages by `meta.cursor`, pausing between pages."""
    params: dict = {"limit": 1000, "fields": fields}
    if trace_id:
        params["traceId"] = trace_id
    if since_s is not None:
        params["fromStartTime"] = iso(time.time() - since_s)
    out: list[dict] = []
    status = 0
    for page in range(max_pages):
        if page:
            time.sleep(PAGE_PAUSE_S)
        r = requests.get(f"{base()}/api/public/v2/observations", auth=auth(), params=params,
                         timeout=60)
        status = r.status_code
        if status != 200:
            break
        body = r.json()
        out.extend(body.get("data", []))
        cursor = (body.get("meta") or {}).get("cursor")
        if not cursor:
            break
        params["cursor"] = cursor
    return status, out


def root_of(obs: list[dict]) -> dict | None:
    """The trace's earliest parentless observation; its user, session and env are the trace's.

    NOT `isRootObservation`: on trace a0aa8dbe (2026-11-15) three observations carried it, one
    of them with a parent inside the trace. A trace whose entry span never emitted has several
    parentless tops; the earliest stands for the trace."""
    tops = [o for o in obs if not o.get("parentObservationId")] or list(obs)
    return min(tops, key=lambda o: o.get("startTime") or "") if tops else None


def trace_fields(obs: list[dict], keys=("userId", "sessionId", "environment")) -> dict:
    """Each trace-level field as the trace's observations carry it: the one non-empty value,
    "" when none carries it, or "MIXED(<n>)" when they disagree. Per-observation, because on
    trace a0aa8dbe `engine-o /plan` carried no userId or sessionId while the analyst spans did."""
    out = {}
    for k in keys:
        vals = {o.get(k) for o in obs if o.get(k)}
        out[k] = next(iter(vals)) if len(vals) == 1 else ("" if not vals else f"MIXED({len(vals)})")
    return out
