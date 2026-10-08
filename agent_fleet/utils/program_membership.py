"""Program-membership check for engines that cannot import the gateway (ADR-0056 Q2).

`src/iagent/human_tasks.py:check_can_view_program` is the gateway's gate, but it imports psycopg2
at module top and `src/` is not in an engine image, so an engine cannot call it. This asks Topaz
the SAME question with the SAME payload; `tests/safety/test_fracas_program_filter.py` pins the
two payloads equal so they cannot drift apart silently.

Same posture as the original: missing arguments or an unconfigured directory are a DENY (False);
a transport or HTTP failure RAISES, so the caller can tell "Topaz is down" (503) from "Topaz
answered: not a member" (empty). Collapsing the two would read an outage as "no failures".
"""
from __future__ import annotations

import os

import httpx


def check_payload(program: str, caller_id: str) -> dict:
    return {
        "object_type": "program",
        "object_id": program,
        "relation": "can_view_program",
        "subject_type": "user",
        "subject_id": caller_id,
    }


def can_view_program(program: str, caller_id: str, *, directory_url: str | None = None) -> bool:
    url = (os.getenv("TOPAZ_DIRECTORY_URL", "") if directory_url is None else directory_url).strip()
    if not program or not caller_id or not url:
        return False
    with httpx.Client(base_url=url, timeout=5.0) as c:
        r = c.post("/api/v3/directory/check", json=check_payload(program, caller_id))
        r.raise_for_status()
        return bool(r.json().get("check"))
