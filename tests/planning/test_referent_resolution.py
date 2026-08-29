"""Referent resolution — turning "the Aurora site" into `S1`, and refusing when it cannot.

THE FAILURE THIS CLOSES was the single largest class in the corpus: 5 of 48 cases, every one
a WRONG fill, all from the same cause. Six spoken slots hold opaque ids, a speaker says a
name, and the filler had nowhere to resolve it — so it emitted the name, confidently, and the
engine answered `422 unknown site 'Aurora'`.

THREE-VALUED BY REQUIREMENT, not by preference. An unresolvable name left in `slots` as the
raw string is indistinguishable at the dispatch point from a successful fill: the supervisor
sees a value and dispatches. The `ask` disposition's trigger is a spoken-mandatory slot
ABSENT after filling, and it cannot fire on a slot that is present and wrong.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent_fleet.planning_agent import main as engine
from agent_fleet.planning_agent.seed import build_seed
from agent_fleet.planning_agent.slots import _REFERENT_KIND, slots_for
from agent_fleet.planning_agent.state import PlanStore


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(engine, "STORE", PlanStore(build_seed()))
    with TestClient(engine.app) as c:
        yield c


def _resolve(client, identifier):
    r = client.post("/resolve_instance", json={"identifier": identifier, "query": ""})
    assert r.status_code == 200
    return r.json()["candidates"]


# ── the provider ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("spoken,expected_id", [
    ("Aurora", "S1"),
    ("Brandon", "S2"),
    ("ERP Modernization", "I1"),
    ("Order to Cash", "BP1"),
    ("Financial Close Automation", "C1"),
])
def test_a_spoken_name_resolves_to_its_id(client, spoken, expected_id):
    """The five names the corpus actually speaks, plus one more. Parameterised on the
    NAMES rather than a count, because "5 resolved" passes when five wrong things do."""
    cands = _resolve(client, spoken)
    assert cands, f"{spoken!r} resolved to nothing"
    assert cands[0]["instance_id"] == expected_id


def test_an_id_still_resolves_to_itself(client):
    """A speaker who says "S1" is naming S1. A resolver that only understood labels would
    reject the filler's own correct answers."""
    assert _resolve(client, "S1")[0]["instance_id"] == "S1"


def test_an_unknown_name_returns_NOTHING_rather_than_the_least_bad_match(client):
    """The abstention that keeps a confidently wrong id from being produced. An empty list
    is a first-class answer — it is what lets the caller ask instead of dispatching."""
    assert _resolve(client, "Zanzibar Manufacturing Hub") == []
    assert _resolve(client, "") == []


def test_candidates_carry_the_class_so_a_caller_can_type_check(client):
    """"ERP Modernization" is an INITIATIVE. A `project_id` slot must be able to see that
    and refuse, which it can only do if the class rides with the candidate."""
    top = _resolve(client, "ERP Modernization")[0]
    assert top["class_uri"].endswith("Initiative")
    assert top["instance_id"] == "I1"


def test_candidates_are_ordered_best_first(client):
    cands = _resolve(client, "Site")
    scores = [c["score"] for c in cands]
    assert scores == sorted(scores, reverse=True)


# ── the seal: two maps of class names, which must not drift ──────────────────

def test_every_declared_referent_class_is_one_the_resolver_can_RETURN():
    """THE DRIFT SEAL. `slots.py` says a slot names a `#Project`; `main.py`'s resolver emits
    candidates classed `#Project`. Those are two hand-written class names in two files, and
    a mismatch fails CLOSED and INVISIBLY: every resolution is type-rejected, every slot
    reports unresolved, and the system looks like a model that cannot resolve names.

    Read from both constants rather than a remembered list, so adding a referent slot with a
    class the resolver never emits fails here by name."""
    emitted = {engine.IDP + class_local for _, _, class_local in engine._RESOLVABLE}
    declared = set(_REFERENT_KIND.values())
    assert declared, "no referent slots declared — this seal would pass over nothing"
    missing = declared - emitted
    assert not missing, (
        f"declared referent class(es) the resolver can never return: {sorted(missing)}. "
        f"Every resolution for those slots will be type-rejected and report unresolved."
    )


def test_every_referent_slot_in_the_declarations_is_in_the_map():
    """The map is keyed by parameter name, so a renamed parameter silently loses its
    referent and goes back to emitting spoken names. Checked against the live signatures."""
    from agent_fleet.planning_agent import measures

    id_slots = {
        (fn, d["name"])
        for fn in dir(measures) if fn.startswith("plan_")
        for d in slots_for(fn)
        if d["kind"].startswith("spoken") and d["name"].endswith("_id")
    }
    assert id_slots, "no id-shaped spoken slots found — the seal is pointing at nothing"
    unmapped = sorted({name for _, name in id_slots if name not in _REFERENT_KIND})
    assert not unmapped, (
        f"id-shaped spoken slot(s) with no referent class: {unmapped} — these will be "
        f"filled with whatever the speaker said and reach the engine as a 422"
    )
