"""The domains a caller holds, for engines that cannot import the gateway.

`src/iagent/authz/topaz_client.py:TopazDirectoryClient.get_entitlements` is the gateway's read of a
user's (persona, domain) matrix, but `src/` is not in an engine image, so an engine cannot call it.
This asks the directory the SAME questions with the SAME requests (a user's `member` relations to
groups, then each group's `assumable_by` cells, paginated, a 404 read as empty), and keeps the part
after the colon of each `<PERSONA>:<DOMAIN>` cell id. `tests/finance/test_a_measure_row_cells_are_enforced.py`
runs both clients against one recording transport and pins the requests equal, so they cannot drift.

A declared measure's `policy.cells` names DOMAINS (the matrix is persona x domain; a row's list holds
domains), so the engine's question is "does the caller hold any domain in this list", and the answer
does not depend on which persona the caller has active.

Same posture as `program_membership.py`: missing arguments or an unconfigured directory are a DENY
(an empty set); a transport or HTTP failure RAISES, so the caller can tell "the directory is down"
(503) from "the directory answered: you hold none" (an empty set, 403). Collapsing the two would read
an outage as a refusal, or, the other way, as a grant.
"""
from __future__ import annotations

import os

import httpx

_RELATIONS = "/api/v3/directory/relations"


def user_groups_params(user_id: str, page_token: str = "") -> dict[str, str]:
    params = {
        "subject_type": "user",
        "subject_id": user_id,
        "relation": "member",
        "object_type": "group",
    }
    if page_token:
        params["page.token"] = page_token
    return params


def group_grants_params(group_id: str, page_token: str = "") -> dict[str, str]:
    params = {
        "object_type": "cell",
        "relation": "assumable_by",
        "subject_type": "group",
        "subject_id": group_id,
        "subject_relation": "member",
    }
    if page_token:
        params["page.token"] = page_token
    return params


def _pages(client: httpx.Client, make_params):
    """Every relation across every page; a 404 is an empty answer, any other failure raises."""
    token = ""
    while True:
        r = client.get(_RELATIONS, params=make_params(token))
        if r.status_code == 404:
            return
        r.raise_for_status()
        body = r.json()
        yield from (body.get("results") or body.get("relations") or [])
        token = (body.get("page") or {}).get("next_token", "")
        if not token:
            return


def entitled_domains(user_id: str, *, directory_url: str | None = None) -> frozenset[str]:
    url = (os.getenv("TOPAZ_DIRECTORY_URL", "") if directory_url is None else directory_url).strip()
    if not user_id or not url:
        return frozenset()
    domains: set[str] = set()
    with httpx.Client(base_url=url.rstrip("/"), timeout=5.0) as c:
        groups = [rel["object_id"]
                  for rel in _pages(c, lambda t: user_groups_params(user_id, t))
                  if rel.get("object_type") == "group"]
        for group_id in groups:
            for rel in _pages(c, lambda t, g=group_id: group_grants_params(g, t)):
                cell_id = str(rel.get("object_id") or "")
                if ":" not in cell_id:
                    continue  # malformed: the gateway skips it too
                domains.add(cell_id.split(":", 1)[1].strip().upper())
    return frozenset(domains)
