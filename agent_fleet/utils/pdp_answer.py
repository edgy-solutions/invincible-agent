"""A PDP's boolean answer, read strictly: yes, no, or malformed.

Topaz answers a directory check as `{"check": <bool>}` and an authorizer decision as
`{"decisions": [{"decision": <name>, "is": <bool>}]}`, and a batch of directory checks as
`{"checks": [{"check": <bool>, "context": {...}}, ...]}` (`checks_answer`). A JSON boolean there
is an answer. A body that is not JSON, is not an object, or carries anything other than a boolean in
that field is MALFORMED, and a malformed answer is the outage class: it raises, and each site handles it exactly as it
handles Topaz being down (architect ruling 2026-10-31: "a non-boolean `check` is a malformed PDP
answer, which is the outage class: 503, never a 403 (a 403 asserts policy said no)"). Reading the
field with `bool(...)` admitted `"false"`, `"no"` and `"0"`.

An ABSENT field is a "no", not a malformed answer: proto3 JSON may omit a false boolean, so `{}` is
one way a "no" can arrive. That is read from the encoding, not measured against the live directory.

`MalformedPdpAnswer` is an `httpx.DecodingError`, so every handler that already maps a transport
failure to a 503 catches it with no change of its own. It is also a `ValueError`, which is what a
body that is not JSON raised before, so a caller that caught that still does. Handlers catch those
bases, never this class, so the two import paths (`utils.` in an engine image, `agent_fleet.utils.`
in the source tree) cannot split the catch.

A site that used to read a failure as a deny answers a malformed answer as an outage (architect
ruling 2026-11-02: "a malformed PDP answer is 503 at every site, including the ones that already fail
closed -- same class as 16"), and a transport failure the same way (ruled yes the same day), so
`httpx.HTTPError` gets its own arm there, ahead of the broad one, which stays a deny for a defect.
Sealed in `tests/security/test_a_malformed_pdp_answer_is_503_at_every_site.py`.
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


#: The reason code of a batched check on an object or subject the directory does not have. It comes
#: with `check: false`, which is a "no": the single `/check` answers the same question 200 false.
_NOT_FOUND = "E20025"


def checks_answer(response: Any, asked: int) -> list[bool]:
    """The `check` of each item of a `/api/v3/directory/checks` answer, in the order asked.

    Read live against the sandbox's Topaz (0.33.13) on 2026-11-14:
    - the items come back in the order asked;
    - a plain no is `check: false` with an empty `context`;
    - a check on an object or subject the directory does not have is `check: false` with a
      `context.reason` that starts `E20025`;
    - an unknown object type or relation is `check: false` with another code (`E20026`, `E20036`).

    So each item is read as `check_answer` reads one answer, a JSON boolean and absent is a no, and:
    - an item whose reason starts `E20025` is a no;
    - an item with any other reason is MALFORMED: the directory could not decide, which is not a no;
    - a count other than `asked` is MALFORMED: no answer could be paired with its question.
    An absent `checks` is an empty list (proto3 JSON omits one)."""
    body = _body(response)
    items = body.get("checks")
    if items is None:
        items = []
    if not isinstance(items, list):
        raise MalformedPdpAnswer(f"`checks` is a {type(items).__name__}, not a list")
    if len(items) != asked:
        raise MalformedPdpAnswer(f"{len(items)} answers to {asked} checks")
    out: list[bool] = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise MalformedPdpAnswer(f"answer {i} is a {type(item).__name__}, not an object")
        value = _strict(item, "check")
        context = item.get("context")
        if context is None:
            context = {}
        if not isinstance(context, dict):
            raise MalformedPdpAnswer(f"answer {i}'s `context` is a {type(context).__name__}, not an object")
        reason = context.get("reason")
        if reason is None or reason == "":
            out.append(value)
            continue
        if not isinstance(reason, str):
            raise MalformedPdpAnswer(f"answer {i}'s reason is a {type(reason).__name__}, not a string")
        code = reason.split(" ", 1)[0][:16]  # the code only: the rest names the object and subject
        if code == _NOT_FOUND and value is False:
            out.append(False)
            continue
        raise MalformedPdpAnswer(f"answer {i} is the error {code}, not a decision")
    return out


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
