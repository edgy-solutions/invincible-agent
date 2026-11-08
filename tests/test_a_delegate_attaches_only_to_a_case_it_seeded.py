"""A delegate (a service identity acting for someone) attaches an occurrence only to an open
case IT seeded. The security half of #283's refile tests.

the #283 ruling that a new occurrence of an open episode attaches to the holder. It did not say whose
holder: the attach asks the episode by key alone (`CaseEpisode/<key>/attach` carries event_id,
received_at, ingest_id and no caller), so ANY delegate naming a declared principal reaches
another delegate's case. The case records who seeded it (`seeded_by`, the run request), and the
read side already scopes by it (`artifact_reads`); the attach does not.

Four arms, one at a time, against the REAL door and runner (the #283 harness, only the
ingress and the status table are doubles):
  1. a foreign delegate is refused, in the route family's own envelope and status (strict xfail:
     the code admits it today; packet to invincible-agent/lane/01);
  2. the seeding delegate is admitted (control);
  3. a person (not a delegate) keeps what the #283 ruling: attaches to the open case (control);
  4. the refusal is classified at its own site (the envelope arm reads the code of the sibling
     refusals, so a new site is not a new shape).
"""
from __future__ import annotations

import json

import pytest

from tests.test_an_occurrence_attaches_to_its_open_episode import (  # noqa: F401
    _approve, _facts, _occurrences, _episode, can_drop_open, gateway, world, pytestmark,
    policy, registered, restate, wr, _Cluster, _Promise, _answer, _body,
)

from fastapi.testclient import TestClient

_KIND = "episode-event"
PERSON = "alice@example.com"
DELEGATE_A = "svc-a@example.test"
DELEGATE_B = "svc-b@example.test"


def _as(authz_id):
    user = type("U", (), {"authz_id": authz_id, "id": authz_id, "sub": authz_id, "email": authz_id,
                          "persona": None, "entitled_domains": [], "is_authenticated": True})()
    gateway.app.dependency_overrides[gateway.get_current_user] = lambda: user


def _post(facts, *, caller, named=PERSON):
    _as(caller)
    return TestClient(gateway.app).post("/ingest/events", json={
        "content_kind": _KIND, "on_behalf_of": named, "payload": facts})


@pytest.fixture
def delegates(monkeypatch):
    monkeypatch.setenv("DELEGATE_ON_BEHALF_OF", json.dumps(
        {DELEGATE_A: [PERSON], DELEGATE_B: [PERSON]}))


def _open_a_case_seeded_by(world, caller):
    first = _post(_facts("E-1"), caller=caller)
    assert first.status_code == 200, first.text
    assert world.cluster.obj(_episode(_facts())).state["open"] == "E-1"
    return first


def _refusal_siblings(delegates):
    """The route family's own refusal: a delegate the map does not allow is 403 with a dict
    `detail` whose `error` is a code. Read from the live door, not restated."""
    out = _post(_facts("E-9"), caller=DELEGATE_A, named="someone-undeclared@example.test")
    assert out.status_code == 403, out.text
    detail = out.json()["detail"]
    assert isinstance(detail, dict) and detail["error"]
    return out.status_code


# Ruled by Chris (lane/saf, 2026-11-07): Lane 1's attach refuses a foreign delegate with this code,
# carried where the sibling refusals carry theirs: `detail["error"]`.
FOREIGN_DELEGATE_CODE = "delegate_not_seeder"


@pytest.mark.xfail(strict=True, reason=(
    "#283's attach asks the episode by key alone, so a foreign delegate attaches to a case it did "
    "not seed (200, attached: true). Lane 1 fixes the attach caller and refuses with "
    "`delegate_not_seeder` (packet, ruled); not fixed here."))
def test_a_foreign_delegate_cannot_attach_to_a_case_it_did_not_seed(world, delegates):
    _open_a_case_seeded_by(world, DELEGATE_A)
    assert world.cluster.case("E-1")["seeded_by"] == DELEGATE_A
    status = _refusal_siblings(delegates)
    out = _post(_facts("E-2"), caller=DELEGATE_B)
    assert out.status_code == status, out.text
    detail = out.json()["detail"]
    assert isinstance(detail, dict) and detail.get("error") == FOREIGN_DELEGATE_CODE, detail
    # a refusal records nothing: no occurrence on the holder, no case of its own, no status row
    assert not _occurrences(world, _facts(), "E-1")
    assert "case" not in world.cluster.ctx("E-2").state


def test_the_seeding_delegate_is_admitted_control(world, delegates):
    _open_a_case_seeded_by(world, DELEGATE_A)
    out = _post(_facts("E-2"), caller=DELEGATE_A)
    assert out.status_code == 200, out.text
    assert out.json()["workflow"] == {"case_id": "E-1", "started": False, "attached": True}
    assert [o["event_id"] for o in _occurrences(world, _facts(), "E-1")] == ["E-2"]


def test_a_person_keeps_the_attach_283_ruled_control(world, delegates):
    first = _post(_facts("E-1"), caller=PERSON)
    assert first.status_code == 200, first.text
    assert world.cluster.case("E-1")["seeded_by"] is None
    out = _post(_facts("E-2"), caller=PERSON)
    assert out.status_code == 200, out.text
    assert out.json()["workflow"] == {"case_id": "E-1", "started": False, "attached": True}


def test_the_sibling_refusal_is_a_403_with_a_coded_detail(world, delegates):
    assert _refusal_siblings(delegates) == 403
