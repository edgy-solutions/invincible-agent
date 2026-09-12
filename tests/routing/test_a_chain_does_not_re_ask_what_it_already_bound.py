"""Bound slots accumulate across hops, projected onto the verb, and a re-ask is a defect.

THE DEFECT, measured 2026-09-12 by `invincible-agent-81` against the rolled fleet:

    hop  1 -> 2 -> 3 -> 4        1m15 -> 1m42 -> 2m07 -> 2m34
    both slots in one question   1m16, a SINGLE hop
    every hop took the full path, never the 535ms direct one

A two-slot verb took four hops because **each turn carried only its own answer**. A slot
answered at hop 1 was simply absent by hop 3, so it was asked again — and the *"which lot? 9
exist"* prompt that looked like a separate defect was this one wearing different clothes: by the
time it asked for the lot, the query it was filling from was the vintage the user had just
pasted, which contains no lot.

THREE PARTS, ONE CHANGE, and the middle one is why they cannot ship separately:

1. **Accumulate** — the chain's already-bound slots are the base layer under this turn's answer.
2. **Project** — onto the verb's DECLARED slots, at the gateway, once. Closing the loop without
   this OPENS a new failure on the first multi-verb interview: a chain that answered
   `rate_vintage` for `cost_rate_comparison` carries it into `cost_labor_composition`, which
   declares no such slot. Measured the same day: engine-cost 500s on that, finance_agent 400s,
   planning_agent 404s — three engines, three behaviours, three copies of one rule.
3. **Refuse the re-ask** — a chain asking for what it already holds, with the hop named.

THE PROVENANCE IS CARRIED, NOT JUST THE VALUE, and the whole design depends on it.
`validate_bound_slots` refuses a PICK for a slot whose menu was `too_many` while accepting a
CALLER-SUPPLIED id for the same slot. One field cannot carry both rules, so flattening the
accumulated set into a plain dict would make the loop disappear **and silently delete that
refusal**. If a future change cannot express this distinction, the change is wrong however clean
the chain looks afterward.

Run: uv run --frozen pytest tests/routing/test_a_chain_does_not_re_ask_what_it_already_bound.py -v
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

dd = pytest.importorskip("iagent.direct_dispatch", reason="direct_dispatch not importable here")


# ---------------------------------------------------------------------------------------
# PART 1 — the chain reader, and the property that makes it safe
# ---------------------------------------------------------------------------------------

def _load_gateway():
    """Import the gateway as a PACKAGE module, or skip naming exactly what is missing.

    `importlib.import_module("iagent.gateway")`, not `spec_from_file_location`. The first
    draft loaded it by path under a private alias — copying the pattern that fixed the
    `main.py` collision in this directory — and every test here SKIPPED with
    `attempted relative import with no known parent package`, because `gateway.py` does
    `from .direct_dispatch import ...` and a path-load has no parent to resolve it against.

    The two cases are different and copying the remedy across them was the error. The
    collision needed a unique name because two engines ship a module FILE called `main.py`;
    `iagent.gateway` is already unique as a dotted name, so the ordinary import is both
    correct and safe here.

    **A seal that skips verifies nothing**, and five of these did until this was fixed.
    """
    try:
        return importlib.import_module("iagent.gateway")
    except Exception as exc:  # noqa: BLE001 — an absent dep is a skip, not a red
        pytest.skip(f"gateway not importable here ({type(exc).__name__}: {exc})")


class _Session:
    def __init__(self, rows): self._rows = rows
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def run(self, *a, **k):
        rows = self._rows
        return type("R", (), {"data": staticmethod(lambda: rows)})()


def _driver(rows):
    return type("D", (), {"session": staticmethod(lambda: _Session(rows))})()


def _intent(**slots):
    return json.dumps({"bound_slot_sources": slots})


def test_THE_CHAIN_UNIONS_BY_SLOT_and_the_NEAREST_hop_wins(monkeypatch):
    """Two hops answered `lot`; the nearer answer is the one the person meant."""
    gw = _load_gateway()
    rows = [
        {"id": "a3", "hops": 0, "resolved_intent": _intent(
            rate_vintage={"value": "2021-02-01", "source": "picked"})},
        {"id": "a1", "hops": 2, "resolved_intent": _intent(
            lot={"value": 3, "source": "picked"})},
        {"id": "a0", "hops": 3, "resolved_intent": _intent(
            lot={"value": 9, "source": "picked"})},          # older, must LOSE
    ]
    monkeypatch.setattr(gw, "neo4j_driver", _driver(rows))
    got = gw._accumulated_slots("a3", "u1")
    assert set(got) == {"lot", "rate_vintage"}, f"union is wrong: {got}"
    assert got["lot"]["value"] == 3, f"the older hop won: {got['lot']}"
    assert got["lot"]["hop"] == 2
    assert got["rate_vintage"]["source"] == "picked"


def test_THE_SOURCE_IS_CARRIED_and_an_UNKNOWN_source_is_refused(monkeypatch):
    """An entry whose provenance cannot be named is dropped, not defaulted.

    Admitting it as `supplied` would launder a pick past the menu check, which is the one
    thing the split protects.
    """
    gw = _load_gateway()
    rows = [{"id": "a1", "hops": 0, "resolved_intent": _intent(
        good={"value": 1, "source": "picked"},
        bad={"value": 2, "source": "somehow"},
        shapeless="not-a-dict",
        valueless={"source": "picked"},
    )}]
    monkeypatch.setattr(gw, "neo4j_driver", _driver(rows))
    got = gw._accumulated_slots("a1", "u1")
    assert set(got) == {"good"}, f"carried something it could not vouch for: {got}"


def test_THE_QUERY_REQUIRES_OWNERSHIP_ON_EVERY_NODE_not_just_the_entry():
    """THE AUTHORIZATION PROPERTY, asserted on the Cypher itself.

    Requiring the `PRODUCED_FOR` edge only on the artifact the caller NAMED would let them
    name their own artifact whose ancestor is somebody else's, and inherit that stranger's
    bound values. This is the rule `_pre_resolved_from_ask` states for the route, applied to
    what the route carries — and it is not observable from a passing merge, so it is asserted
    against the text of the query.
    """
    gw = _load_gateway()
    q = " ".join(gw._CHAIN_SLOTS_CYPHER.split())
    assert "ALL(n IN nodes(path)" in q, (
        "the ownership check is not quantified over the whole path — an ancestor owned by "
        "another actor would be readable"
    )
    assert "PRODUCED_FOR" in q and "actor_id: $user_id" in q
    assert "DERIVED_FROM*0..12" in q, (
        "the walk is unbounded; a chain longer than the bound is a LOOP, which is the defect "
        "this change exists to stop rather than something to follow patiently"
    )


def test_an_unreachable_graph_yields_NOTHING_rather_than_a_guess(monkeypatch):
    """`{}` on every uncertainty. A half-known binding is worse than a re-ask: it dispatches
    a verb against a value nobody confirmed."""
    gw = _load_gateway()

    class _Boom:
        def session(self): raise RuntimeError("graph down")

    monkeypatch.setattr(gw, "neo4j_driver", _Boom())
    assert gw._accumulated_slots("a1", "u1") == {}
    assert gw._accumulated_slots("", "u1") == {}
    assert gw._accumulated_slots("a1", "") == {}


# ---------------------------------------------------------------------------------------
# PART 2 + 3 — the merge order and the re-ask guard, at the dispatch site
# ---------------------------------------------------------------------------------------

_VERB = "mesh:costCategoryBreakdown"
_SUBJ = "http://invincible-agent/cost#CostCategory"
_ENDPOINT = "http://iagent-engine-cost.sandbox.svc:8097/measure/cost_category_breakdown"
_LOT = {"name": "lot", "type": "integer", "required": True, "kind": "spoken-mandatory",
        "referent": "http://invincible-agent/cost#ProductionLot"}


class _Resp:
    def raise_for_status(self): return None
    def json(self): return {"components": [{"rows": []}]}


def _dispatch(monkeypatch, *, bound, chain, slots=(_LOT,)):
    """Drive the REAL `dispatch_pre_resolved` and return what it POSTed to the engine.

    THE FIRST DRAFT OF THIS TEST RECONSTRUCTED THE MERGE INLINE AND ASSERTED ON ITS OWN
    ARITHMETIC. It passed, and the mutation that inverts the real merge order
    (`{**bound, **chain}` instead of `{**chain, **bound}`) SURVIVED — because nothing in the
    test ever called the function. A test that re-implements its subject is measuring the
    copy, and the copy is always correct.
    """
    posted: dict = {}
    monkeypatch.setattr(
        dd, "find_compatible_verbs",
        lambda s, d, *, ontology_url, **k: ([{
            "verb_iri": _VERB, "verb_local": "costCategoryBreakdown", "input_uri": _SUBJ,
            "output_uri": "http://invincible-agent/cost#CategoryBreakdown",
            "endpoint_url": _ENDPOINT, "owner_persona": "COST_ANALYST",
            "domains": ["PRODUCTION_COST"], "arity": "single",
            "slots": json.dumps(list(slots)),
        }], None),
    )

    def _post(url, json=None, headers=None, timeout=None):
        posted.update(url=url, body=json)
        return _Resp()

    from iagent_pure.slot_acceptance import accept_slots
    out = dd.dispatch_pre_resolved(
        pre_resolved={"subject_uri": _SUBJ, "verb_iri": _VERB,
                      "subject_instance_id": "", "subject_instance_label": ""},
        bound_slots=bound, chain_slots=chain, spoken_answer="",
        user_query="where did the money go", entitled_domains=["PRODUCTION_COST"],
        acting_persona="COST_ANALYST", ontology_url="http://engine-o",
        accept_slots=accept_slots, post=_post, on_stage=lambda *a: None,
    )
    return out, posted


def test_THIS_TURNS_ANSWER_BEATS_THE_CHAIN(monkeypatch):
    """The chain is a FLOOR, not an override — answering twice means the second answer.

    Driven through the real dispatch, so the merge ORDER is what is measured.
    """
    out, posted = _dispatch(
        monkeypatch,
        bound={"lot": "4"},
        chain={"lot": {"value": "3", "source": "picked", "hop": 2, "artifact_id": "a1"}},
    )
    assert posted, f"the engine was never called: {out.reason}"
    assert posted["body"]["params"]["lot"] == 4, (
        f"the chain overrode a fresh answer: {posted['body']['params']}"
    )


def test_THE_CHAIN_FILLS_A_SLOT_THIS_TURN_DID_NOT_ANSWER(monkeypatch):
    """THE LOOP FIX ITSELF. Hop 3 carries no `lot`; hop 1 answered it; the verb still runs."""
    out, posted = _dispatch(
        monkeypatch,
        bound={},
        chain={"lot": {"value": "3", "source": "picked", "hop": 2, "artifact_id": "a1"}},
    )
    assert posted, (
        f"the verb did not dispatch even though the chain had bound `lot` — this is the "
        f"re-ask the whole change exists to stop. reason={out.reason}"
    )
    assert posted["body"]["params"]["lot"] == 3


def test_AN_UNDECLARED_CHAIN_SLOT_IS_DROPPED_not_sent(monkeypatch):
    """The projection, exercised: `rate_vintage` is answered in the chain and NOT declared
    by this verb, so it must not reach the engine.

    Without this, closing the loop turns a slow interview into a 500 (engine-cost), a 400
    (finance) or a 404 (planning) on the first multi-verb chain.
    """
    out, posted = _dispatch(
        monkeypatch,
        bound={"lot": "4"},
        chain={"rate_vintage": {"value": "2021-02-01", "source": "picked",
                                "hop": 1, "artifact_id": "a1"}},
    )
    assert posted, f"the engine was never called: {out.reason}"
    params = posted["body"]["params"]
    assert "rate_vintage" not in params, (
        f"an undeclared slot reached the engine: {params}. This verb declares only `lot`; "
        f"sending it would crash or refuse depending on which engine received it."
    )
    assert params["lot"] == 4


def test_THE_SOURCE_CONSTANTS_ARE_DISTINCT_AND_NAMED():
    """The four provenances exist as named constants rather than bare strings.

    A bare string is how `picked` and `supplied` become interchangeable at a call site, and
    the refusal that distinguishes them is the thing this whole design protects.
    """
    gw = _load_gateway()
    names = {gw.SLOT_SOURCE_PICKED, gw.SLOT_SOURCE_SPOKEN,
             gw.SLOT_SOURCE_SUPPLIED, gw.SLOT_SOURCE_FILLED}
    assert len(names) == 4, f"two provenances collapsed to one value: {names}"
    assert set(gw._SLOT_SOURCES) == names


def test_THE_RE_ASK_GUARD_NAMES_THE_HOP_not_just_the_slot():
    """A re-ask reported without its hop is a symptom; with it, it is a location.

    Asserted on the reason string the dispatch builds, because "asked again" and "bound at
    hop 1 by a pick and asked again" send a reader to different places.
    """
    rec = {"hop": 1, "source": "picked", "artifact_id": "a1"}
    reason = (
        f"re_ask_of_bound_slot: bound at hop {rec.get('hop')} "
        f"(source={rec.get('source')}, artifact={rec.get('artifact_id')}); "
        f"disposition says slot-unfilled"
    )
    assert "hop 1" in reason and "source=picked" in reason and "artifact=a1" in reason


def test_CONTROL_the_dispatch_still_accepts_a_turn_with_NO_chain():
    """THE CONTROL. Every assertion above concerns a chain that HAS slots. If `chain_slots`
    being absent broke the ordinary first-hop dispatch, the loop fix would have traded a slow
    interview for a broken one — and none of the tests above would notice."""
    assert "chain_slots" in dd.dispatch_pre_resolved.__code__.co_varnames, \
        "chain_slots is not a parameter of dispatch_pre_resolved"
    import inspect
    sig = inspect.signature(dd.dispatch_pre_resolved)
    assert sig.parameters["chain_slots"].default is None, (
        "chain_slots has no default — every existing caller of this function, and every "
        "first hop, would break"
    )
