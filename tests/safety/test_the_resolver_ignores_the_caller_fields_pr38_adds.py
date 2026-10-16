"""PR #38 (lane/74) adds `user_email` and `entitled_domains` to every mesh:resolveInstance POST.
This engine's provider neither requires nor refuses on them: with them, with an empty caller, and
with neither, HAZ-1004 resolves identically. So #38 cannot be what makes HAZ-1004 miss live."""
from __future__ import annotations

import pytest


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from agent_fleet.safety_agent import main

    with TestClient(main.app) as c:
        yield c


_BODIES = {
    "before #38 (identifier, query)": {"identifier": "HAZ-1004", "query": "q"},
    "after #38, a caller": {"identifier": "HAZ-1004", "query": "q", "user_email": "bob@example.invalid",
                            "entitled_domains": ["SUSTAINMENT"]},
    "after #38, no caller": {"identifier": "HAZ-1004", "query": "q", "user_email": "", "entitled_domains": []},
}


@pytest.mark.parametrize("name", list(_BODIES))
def test_HAZ_1004_resolves_whatever_caller_fields_arrive(client, name):
    r = client.post("/resolve_instance", json=_BODIES[name])
    assert r.status_code == 200, (name, r.text[:200])
    assert [c["instance_id"] for c in r.json()["candidates"]] == ["HAZ-1004"], name


def test_control_a_name_the_engine_does_not_hold_returns_no_candidates(client):
    r = client.post("/resolve_instance", json={"identifier": "HAZ-9999", "query": "q",
                                               "user_email": "bob@example.invalid"})
    assert r.status_code == 200 and r.json()["candidates"] == []
