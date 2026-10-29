"""Recipient-reader check for engines (policy rail `recipient_readers`).

Asks Topaz whether a caller may download a recipient's disclosure package: the
`recipient_scope` object `<owner>:<scope>`, permission `can_read_recipient`
(policy/sync/recipient_reader_sync.py writes the `reader` relations; the chart's Topaz manifest
declares the type). `owner` is the engine that owns the scope ("finance" | "cost") -- part of
the object id so a scope string shared by two engines never shares readers.

Same posture as `program_membership.py`: missing arguments or an unconfigured directory are a
DENY (False); a transport or HTTP failure RAISES, so the caller can tell "Topaz is down" (503)
from "Topaz answered: not a reader". Collapsing the two would read an outage as "no readers".
"""
from __future__ import annotations

import os

import httpx


def check_payload(owner: str, scope: str, caller_id: str) -> dict:
    return {
        "object_type": "recipient_scope",
        "object_id": f"{owner}:{scope}",
        "relation": "can_read_recipient",
        "subject_type": "user",
        "subject_id": caller_id,
    }


def can_read_recipient(owner: str, scope: str, caller_id: str, *,
                       directory_url: str | None = None) -> bool:
    url = (os.getenv("TOPAZ_DIRECTORY_URL", "") if directory_url is None else directory_url).strip()
    if not owner or not scope or not caller_id or not url:
        return False
    with httpx.Client(base_url=url, timeout=5.0) as c:
        r = c.post("/api/v3/directory/check", json=check_payload(owner, scope, caller_id))
        r.raise_for_status()
        return bool(r.json().get("check"))
