"""Ruling 3 (2026-10-15): a slot accepts a candidate whose class is the referent OR a subclass.

PR #57 moved safety's `part_number` referent from `safety:SafetyCriticalItem` to `pcn:Component`.
A SafetyCriticalItem IS a Component (`rdfs:subClassOf`), but both consumers compared
`class_uri == referent` and dropped it. `slot_disposition` is pure, so Engine O sends the chain
on the candidate (`class_chain`); a candidate without one keeps the exact-match behaviour.

Run: uv run pytest tests/test_a_slot_accepts_a_subclass_of_its_referent.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from iagent_pure.slot_disposition import _from_candidates, validate_bound_slots  # noqa: E402

# Read from setup/ontologies/safety_extension.ttl prefixes and agent_fleet/safety_agent/slots.py.
SAFETY = "http://internal/sustainment/safety#"
PCN = "http://internal/sustainment/pcn#"
CRITICAL = SAFETY + "SafetyCriticalItem"
COMPONENT = PCN + "Component"
HAZARD = SAFETY + "Hazard"


def _decl(referent):
    return f'[{{"name": "part_number", "kind": "spoken-mandatory", "referent": "{referent}"}}]'


def _cand(chain=True, cls=CRITICAL, extra_chain=(COMPONENT,)):
    c = {"class_uri": cls, "instance_id": "CSI-8802", "label": "PN-8802"}
    if chain:
        c["class_chain"] = [cls, *extra_chain]
    return c


# -- _from_candidates --------------------------------------------------------

def test_a_subclass_candidate_is_kept_for_the_superclass_referent():
    opts, n = _from_candidates([_cand()], referent=COMPONENT, menu_bound=8)
    assert n == 0 and [(o.value, o.label) for o in opts] == [("CSI-8802", "PN-8802")]


def test_the_same_candidate_is_kept_for_its_own_class():
    opts, n = _from_candidates([_cand()], referent=CRITICAL, menu_bound=8)
    assert n == 0 and opts[0].value == "CSI-8802"


def test_an_unrelated_class_is_dropped():
    c = _cand(cls=HAZARD, extra_chain=(SAFETY + "Thing",))
    assert _from_candidates([c], referent=COMPONENT, menu_bound=8) == ((), 0)


def test_no_chain_means_exact_match_so_the_chain_is_what_admits():
    """CONTROL: identical candidate minus `class_chain` is dropped."""
    assert _from_candidates([_cand(chain=False)], referent=COMPONENT, menu_bound=8) == ((), 0)


# -- validate_bound_slots ----------------------------------------------------

def _validate(cand, referent):
    picked, refusals, _res = validate_bound_slots(
        {"part_number": "CSI-8802"}, declared=_decl(referent),
        resolve_identifier=lambda _n, _r: [cand],
    )
    return picked, refusals


def test_validate_keeps_a_subclass_candidate():
    picked, refusals = _validate(_cand(), COMPONENT)
    assert picked == {"part_number": "CSI-8802"} and not refusals


def test_validate_keeps_the_exact_class():
    picked, _ = _validate(_cand(), CRITICAL)
    assert picked == {"part_number": "CSI-8802"}


def test_validate_drops_an_unrelated_class():
    picked, refusals = _validate(_cand(cls=HAZARD, extra_chain=()), COMPONENT)
    assert not picked and any("no_menu" in r for r in refusals)


def test_validate_without_a_chain_is_exact_match():
    picked, refusals = _validate(_cand(chain=False), COMPONENT)
    assert not picked and any("no_menu" in r for r in refusals)


# -- Engine O: the chain is built from ONE batched query and never invented --

class _Session:
    def __init__(self, drv):
        self._d = drv

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def run(self, cypher, **params):
        self._d.calls.append((cypher, params))
        if self._d.fail:
            raise RuntimeError("graph down")
        return [{"uri": u, "chain": self._d.graph[u]} for u in params["uris"] if u in self._d.graph]


class _Driver:
    def __init__(self, graph, fail=False):
        self.graph, self.fail, self.calls = graph, fail, []

    def session(self):
        return _Session(self)


@pytest.fixture()
def eo():
    from agent_fleet.ontology_service import main as m
    return m


def test_engine_o_attaches_the_chain_in_one_batched_query(eo, monkeypatch):
    drv = _Driver({CRITICAL: [CRITICAL, COMPONENT, "http://x#Top"], COMPONENT: [COMPONENT]})
    monkeypatch.setattr(eo, "_NEO4J_DRIVER", drv)
    cands = [
        {"instance_id": "a", "class_uri": CRITICAL},
        {"instance_id": "b", "class_uri": CRITICAL},
        {"instance_id": "c", "class_uri": COMPONENT},
        {"instance_id": "d", "class_uri": "http://x#NoNode"},
        {"instance_id": "e"},
    ]
    out = asyncio.run(eo._attach_class_chains(cands))
    assert len(drv.calls) == 1, "one query per response, not per candidate"
    assert sorted(drv.calls[0][1]["uris"]) == sorted([CRITICAL, COMPONENT, "http://x#NoNode"])
    assert "subClassOf*0..5" in drv.calls[0][0]
    assert out[0]["class_chain"] == [CRITICAL, COMPONENT, "http://x#Top"]
    assert out[2]["class_chain"] == [COMPONENT]
    assert "class_chain" not in out[3] and "class_chain" not in out[4]
    assert "class_chain" not in cands[0], "the caller's dicts are not mutated"


def test_a_graph_error_yields_candidates_without_a_chain(eo, monkeypatch):
    monkeypatch.setattr(eo, "_NEO4J_DRIVER", _Driver({}, fail=True))
    out = asyncio.run(eo._attach_class_chains([{"instance_id": "a", "class_uri": CRITICAL}]))
    assert out == [{"instance_id": "a", "class_uri": CRITICAL}]


def test_resolve_instance_still_succeeds_when_the_graph_fails(eo, monkeypatch):
    cand = {"instance_id": "CSI-8802", "class_uri": CRITICAL, "label": "PN-8802", "score": 1.0}

    async def _rows(*_a, **_k):
        return []

    async def _filt(c, **_k):
        return c

    monkeypatch.setattr(eo, "execute_sparql", _rows)
    monkeypatch.setattr(eo, "_resolve_sustainment_candidates", lambda *_a, **_k: [dict(cand)])
    monkeypatch.setattr(eo, "_filter_sustainment_candidates", _filt)
    req = eo.ResolveInstanceRequest(identifier="PN-8802")

    monkeypatch.setattr(eo, "_NEO4J_DRIVER", _Driver({CRITICAL: [CRITICAL, COMPONENT]}))
    ok = asyncio.run(eo.resolve_instance(req))
    assert ok["candidates"][0]["class_chain"] == [CRITICAL, COMPONENT]

    monkeypatch.setattr(eo, "_NEO4J_DRIVER", _Driver({}, fail=True))
    bad = asyncio.run(eo.resolve_instance(req))
    assert bad["candidates"] == [cand]
