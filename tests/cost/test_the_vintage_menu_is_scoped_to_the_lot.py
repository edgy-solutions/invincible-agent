"""The vintage menu: a referent is only worth declaring if its chips survive the verb.

TWO HALVES, ONE COMMIT, AND THIS IS THE SEAL THAT KEEPS THEM TOGETHER. Declaring
`referent: cost#RateTable` on `rate_vintage` alone does not turn a free-text box into a good
menu — it turns it into a TWELVE-option class-wide menu, because `class_wide` has exactly one
producer (`slot_disposition.py:496`) behind a `declared_scope ∩ offered` test that needs a
`narrowed_by` no row has. Ten of those twelve are invalid for any given lot, and — the sharper
half, measured 2026-09-23 — all twelve are in the id form `<fy>-<vintage>` while the slot
accepts a bare `<vintage>`, so the class-wide ids intersect the accepted values in NOTHING.
A chip from that menu is refused by the verb even when the user picks the right vintage, which
is worse than free text by engine-cost's own standard: free text does not imply validity, a
menu does.

WHY THE CLASS-WIDE TEST IS HERE. `test_the_scoped_menu...` alone would pass for the wrong
reason if `bound_slots` were dropped and the class-wide list happened to be right. The
class-wide assertion is the fixture that discriminates: it pins that the unscoped answer is
NOT an acceptable menu, so the scoped test can only pass because the scoping ran.
"""
from __future__ import annotations

import pathlib

import pytest
import yaml
from fastapi.testclient import TestClient

from agent_fleet.cost_agent import instances, measures
from agent_fleet.cost_agent.main import STATE, app

_REPO = pathlib.Path(__file__).resolve().parents[2]
_ROW = _REPO / "policy" / "graphs" / "cost_lot_costing_review.yaml"

COST = "http://invincible-agent/cost#"
RATE_TABLE = COST + "RateTable"

#: Lot 3 is fiscal year 2021, which has exactly these two vintages. Written out rather than
#: derived so this file states what it expects; the JOIN test below asserts the engine's own
#: computation agrees, which is the check that catches a fixture change.
LOT_3_VINTAGES = ["2021-02-01", "2021-08-01"]


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _enumerate(client, **body) -> dict:
    r = client.post("/enumerate_instances", json={"class_uri": RATE_TABLE, **body})
    assert r.status_code == 200, r.text
    return r.json()


def test_the_scoped_menu_offers_exactly_what_the_verb_accepts(client):
    """The point of the whole change: bind the lot, get that lot's vintages, in the slot's form."""
    body = _enumerate(client, bound_slots={"lot": 3})

    assert body["outcome"] == "members", body
    ids = [m["instance_id"] for m in body["members"]]
    assert ids == LOT_3_VINTAGES, (
        f"the scoped menu offers {ids}, and lot 3 accepts {LOT_3_VINTAGES}"
    )
    assert body["scoped_by"] == ["lot"], (
        f"scoped_by is {body.get('scoped_by')!r} — engine-o reads an ABSENT or empty scoped_by "
        f"as class-wide (ontology_service/main.py:2318-2333), so a menu that narrowed and did "
        f"not say so has its chips treated as class-wide and refused"
    )


def test_the_scoped_menu_and_the_ROUTE_agree_about_what_is_available(client):
    """THE JOIN. Two computations of one truth that used to meet nowhere.

    `enumerate_class` narrows through `measures._SLOT_OPTION_SOURCES`, and the refusal path
    computes `options` from the same registry. They are one declaration, and this is the
    assertion that keeps them one — a second derivation of the value form inside `instances`
    would be invisible to any test that read only one side.
    """
    ids = [m["instance_id"] for m in _enumerate(client, bound_slots={"lot": 3})["members"]]
    accepted = measures.options_for(STATE, "cost_lot_breakdown", "rate_vintage", {"lot": 3})

    assert accepted is not None, "the engine cannot compute lot 3's vintages at all"
    assert ids == list(accepted), (
        f"the menu offers {ids} and the verb would accept {list(accepted)} — one truth, two "
        f"answers"
    )


def test_the_CLASS_WIDE_menu_offers_NOTHING_the_verb_accepts(client):
    """The discriminating fixture, and the reason the referent could not ship on its own.

    This is a seal on a DEFECT, deliberately: if a later change makes the class-wide ids
    acceptable to the verb, this test reds and whoever is reading it gets to decide whether
    the scoping is still required. It must not be "fixed" by deleting it.
    """
    body = _enumerate(client)

    assert body["outcome"] == "members", body
    assert not body.get("scoped_by"), (
        f"the UNSCOPED call reported scoped_by={body.get('scoped_by')!r}; a provider claiming a "
        f"narrowing it did not do is the one direction engine-o's contract cannot detect"
    )
    class_wide = {m["instance_id"] for m in body["members"]}
    accepted = set(measures.options_for(STATE, "cost_lot_breakdown", "rate_vintage", {"lot": 3}))

    assert class_wide, "the class-wide menu is empty, so this fixture discriminates nothing"
    assert class_wide & accepted == set(), (
        f"class-wide ids now intersect what lot 3 accepts ({sorted(class_wide & accepted)}); the "
        f"id-form defect this scoping exists for may be gone — re-decide, do not delete"
    )


def test_every_chip_the_scoped_menu_DRAWS_survives_the_verb(client):
    """READ THE CONSUMER. A menu is only correct if the thing it feeds accepts its values.

    Every earlier assertion here compares the menu against another computation. This one spends
    the chips: each `instance_id` goes into the verb the ask was blocking on, and a refusal means
    the menu was wrong however well it agreed with its neighbours.
    """
    ids = [m["instance_id"] for m in _enumerate(client, bound_slots={"lot": 3})["members"]]
    assert ids, "no chips to spend"

    for chip in ids:
        r = client.post("/measure/cost_lot_breakdown",
                        json={"params": {"lot": 3, "rate_vintage": chip}})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("refused") is not True, (
            f"the menu drew {chip!r} and the verb refused it ({body.get('outcome')!r}) — the "
            f"chips must be values the verb takes, not merely ids of the referent class"
        )


def test_the_GRAPH_ROW_declares_the_referent_and_no_inert_scope():
    """Half (a), and the two ways it can go wrong.

    Without the referent the scoped enumeration above is unreachable from a card — it would be
    correct code nothing calls. With a `narrowed_by` it would declare a runtime guard that the
    PINNED SDK (v0.9.3) does not enforce, so the row would read as protected when it is not;
    that guard arrives in v0.9.4 and the order is cut, then pin, then declare.
    """
    row = yaml.safe_load(_ROW.read_text(encoding="utf-8"))
    slots = {s["name"]: s for s in row["slots"]}

    assert slots["rate_vintage"].get("referent") == RATE_TABLE, (
        f"rate_vintage declares referent {slots['rate_vintage'].get('referent')!r}; without "
        f"{RATE_TABLE} the lot-scoped menu is code no card can reach"
    )
    assert "narrowed_by" not in slots["rate_vintage"], (
        "rate_vintage declares narrowed_by, which is INERT on the pinned v0.9.3 — a declared "
        "scope nothing enforces reads as a guard and is not one"
    )


def test_the_scopeable_registry_is_not_a_sample():
    """The shape that bit this engine before: a per-slot fix that covered one of three verbs.

    Every class named in `_SCOPED_BY_SLOT` must be enumerable at all, and the slot it scopes to
    must have a real option source. A typo in either makes the scoping silently never fire and
    the card silently falls back to the twelve-chip menu.
    """
    assert instances._SCOPED_BY_SLOT, "the registry is empty; nothing is scoped"
    for class_uri, (slot, needs) in instances._SCOPED_BY_SLOT.items():
        assert class_uri in instances._RESOLVABLE, (
            f"{class_uri} is declared scopeable but is not enumerable at all"
        )
        assert slot in measures._SLOT_OPTION_SOURCES, (
            f"{class_uri} scopes to slot {slot!r}, which has no option source — the scoped "
            f"branch would compute None and fall through to the class-wide menu"
        )
        assert needs, f"{class_uri} declares no slots to scope by, so the branch can never fire"
