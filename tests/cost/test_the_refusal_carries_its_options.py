"""The fifth screen: a designed refusal, and whether it tells the caller what to say next.

THE WALK SHEET ASSERTED A REFUSAL THAT DID NOT EXIST. Q5 step 1 says to expect
`VintageRequired` and checks that "it names BOTH vintages — 2021-02-01 and 2021-08-01".
Measured on the wire 2026-09-11, the route returned `slot_required` with `missing` and
`declarations` and NO VALUES AT ALL, because `rate_vintage` is a spoken-mandatory slot and
`/measure/{fn}` short-circuits BEFORE the verb runs. `_require_vintage` — the one piece of
code that knows the answer — was unreachable through the only path the UI uses.

A walker following that sheet would have scored a red against a rendering that works, on the
one screen nobody had ever looked at.

These seals hold the fixed shape, and the one that matters most is the JOIN: the verb's
`available` and the route's `options` are two computations of one truth, and nothing before
this asserted they agree.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent_fleet.cost_agent import measures
from agent_fleet.cost_agent.entities import VintageRequired
from agent_fleet.cost_agent.main import STATE, app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _refuse(client, params):
    r = client.post("/measure/cost_rate_comparison", json={"params": params})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["refused"] is True and body["outcome"] == "slot_required", body
    return body


def test_the_refusal_names_the_vintages_the_caller_may_choose(client):
    """The check the walk sheet asks for, now actually passable."""
    body = _refuse(client, {"lot": 3})
    assert body["missing"] == ["rate_vintage"]
    assert body["options"]["rate_vintage"] == ["2021-02-01", "2021-08-01"], (
        "the refusal does not name the vintages; a caller is told what is missing and has no "
        "way to learn what a vintage looks like"
    )


def test_the_route_and_the_VERB_agree_about_what_is_available(client):
    """THE JOIN. Two computations of one truth, and nothing asserted they agreed.

    `_require_vintage` raises `VintageRequired(available=...)` and the route computes
    `options` by a different path that never calls it. Both are individually correct and a
    change to either drifts silently — the verb's refusal is unreachable over HTTP, so no
    endpoint test can see it, and the route's options never run in a direct call. This is the
    only place the two meet.
    """
    body = _refuse(client, {"lot": 3})

    with pytest.raises(VintageRequired) as exc:
        measures.cost_rate_comparison(STATE, lot=3, rate_vintage=None)

    assert body["options"]["rate_vintage"] == list(exc.value.available), (
        f"the route offers {body['options']['rate_vintage']} and the verb would have said "
        f"{list(exc.value.available)} — one truth, two answers"
    )


def test_options_are_ABSENT_when_nothing_can_be_computed_rather_than_empty(client):
    """None and [] mean different things, and the difference is load-bearing.

    With no lot the engine genuinely cannot say which vintages apply — the vintages are a
    property of the LOT's fiscal year. An empty map would read to a caller as "asked, and
    there are none", which is a false statement about the model.
    """
    body = _refuse(client, {})
    assert set(body["missing"]) == {"lot", "rate_vintage"}
    assert "options" not in body, (
        f"options were carried with nothing to compute from: {body.get('options')!r}"
    )


def test_an_unknown_lot_does_not_get_a_SECOND_diagnosis_attached(client):
    """Lot 99 is not in the model. The refusal is still about the vintage.

    Guessing here would attach the lot's problem to the vintage's message, and a caller
    reading two diagnoses cannot tell which one to act on first.
    """
    body = _refuse(client, {"lot": 99})
    assert body["missing"] == ["rate_vintage"]
    assert "options" not in body


def test_supplying_the_vintage_gets_the_card_and_not_a_refusal(client):
    """THE POSITIVE CONTROL. Without it every assertion above could pass on a verb that
    refuses unconditionally — which is precisely the failure mode of a refusal seal."""
    r = client.post("/measure/cost_rate_comparison",
                    json={"params": {"lot": 3, "rate_vintage": "2021-02-01"}})
    body = r.json()
    assert body.get("refused") is not True, body
    assert body["output_uri"].endswith("#RateComparison")
    assert len(body["rows"]) == 6


def test_every_option_offered_is_one_the_verb_actually_ACCEPTS(client):
    """An option list is a promise. Offer a value the verb then rejects and the refusal has
    sent the caller into a second failure — worse than saying nothing, because it was
    specific."""
    offered = _refuse(client, {"lot": 3})["options"]["rate_vintage"]
    assert offered, "nothing offered; this seal would pass vacuously"
    for vintage in offered:
        r = client.post("/measure/cost_rate_comparison",
                        json={"params": {"lot": 3, "rate_vintage": vintage}})
        assert r.json().get("refused") is not True, (
            f"the refusal offered {vintage!r} and the verb then refused it"
        )


def test_a_verb_with_no_option_source_still_refuses_cleanly(client):
    """OPTION_SOURCES is keyed on (verb, slot) and covers one pair today. The absence of an
    entry must not become an error — a verb nobody has written options for still has to be
    able to ask for its slot."""
    r = client.post("/measure/package_export", json={"params": {}})
    body = r.json()
    assert body["refused"] is True and body["outcome"] == "slot_required"
    assert "recipient_scope" in body["missing"]
    assert "options" not in body
