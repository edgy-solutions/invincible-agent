"""An answer routed before the intent hop exports its verb (measured 2026-10-28).

43 Portfolio answers written before `e4154f91` (2026-09-04) carry `resolved_intent` =
the ExtractIntent output (no `verb_iri`) and name the verb only in `routing_inline`
(`action.iri`). The export read `resolved_intent` alone and refused them as `no_verb`. The two
homes agreed on all 1,018 artifacts carrying both. Supervisor-abstain answers read
`action.iri == "UNKNOWN"`: they have no verb, and `no_verb` stays their true refusal.

Fixture rows are the MEASURED shapes (synthetic ids, JSON strings as the store holds them).
The refusal codes come from the REAL `canvas.resolve`; no rule is restated here.
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi")

from agent_fleet.cost_agent import canvas as C  # noqa: E402
from agent_fleet.cost_agent.entities import NotInModel  # noqa: E402
from agent_fleet.cost_agent.seed import lots_for_recipient  # noqa: E402
from src.iagent import gateway  # noqa: E402

ALPHA = "notional-customer-alpha"

PRE_HOP_INTENT = json.dumps({
    "mode": "ONE_SHOT", "entity_refs": [], "confidence": 0.97, "reasoning": "synthetic"})


def _routing(iri, about=None):
    return json.dumps({
        "about": about or {"label": "Portfolio",
                           "uri": "http://invincible-agent/idp#Portfolio", "confidence": 0.92},
        "action": {"label": "x", "iri": iri, "confidence": 0.95, "classify_called": True,
                   "candidate_count": 10, "owner_persona": "PORTFOLIO_LEAD"},
        "handled_by": {"engine_name": "Engine P"},
    })


class _Rec:
    def __init__(self, row): self._row = row
    def get(self, k, d=None): return self._row.get(k, d)
    def __getitem__(self, k): return self._row[k]
    def single(self): return self


class _Session:
    def __init__(self, store): self._store = store
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def run(self, _c, artifact_id=None, **_k): return _Rec(self._store[artifact_id])


class _Driver:
    def __init__(self, store): self._store = store
    def session(self): return _Session(self._store)


def _export(monkeypatch, rows):
    """rows: {id: (resolved_intent_json, routing_inline)} -> `_resolve_export_answers` output."""
    store = {i: {"id": i, "is_owner": True, "resolved_intent": ri, "routing_inline": rt}
             for i, (ri, rt) in rows.items()}
    monkeypatch.setattr(gateway, "neo4j_driver", _Driver(store))
    return gateway._resolve_export_answers(list(rows), "sub-alice")


def test_a_pre_hop_answer_exports_the_verb_its_routing_record_names(monkeypatch):
    out = _export(monkeypatch, {"a1": (PRE_HOP_INTENT, _routing("mesh:planSchedule"))})
    assert out[0]["verb_iri"] == "mesh:planSchedule"


def test_a_supervisor_abstain_has_no_verb(monkeypatch):
    out = _export(monkeypatch, {"a2": (PRE_HOP_INTENT, _routing("UNKNOWN"))})
    assert out[0]["verb_iri"] is None


def test_the_intent_verb_wins_over_the_routing_record(monkeypatch):
    intent = json.dumps({"verb_iri": "mesh:planCostCurve"})
    out = _export(monkeypatch, {"a3": (intent, _routing("mesh:planSchedule"))})
    assert out[0]["verb_iri"] == "mesh:planCostCurve"


@pytest.mark.parametrize("routing", [None, "not json", "[]", '{"action": "x"}', "{}"])
def test_a_malformed_routing_record_gives_no_verb_and_never_raises(monkeypatch, routing):
    out = _export(monkeypatch, {"a4": (PRE_HOP_INTENT, routing)})
    assert out[0]["verb_iri"] is None


def test_the_subject_instance_is_never_read_from_the_routing_record(monkeypatch):
    about = {"label": "Lot", "uri": "u", "instance_identifier": "7"}
    out = _export(monkeypatch, {"a5": (PRE_HOP_INTENT, _routing("mesh:planSchedule", about))})
    assert out[0]["subject_instance_id"] is None


def test_the_real_canvas_names_the_pre_hop_refusal_true_and_keeps_no_verb_for_abstain(monkeypatch):
    out = _export(monkeypatch, {
        "pre": (PRE_HOP_INTENT, _routing("mesh:planSchedule")),
        "abs": (PRE_HOP_INTENT, _routing("UNKNOWN")),
    })
    with pytest.raises(NotInModel) as ei:
        C.resolve({"answers": out}, recipient_scope=ALPHA,
                  entitled_lots=lots_for_recipient(ALPHA))
    codes = {r["answer_id"]: r["reason_code"] for r in ei.value.refused}
    assert codes["pre"] == "not_an_exportable_cost_verb"
    assert codes["abs"] == "no_verb"
