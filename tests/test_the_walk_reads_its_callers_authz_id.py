"""THE LIVE WALK READS EACH CALLER'S authz_id FROM ITS SESSION BEFORE IT WRITES ANYTHING.

Chris, 2026-11-06: "make the liaison's /me an explicit readiness step in future rather than a log
grep -- a 200 with empty entitlements is exactly the silent failure a readiness check exists to
catch." `tests/sandbox_e2e/test_mrad_case_walks_to_closed.py` used to send the initiator's EMAIL
as `on_behalf_of`, on the comment "in the sandbox authz_id == email". Its readiness step now reads
`authz_id` and the cells from `GET /me/entitlements` for both callers, and stops on a blank id or
no cells before `POST /ingest/events` is ever sent.

Each refusal arm has a control that differs only in the field the guard decides on.
"""
from __future__ import annotations

import json

import httpx
import pytest

from tests.sandbox_e2e import test_mrad_case_walks_to_closed as mrad

_READY = {"authz_id": "erin-authz", "email": "erin@example.test", "source": "topaz",
          "cells": [{"persona": "maintainer", "domain": "maintenance"}]}


def _walk(me: dict[str, dict], seen: list[httpx.Request]) -> mrad.Walk:
    """A Walk whose BFF answers /me/entitlements per caller and refuses everything else 500."""
    by_token = {"tok-initiator": "initiator", "tok-decider": "decider"}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        who = by_token[req.headers["Authorization"].removeprefix("Bearer ")]
        if req.url.path == "/me/entitlements":
            return httpx.Response(200, json=me[who])
        return httpx.Response(500, json={"stopped": "after readiness"})

    w = mrad.Walk("http://bff.test", {"initiator": "tok-initiator", "decider": "tok-decider"})
    w.http = httpx.Client(transport=httpx.MockTransport(handler))
    return w


def _posts(seen: list[httpx.Request]) -> list[httpx.Request]:
    return [r for r in seen if r.method == "POST"]


def test_a_ready_walk_sends_the_initiators_authz_id_not_its_email():
    seen: list[httpx.Request] = []
    decider = {**_READY, "authz_id": "bob-authz", "email": "bob@example.test"}
    with pytest.raises(mrad.Fail) as exc:
        mrad.walk(_walk({"initiator": _READY, "decider": decider}, seen), None)
    assert exc.value.step == "ingest the fault event"
    (post,) = _posts(seen)
    assert json.loads(post.content)["on_behalf_of"] == "erin-authz"


def test_an_explicit_initiator_id_still_wins_after_readiness():
    seen: list[httpx.Request] = []
    with pytest.raises(mrad.Fail):
        mrad.walk(_walk({"initiator": _READY, "decider": _READY}, seen), "given-id")
    (post,) = _posts(seen)
    assert json.loads(post.content)["on_behalf_of"] == "given-id"


@pytest.mark.parametrize("who", ["initiator", "decider"])
@pytest.mark.parametrize("authz_id", [None, "", "   "], ids=["absent", "empty", "whitespace"])
def test_a_blank_authz_id_stops_the_walk_before_any_write(who, authz_id):
    seen: list[httpx.Request] = []
    me = {"initiator": _READY, "decider": _READY, who: {**_READY, "authz_id": authz_id}}
    with pytest.raises(mrad.Fail) as exc:
        mrad.walk(_walk(me, seen), None)
    assert exc.value.step == f"{who} readiness: authz_id is blank"
    assert _posts(seen) == []


@pytest.mark.parametrize("who", ["initiator", "decider"])
def test_a_200_with_no_cells_stops_the_walk_before_any_write(who):
    seen: list[httpx.Request] = []
    me = {"initiator": _READY, "decider": _READY, who: {**_READY, "cells": []}}
    with pytest.raises(mrad.Fail) as exc:
        mrad.walk(_walk(me, seen), None)
    assert exc.value.step == f"{who} readiness: no entitlement cells"
    assert _posts(seen) == []


def test_the_control_with_the_same_fields_set_passes_readiness():
    seen: list[httpx.Request] = []
    ids = mrad.readiness(_walk({"initiator": _READY, "decider": _READY}, seen))
    assert ids == {"initiator": "erin-authz", "decider": "erin-authz"}
    assert [r.url.path for r in seen] == ["/me/entitlements", "/me/entitlements"]
