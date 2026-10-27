"""Architect order 2026-10-15 (lane/74's finding on case 6790f5fb): the walk's step-1 CHECK asked
Topaz about `svc:case-runner`, not the event's dropper, whenever no user_jwt was attached --
`_run_subject` was right and the gate ignored it. A declared query is a mesh verb, and
svc:case-runner is never a verb grantee (ruling 2026-10-11), so the gate subject is the run's
acting identity with or without a user_jwt, and a blank one is DENIED rather than replaced by the
runner's.

These arms assert the identity handed to `check_can_invoke` -- the CHECK's subject -- not the
identity on the run (that is tests/test_an_event_case_runs_as_its_dropper.py). The case-runner
credential stays the TRANSPORT bearer; arm B says so, so the two are never confused again."""
from __future__ import annotations

import copy

import pytest

from tests.test_a_declared_query_walks_the_manual import (  # noqa: F401 -- fixtures by name
    ACK, DECIDE, KNOWN, WALK_VERB, _event, _real_policy, _run, ex, registered, wd, wire,
)

ERIN = "erin@example.com"
RUNNER = "svc:case-runner"
#: Bound at import, before the autouse `wire` replaces it with a recorder.
_REAL_CHECK = ex.check_can_invoke


def _dropped(event: dict, who) -> dict:
    ev = copy.deepcopy(event)
    ev["dropped_by"] = {"authz_id": who, "via": "svc:openddil"}
    return ev


@pytest.mark.asyncio
async def test_A_AN_EVENT_CASES_WALK_IS_CHECKED_AS_ITS_DROPPER(registered, wire):
    """END TO END: the trigger carries `dropped_by` and no user_jwt; the walk's capability is
    asked about the dropper, exactly once, and never about the runner."""
    declared = wd.load_query_verbs()[WALK_VERB].capability
    await _run(_dropped(_event(), ERIN), [(DECIDE, "replace_now"), (ACK, "released", "tier@x")])
    assert wire["asked"] == [(declared, ERIN)], wire["asked"]


def test_B_NO_USER_JWT_CHECKS_THE_ACTING_IDENTITY_AND_SENDS_THE_RUNNERS_TOKEN(wire):
    """UNIT, the other half: the subject of the check is the run's, the bearer on the wire is the
    runner's own credential. Transport identity is not the gate subject."""
    decl = wd.load_query_verbs()[WALK_VERB]
    ex.execute_declared_query(decl, {"fault_code": KNOWN}, {"authz_id": ERIN})
    assert wire["asked"] == [(decl.capability, ERIN)], wire["asked"]
    [post] = wire["posts"]
    assert post["headers"].get("Authorization") == "Bearer case-runner-token", post["headers"]


@pytest.mark.parametrize("identity", [{}, {"authz_id": ""}], ids=["absent", "blank"])
def test_C_A_BLANK_ACTING_IDENTITY_IS_ASKED_AS_BLANK_NEVER_AS_THE_RUNNER(wire, identity):
    decl = wd.load_query_verbs()[WALK_VERB]
    ex.execute_declared_query(decl, {"fault_code": KNOWN}, identity)
    assert wire["asked"] == [(decl.capability, "")], wire["asked"]
    assert all(who != RUNNER for _, who in wire["asked"]), wire["asked"]


def test_C_THE_REAL_GATE_DENIES_A_BLANK_CALLER_BEFORE_ANY_NETWORK(monkeypatch):
    """The control for C: the stub above allows everything, so this is the arm that says a blank
    subject actually FAILS. The real `check_can_invoke` refuses it before any request is built."""
    sent = []  # recorded, not raised: the check swallows every exception, so a raise would hide
    monkeypatch.setattr(ex.httpx, "post", lambda *a, **kw: sent.append(a) or 1 / 0)
    assert _REAL_CHECK("mesh:s1000dFaultWalk", "", topaz_url="http://topaz.invalid") is False
    assert sent == [], sent
    # positive control: a named caller DOES reach the seam, so `sent == []` above is not vacuous
    assert _REAL_CHECK("mesh:s1000dFaultWalk", ERIN, topaz_url="http://topaz.invalid") is False
    assert len(sent) == 1, sent
