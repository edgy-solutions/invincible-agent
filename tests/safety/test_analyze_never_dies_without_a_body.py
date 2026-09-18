"""`/analyze` answers every call — a refusal, a result, or a named 500. Never nothing.

**THE DEFECT, MEASURED 2026-09-14 AND THEN RE-MEASURED AS A FIX.** `analyze` ended in
`fn(**req.params)` with the params splatted unfiltered, so ANY key the caller added that the
measure did not declare raised `TypeError: got an unexpected keyword argument` — unhandled, no
body, and from the caller's side indistinguishable from an engine that is merely slow:

    {"subject": "safety:Hazard"}    -> TypeError, no response
    {"hazard_id": "HAZ-1003"}       -> TypeError, no response

**WHY IT COST 58 SECONDS TO LEARN NOTHING.** A dispatch that gets no response cannot tell a dead
handler from a slow one, so the artifact records FAILED with 0 bytes and the time is attributed
to the dispatch — the one place the cause is not. Every diagnosis then starts at the wrong end.
The walk that found this read `disposition: route`, `58,425 ms`, `rendered_output 0 bytes`, and
the engine log showing the inbound line and nothing after it.

**AND IT HAD A TWIN SYMPTOM, WHICH IS THE PART WORTH KEEPING.** The same surface shows a blank
card when an output class has no `mesh:rendersAs` binding — the HUD's `payload-only` line. Two
unrelated defects presenting identically is how an afternoon goes, and it is the argument for a
refusal that NAMES ITSELF rather than one that merely fails.

── WHY THE ALLOWLIST COMES FROM THE SIGNATURE ──────────────────────────────────────────────────
A hand-written set of accepted keys would be a second declaration of each measure's signature, and
the two would disagree on the first change — a slot added to a measure would be refused by a guard
nobody remembered to update, which is the same hand-kept-list failure one layer along. Reading
`inspect.signature` means the guard is correct by construction and cannot drift.
"""
from __future__ import annotations

import pytest

from ._engine_extra import requires_rdflib


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from agent_fleet.safety_agent import main

    with TestClient(main.app) as c:
        yield c


def _post(client, fn: str, params: dict):
    """POST the way the FLEET'S DISPATCHER does: verb in the PATH, `{query, params}` in the body.

    ⛔ THIS SEAL WAS GREEN ON A CONTRACT NOTHING COULD CALL. It posted to `/analyze` with
    `{"fn": ..., "params": ...}` — the engine's own invented shape — and every assertion here
    passed while EVERY REAL DISPATCH 422'd on arrival: `{"type":"missing","loc":["body","fn"]}`.
    The dispatcher puts the verb in the URL path and sends no `fn`, because cost and finance
    register `{base}/measure/{fn}`.

    **A seal that speaks the subject's own dialect cannot detect that the dialect is wrong.**
    It is the instrument-and-subject-share-a-surface shape at the level of a CONTRACT: the test
    agreed with the engine, both disagreed with the fleet, and the agreement is what made it
    look verified. Nothing in this file could have caught it, which is why it was caught by a
    replay against the pod instead.
    """
    return client.post(f"/measure/{fn}", json={"query": "", "params": params})


def test_the_happy_path_still_answers_so_the_guard_is_not_refusing_everything():
    """THE CONTROL, and it is first deliberately. A guard that refused every call would satisfy
    every assertion below about never dying silently — by never doing anything at all."""
    from fastapi.testclient import TestClient

    from agent_fleet.safety_agent import main

    with TestClient(main.app) as c:
        r = _post(c, "find_orphaned_hazards", {})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("refused") is False
        assert body["orphans"], (
            "the shipped fixture yielded no orphans — this seal would pass over an empty engine, "
            "which is the state the walk originally guessed at and the measurement disproved"
        )


@pytest.mark.parametrize(
    "key,value",
    [
        ("subject", "http://internal/sustainment/safety#Hazard"),
        ("hazard_id", "HAZ-1003"),
        ("instance_identifier", ""),
        ("owner_persona", "SAFETY_ENGINEER"),
    ],
)
def test_an_unexpected_key_is_a_422_that_NAMES_it(client, key, value):
    """THE SEAL. Each of these is a field the supervisor actually carries on a dispatch, so they
    are the keys most likely to arrive — `instance_identifier` and `owner_persona` are recorded
    on the failing artifact itself."""
    r = _post(client, "find_orphaned_hazards", {key: value})
    assert r.status_code == 422, f"expected a named refusal, got {r.status_code}: {r.text[:200]}"
    body = r.json()
    assert key in body["unexpected"], body
    assert key in body["reason"], body
    # A refusal that names only what was WRONG makes the caller guess at what would be right.
    assert body["accepts"], "the refusal does not say what the measure does accept"


def test_the_refusal_lists_what_the_measure_DOES_accept(client):
    """Derived from the signature, so it cannot drift from the measure it describes."""
    r = _post(client, "find_orphaned_hazards", {"nonsense": 1})
    accepts = set(r.json()["accepts"])
    assert {"scope", "scope_value"} <= accepts, accepts
    assert "nonsense" not in accepts


@requires_rdflib
def test_a_measure_that_RAISES_still_returns_a_named_body(client, monkeypatch):
    """THE CLASS, not just the one exception. The kwarg guard stops what we found; this stops
    what we have not. A bug inside a measure must be reported as a bug inside THAT measure,
    by name, with the params that reached it — never as silence.
    """
    from typing import Any, Optional

    from agent_fleet.safety_agent import main

    # ⛔ THE STUB CARRIES THE REAL SIGNATURE, AND THE FIRST ONE DID NOT — which changed the
    # contract it was substituting for. `slots_mod.slots_for` DERIVES A VERB'S SLOTS FROM THE
    # LIVE FUNCTION SIGNATURE, so a `def boom(*_a, **_k)` stub made `a` and `k` into
    # spoken-mandatory slots; the handler then refused with "missing required slot(s): a, k"
    # and the 500 path was never reached. The test failed at 200 and looked like a broken patch.
    #
    # **A DOUBLE THAT DOES NOT MATCH ITS ORIGINAL'S SIGNATURE IS NOT A DOUBLE OF IT** when
    # anything in the system reads that signature — the fixture silently redefined the verb it
    # was standing in for, and the assertion it defeated was its own.
    def boom(state: Any = None, *, scope: str = "fleet", scope_value: Optional[str] = None):
        raise RuntimeError("the matrix file went missing")

    # PATCHED ON `main.measures`, the object the handler actually reads — `main` resolves its
    # measures module through the flat-first try/except, so the name imported here is not
    # guaranteed to be the same module object the handler holds.
    monkeypatch.setattr(main.measures, "find_orphaned_hazards", boom)
    r = _post(client, "find_orphaned_hazards", {"scope": "fleet"})
    assert r.status_code == 500
    body = r.json()
    assert "RuntimeError" in body["reason"] and "matrix file went missing" in body["reason"]
    assert body["fn"] == "find_orphaned_hazards"
    # THE FIRST QUESTION ABOUT A FAILED DISPATCH is always "what was it actually sent", and the
    # answer has been unavailable every time it has been asked.
    assert body["params_received"] == ["scope"]


def test_EVERY_verb_refuses_an_unexpected_key_rather_than_dying(client):
    """DERIVED FROM THE CATALOGUE, not a list of the one verb that failed. A guard proven on the
    verb that exposed it says nothing about its two neighbours, and `find_orphaned_hazards` is
    the only one anyone has dispatched so far."""
    from agent_fleet.safety_agent import main

    assert len(main.VERBS) >= 3, "the catalogue shrank — this seal is quantifying over less"
    for v in main.VERBS:
        r = _post(client, v["fn"], {"definitely_not_a_slot": "x"})
        assert r.status_code == 422, (
            f"{v['fn']} answered {r.status_code} to an unexpected key rather than naming it"
        )
        assert "definitely_not_a_slot" in r.json()["unexpected"]


def test_an_unknown_fn_is_still_a_refusal_with_the_known_set(client):
    """Unchanged behaviour, asserted because the guard was inserted just above it and a refusal
    that moved would be invisible."""
    r = _post(client, "not_a_verb", {})
    assert r.status_code == 200
    body = r.json()
    assert body["refused"] is True and "unknown verb" in body["reason"]
    assert "find_orphaned_hazards" in body["known"]
