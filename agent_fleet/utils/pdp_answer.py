"""A PDP's boolean answer, read strictly: yes, no, or malformed.

Topaz answers a directory check as `{"check": <bool>}` and an authorizer decision as
`{"decisions": [{"decision": <name>, "is": <bool>}]}`. A JSON boolean there is an answer. A body that
is not JSON, is not an object, or carries anything other than a boolean in that field is MALFORMED,
and a malformed answer is the outage class: it raises, and each site handles it exactly as it
handles Topaz being down (architect ruling 2026-10-31: "a non-boolean `check` is a malformed PDP
answer, which is the outage class: 503, never a 403 (a 403 asserts policy said no)"). Reading the
field with `bool(...)` admitted `"false"`, `"no"` and `"0"`.

An ABSENT field is a "no", not a malformed answer: proto3 JSON may omit a false boolean, so `{}` is
one way a "no" can arrive. That is read from the encoding, not measured against the live directory.

`MalformedPdpAnswer` is an `httpx.DecodingError`, so every handler that already maps a transport
failure to a 503 (or, at a fail-closed site, to a deny) catches it with no change of its own. It is
also a `ValueError`, which is what a body that is not JSON raised before, so a caller that caught
that still does. Handlers catch those bases, never this class, so the two import paths (`utils.` in
an engine image, `agent_fleet.utils.` in the source tree) cannot split the catch.
"""
from __future__ import annotations

from typing import Any

import httpx

_ABSENT = object()


class MalformedPdpAnswer(httpx.DecodingError, ValueError):
    """The PDP answered, but not with a JSON boolean where one belongs."""


def _body(response: Any) -> dict:
    try:
        body = response.json()
    except ValueError as exc:  # httpx and requests both raise a ValueError for a body that is not JSON
        raise MalformedPdpAnswer(f"the answer is not JSON ({type(exc).__name__})") from exc
    if not isinstance(body, dict):
        raise MalformedPdpAnswer(f"the answer is a JSON {type(body).__name__}, not an object")
    return body


def _strict(obj: dict, field: str) -> bool:
    value = obj.get(field, _ABSENT)
    if value is _ABSENT:
        return False
    if isinstance(value, bool):
        return value
    raise MalformedPdpAnswer(f"`{field}` is a {type(value).__name__}, not a JSON boolean")


def check_answer(response: Any) -> bool:
    """The `check` of a `/api/v3/directory/check` answer."""
    return _strict(_body(response), "check")


def decision_answer(response: Any, decision: str) -> bool:
    """The `is` of the named decision in a `/api/v2/authz/is` answer; no such decision is a "no"."""
    decisions = _body(response).get("decisions", [])
    if decisions is None:
        decisions = []
    if not isinstance(decisions, list):
        raise MalformedPdpAnswer(f"`decisions` is a {type(decisions).__name__}, not a list")
    for d in decisions:
        if not isinstance(d, dict):
            raise MalformedPdpAnswer(f"a decision is a {type(d).__name__}, not an object")
        if d.get("decision") == decision:
            return _strict(d, "is")
    return False
