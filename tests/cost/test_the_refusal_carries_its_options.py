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
from agent_fleet.cost_agent import slots as slot_decls
from agent_fleet.cost_agent.entities import VintageRequired
from agent_fleet.cost_agent.main import STATE, app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _refuse(client, params, verb="cost_rate_comparison"):
    r = client.post(f"/measure/{verb}", json={"params": params})
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


def _verbs_declaring(slot: str) -> list[str]:
    """Derived from the engine's own declarations, never listed here."""
    return [fn for fn in measures.VERBS if slot in slot_decls.mandatory_slots(fn)]


@pytest.mark.parametrize("verb", _verbs_declaring("rate_vintage"))
def test_EVERY_verb_needing_a_vintage_offers_the_options(client, verb):
    """⚠ THE FIRST FIX WAS A SAMPLE, AND A LIVE CARD IS WHERE THAT SHOWED.

    `OPTION_SOURCES` was keyed on `(verb, slot)` and held ONE entry. `cost_rate_comparison`
    got its options; `cost_lot_breakdown` and `cost_price_composition` declare the SAME
    mandatory `rate_vintage` and got none — so the ask rendered "Which rate vintage?" as a
    bare text box with nothing for cortex to draw. **I fixed the verb I happened to be
    looking at**, in the very commit whose subject was that a refusal must carry its options.

    PARAMETERIZED OFF THE DECLARATIONS, so a tenth verb taking a vintage is covered by the
    commit that adds it. A list written here would reproduce the original defect in the seal
    that exists to prevent it.
    """
    body = _refuse(client, {"lot": 3}, verb=verb)
    assert body["options"]["rate_vintage"] == ["2021-02-01", "2021-08-01"], (
        f"{verb} asks for a rate vintage and offers no values; a caller is told what is "
        f"missing with no way to learn what a valid one looks like"
    )


@pytest.mark.parametrize("verb", _verbs_declaring("rate_vintage"))
def test_every_option_offered_is_one_the_verb_actually_ACCEPTS(client, verb):
    """An option list is a promise. Offer a value the verb then rejects and the refusal has
    sent the caller into a second failure — worse than saying nothing, because it was
    specific.

    OVER EVERY LOT, NOT JUST LOT 3. The first version of this seal checked one lot and passed
    while the defect that reached a user was on lot 4 — whose fiscal year has a SINGLE
    vintage, so the two-vintage case cannot represent it. A seal over one member of a
    population is the same sample error the registry above just made.
    """
    for lot in STATE.lot_numbers:
        offered = _refuse(client, {"lot": lot}, verb=verb)["options"]["rate_vintage"]
        assert offered, f"lot {lot}: nothing offered; this seal would pass vacuously"
        for vintage in offered:
            r = client.post(f"/measure/{verb}",
                            json={"params": {"lot": lot, "rate_vintage": vintage}})
            assert r.json().get("refused") is not True, (
                f"{verb} on lot {lot} offered {vintage!r} and then refused it"
            )


def test_a_vintage_valid_for_ANOTHER_lot_is_a_REFUSAL_and_not_a_500(client):
    """⚠ THIS REACHED A USER AS AN EMPTY CARD.

    The ask said "Which rate vintage?" in a free-text box; the architect typed `2021-02-01`
    because that is what the PREVIOUS question used; lot 4 is FY2022. `rates_for` raised
    `CompositionError`, nothing caught it, and the card rendered blank.

    **An unhandled exception is the one refusal shape this engine promised never to
    produce.** ADR-0049 Ruling 4 exists so a composing verb can tell refusals apart, and a
    500 tells it nothing at all — it is indistinguishable from the engine being down.

    THE REFUSAL MUST CARRY WHAT THE LOT ACTUALLY ACCEPTS, recomputed rather than echoed: the
    caller's value was wrong, and handing it back is what produced the loop.
    """
    r = client.post("/measure/cost_lot_breakdown",
                    json={"params": {"lot": 4, "rate_vintage": "2021-02-01"}})
    assert r.status_code == 200, f"a wrong-but-well-formed vintage returned {r.status_code}"
    body = r.json()
    assert body["refused"] is True
    assert body["outcome"] == "not_in_model", body
    assert body["available"] == ["2022-02-01"], (
        f"the refusal must name what lot 4 accepts; got {body.get('available')!r}"
    )
    # THE POSITIVE CONTROL: the vintage it names must then work, or the refusal has sent the
    # caller somewhere else that fails.
    ok = client.post("/measure/cost_lot_breakdown",
                     json={"params": {"lot": 4, "rate_vintage": body["available"][0]}})
    assert ok.json().get("refused") is not True and len(ok.json()["rows"]) == 5


def test_no_lot_and_vintage_combination_anywhere_in_the_model_can_500(client):
    """THE CENSUS, because the case that reached a user was one cell of a 9x13 grid.

    Every lot crossed with every vintage any lot accepts: 9 lots, and the union of vintages
    across all fiscal years. Most of those pairs are wrong, and EVERY one of them must be a
    refusal rather than an exception.
    """
    all_vintages = sorted({v for (_fy, v) in STATE.rates})
    assert len(all_vintages) >= 12, all_vintages

    bad = []
    for lot in STATE.lot_numbers:
        for vintage in all_vintages:
            r = client.post("/measure/cost_lot_breakdown",
                            json={"params": {"lot": lot, "rate_vintage": vintage}})
            if r.status_code != 200:
                bad.append((lot, vintage, r.status_code))
    assert not bad, f"these lot/vintage pairs did not refuse cleanly: {bad[:8]}"


def test_a_verb_with_no_option_source_still_refuses_cleanly(client):
    """OPTION_SOURCES is keyed on (verb, slot) and covers one pair today. The absence of an
    entry must not become an error — a verb nobody has written options for still has to be
    able to ask for its slot."""
    r = client.post("/measure/package_export", json={"params": {}})
    body = r.json()
    assert body["refused"] is True and body["outcome"] == "slot_required"
    assert "recipient_scope" in body["missing"]
    assert "options" not in body


def test_the_two_verbs_naming_the_SAME_factors_use_the_SAME_labels(client):
    """⚠ "G And A" REACHED A LIVE CHART because one verb derived its labels from the keys.

    `cost_rate_comparison` reads `_RATE_LABELS` and says "G&A". `cost_rate_assumptions`
    built its `series` labels with `key.replace("_"," ").title()` and said "G And A" — so two
    verbs over the SAME six factors spoke two vocabularies, and the renderer drew exactly
    what it was sent. A renderer cannot tell a derived label from an authored one.

    ASSERTED AS AGREEMENT BETWEEN THE TWO VERBS rather than against a literal, because a
    literal here would be a third place for the vocabulary to live.
    """
    series = client.post("/measure/cost_rate_assumptions",
                         json={"params": {"fiscal_year": 2021}}).json()["series"]
    by_key = {s["key"]: s["label"] for s in series}

    # THE LABELS LIVE IN `effects`, NOT `rows`. `rows` carries the raw `factor` key; the
    # human name is on the effect. Reading the wrong one made this seal fail against a
    # CORRECT fix — a null comparison set is not a disagreement, so the check below also
    # requires the set to be non-empty.
    effects = client.post("/measure/cost_rate_comparison",
                          json={"params": {"lot": 3, "rate_vintage": "2021-02-01"}}).json()["effects"]
    comparison_labels = {e["metric"] for e in effects}
    assert len(comparison_labels) == 6, comparison_labels

    assert by_key, "no series returned; this seal would pass vacuously"
    disagreed = {k: v for k, v in by_key.items() if v not in comparison_labels}
    assert not disagreed, (
        f"these factors are labelled differently by the two verbs that report them: "
        f"{disagreed} — the comparison verb says {sorted(comparison_labels)}"
    )
    assert by_key["g_and_a"] == "G&A", by_key["g_and_a"]


@pytest.mark.parametrize("verb", sorted(measures.VERBS))
def test_NO_verb_500s_on_a_param_it_does_not_declare(client, verb):
    """⚠ AN UNDECLARED PARAM WAS A 500, ACROSS EVERY VERB.

    Found by probing `cost_labor_composition` with `rate_vintage`: the verb has no such slot,
    the param reached `fn(**params)`, and TypeError escaped as a 500. The `slot_required`
    branch upstream exists to stop exactly that crash for a MISSING slot and nothing guarded
    the opposite direction.

    THIS IS NOT HYPOTHETICAL ONCE SLOTS ACCUMULATE. The interview loop's fix is to merge
    bound slots across hops; a chain that answered `rate_vintage` for one verb then carries it
    into a neighbour with no such slot. The fix that closes the loop would have opened this.

    OVER EVERY VERB, since the defect was in the shared route and the one I probed was
    incidental.
    """
    params = {d["name"]: _plausible(d) for d in slot_decls.slots_for(verb) if d["required"]}
    r = client.post(f"/measure/{verb}",
                    json={"params": {**params, "definitely_not_a_slot": "x"}})
    assert r.status_code == 200, f"{verb} returned {r.status_code} for an undeclared param"
    body = r.json()
    assert "definitely_not_a_slot" in body.get("ignored_params", []), (
        f"{verb} accepted an undeclared param without recording that it was ignored; a "
        f"silently dropped param means the answer does not reflect the question asked"
    )


def _plausible(decl):
    """A value of the declared type, so the call gets past validation to the point at issue."""
    if decl["name"] == "lot":
        return 3
    if decl["name"] == "rate_vintage":
        return "2021-02-01"
    if decl["name"] == "recipient_scope":
        return "notional-customer-alpha"
    if decl["name"] == "fiscal_year":
        return 2021
    return {"integer": 1, "number": 1, "boolean": True}.get(decl["type"], "x")


def test_a_clean_call_does_NOT_carry_an_empty_ignored_params(client):
    """Absence means nothing was dropped. An empty list would be a third state nobody needs,
    and a consumer checking truthiness and one checking presence would disagree."""
    body = client.post("/measure/cost_labor_composition",
                       json={"params": {"lot": 4}}).json()
    assert "ignored_params" not in body, body.get("ignored_params")
