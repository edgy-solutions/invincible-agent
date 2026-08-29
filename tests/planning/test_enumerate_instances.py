"""`enumerate` is not `resolve` — the option source an elicitation draws its menu from.

WHY A SECOND VERB. `resolveInstance` takes an `identifier` and SCORES candidates against
something the speaker said. A slot the phrase never filled has no such string, so no number of
resolve providers builds a menu for it. All four spoken-mandatory slots in this engine are
instance-kind, which is why the ask trigger was free and every menu it could offer was blocked.

    resolve   : identifier -> scored candidates
    enumerate : class      -> its members

THREE OUTCOMES, NOT A LIST, and that is the design rather than an implementation detail.
`resolve` is bounded by the query; `enumerate` is bounded only by the substrate. A provider
that cannot list a class must be able to SAY so as a first-class answer — which is what makes
ADR-0033's free-text boundary decidable instead of a fudge: free text is permitted where a
provider REPORTS unboundedness, never where nobody built the capability.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent_fleet.planning_agent import main as engine
from agent_fleet.planning_agent.seed import build_seed
from agent_fleet.planning_agent.slots import _REFERENT_KIND
from agent_fleet.planning_agent.state import PlanStore

IDP = "http://invincible-agent/idp#"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(engine, "STORE", PlanStore(build_seed()))
    with TestClient(engine.app) as c:
        yield c


def _enum(client, class_uri):
    r = client.post("/enumerate_instances", json={"class_uri": class_uri})
    assert r.status_code == 200
    return r.json()


# ── outcome: members ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("cls,count", [
    ("Capability", 9), ("Site", 4), ("Project", 14),
    ("BusinessProcess", 2), ("Initiative", 3), ("Technology", 5),
])
def test_a_bounded_class_returns_its_MEMBERS(client, cls, count):
    """Asserted on the counts the seed actually holds, per class, rather than "some members
    came back" — which passes when the wrong collection is enumerated."""
    body = _enum(client, IDP + cls)
    assert body["outcome"] == "members"
    assert body["count"] == count
    assert len(body["members"]) == count


def test_members_carry_a_LABEL_because_a_menu_of_ids_is_not_a_menu(client):
    """"Which capability?" answered with C1..C9 is a menu only in shape. The label is the
    part a person chooses from; the id is what the slot needs afterwards."""
    members = _enum(client, IDP + "Capability")["members"]
    assert all(m["label"] for m in members), "a member came back with no label"
    assert {"C1", "C9"} <= {m["instance_id"] for m in members}


# ── outcome: too_many ────────────────────────────────────────────────────────

def test_a_class_larger_than_the_menu_bound_returns_TOO_MANY_with_its_count(client, monkeypatch):
    """The outcome that makes free text legitimate. Exercised by lowering the bound, because
    no class in this substrate currently exceeds it — and an outcome that the tests can never
    reach is an outcome nobody has checked.

    The COUNT travels even though the members do not: "there are 14" is a useful thing for an
    ask to say, and it is cheap here because the collection is already in hand."""
    monkeypatch.setattr(engine, "_MENU_BOUND", 3)
    body = _enum(client, IDP + "Project")
    assert body["outcome"] == "too_many"
    assert body["count"] == 14
    assert body["bound"] == 3
    assert body["members"] == [], "too_many must not also return a truncated menu"


def test_the_bound_is_inclusive_at_its_edge(client, monkeypatch):
    """4 sites with a bound of 4 is a menu; with a bound of 3 it is not. Pinned because an
    off-by-one here silently turns a legitimate menu into permitted free text."""
    monkeypatch.setattr(engine, "_MENU_BOUND", 4)
    assert _enum(client, IDP + "Site")["outcome"] == "members"
    monkeypatch.setattr(engine, "_MENU_BOUND", 3)
    assert _enum(client, IDP + "Site")["outcome"] == "too_many"


# ── outcome: unsupported ─────────────────────────────────────────────────────

def test_a_class_this_provider_does_not_hold_is_UNSUPPORTED_not_empty(client):
    """"I do not enumerate this" and "this class has no members" are different facts.
    Collapsing them is how free text becomes a DEFAULT rather than a reported outcome — the
    reading ADR-0033's "never because enumeration was not attempted" clause exists to close."""
    body = _enum(client, "http://invincible-agent/idp#Dataset")
    assert body["outcome"] == "unsupported"
    assert body["members"] == []
    assert body["reason"], "an unsupported answer with no reason cannot be carried into an ask"


def test_an_empty_class_uri_is_unsupported_rather_than_a_crash(client):
    assert _enum(client, "")["outcome"] == "unsupported"


# ── the join to the declarations, which is what makes this callable ──────────

def test_every_referent_class_a_slot_DECLARES_can_be_enumerated(client):
    """THE JOIN THE ENUMERATE ITEM FLAGGED AS "most likely to be discovered late", and it is
    already closed: a slot's `referent` holds the CLASS URI, which is exactly this endpoint's
    input. A caller passes the declaration straight through and needs no vocabulary of its own.

    Every class a slot can declare must therefore be enumerable, or the ask for that slot has
    no menu and silently falls back to free text — which would be free text by omission, the
    thing the whole three-outcome design exists to prevent."""
    assert _REFERENT_KIND, "no referent classes declared — this seal would pass over nothing"
    for slot, class_uri in sorted(_REFERENT_KIND.items()):
        body = _enum(client, class_uri)
        assert body["outcome"] != "unsupported", (
            f"slot {slot} declares {class_uri}, which this engine cannot enumerate — an ask "
            f"for it would fall back to free text because nobody built the capability, not "
            f"because the class is unbounded"
        )
