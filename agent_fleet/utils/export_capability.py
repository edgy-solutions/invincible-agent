"""Export-capability check for engines (policy rail `capability_grants`, `can_export:<profile>`).

Asks Topaz whether a caller may PRODUCE an answers export: the `capability` object
`can_export:<profile name>`, relation `can_invoke`. The row that grants it is policy's
(`policy/capability_grants.yaml`); a profile with no row is exportable by nobody
(DENY BY DEFAULT).

This is the same question lane/01's `_may_export_profile` (#163) asks from the BFF for the review
export. It is a separate function because engine-cost cannot import `src/iagent`; the two fold
together at the loader convergence (iagent-mesh v0.9.12).

Same posture as `recipient_readers.py`, with one addition: missing arguments or an unconfigured
directory are a DENY (False); a 404 is a DENY too (Topaz answers "object not found" for an
ungranted capability, as `human_tasks.can_invoke_or_unavailable` maps it -- without that,
deny-by-default would read as an outage); any other non-2xx, a transport error, or a body that
is not JSON RAISES, so the caller can tell "Topaz is down" (503) from "Topaz answered: no".
"""
from __future__ import annotations

import os

import httpx


def check_payload(profile_name: str, caller_id: str) -> dict:
    return {
        "object_type": "capability",
        "object_id": f"can_export:{profile_name}",
        "relation": "can_invoke",
        "subject_type": "user",
        "subject_id": caller_id,
    }


def can_export(profile_name: str, caller_id: str, *, directory_url: str | None = None) -> bool:
    url = (os.getenv("TOPAZ_DIRECTORY_URL", "") if directory_url is None else directory_url).strip()
    if not profile_name or not caller_id or not url:
        return False
    with httpx.Client(base_url=url, timeout=5.0) as c:
        r = c.post("/api/v3/directory/check", json=check_payload(profile_name, caller_id))
        if r.status_code == 404:
            return False
        r.raise_for_status()
        return bool(r.json().get("check"))
