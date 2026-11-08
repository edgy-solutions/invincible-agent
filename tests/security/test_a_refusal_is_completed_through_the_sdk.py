"""The BFF's refusal is the SDK's: a `PartialRefusal`, completed here with the grantor.

Architect, 2026-10-31, fork 2: option (b), `PartialRefusal` (SDK v0.9.13), completed at the BFF.
Option (a), a placeholder `grantable_by` on the engine side, was refused as a lie on the wire.

`test_a_relayed_refusal_parses_the_same_on_both_sides.py` holds the two parsers to one format and
`test_every_policy_refusal_names_policy_binding_grantor.py` holds the envelope's content. This file
holds the join: the path goes THROUGH the SDK's model, and that model's strictness never turns a
deny into a 500.
"""
from __future__ import annotations

import json
import logging

import pytest
from iagent_mesh import PartialRefusal, Refusal

from agent_fleet.utils import terminal_refusal as engine
from src.iagent.authz import refusal as R

_NAMES = {"policy_id": "groups", "missing_binding": "member_of(g)"}


@pytest.fixture(autouse=True)
def _seed_grantors(monkeypatch):
    monkeypatch.setattr(R, "_GRANTORS_CACHE", None)
    monkeypatch.delenv("GRANTOR_OVERLAY_DIRS", raising=False)


@pytest.fixture
def completed(monkeypatch):
    """Every `PartialRefusal.complete` call the path makes, by the grantor it was given."""
    seen = []
    real = PartialRefusal.complete

    def spy(self, grantable_by):
        seen.append(grantable_by)
        return real(self, grantable_by)

    monkeypatch.setattr(PartialRefusal, "complete", spy)
    return seen


def test_a_site_refusal_goes_through_the_sdk(completed):
    out = R.refusal("groups", "member_of(g)", ["a"])
    seed = R.grantors()["groups"]
    assert completed == [f"{seed.who}; {seed.how}"]
    assert out == {**_NAMES, "grantable_by": completed[0], "candidates": ["a"]}


def test_a_relayed_refusal_goes_through_the_sdk(completed):
    out = R.relay_refusal({"refusal": dict(_NAMES)})
    assert len(completed) == 1 and out["refusal"]["grantable_by"] == completed[0]


def test_what_an_engine_sends_is_a_partial_refusal_and_not_a_refusal():
    """Why fork 2 exists: the model that requires a grantor refuses what an engine can send, and
    the partial takes it. If the first stopped holding, an engine would be speaking for the
    deployment; if the second did, every relayed refusal would lose its envelope."""
    body = engine.from_terminal(engine.to_terminal("groups", "member_of(g)", ["a"]))
    with pytest.raises(ValueError):
        Refusal.model_validate(body)
    assert Refusal.from_terminal(engine.to_terminal("groups", "member_of(g)")) is None
    partial = PartialRefusal.model_validate(body)
    assert (partial.policy_id, partial.missing_binding, partial.candidates) == (
        "groups", "member_of(g)", ("a",))


def test_a_relay_takes_the_two_names_and_nothing_else_an_engine_wrote():
    """The partial forbids extra keys and the relay has always ignored them. An engine's own
    `grantable_by` is overwritten and its `candidates` dropped (ruling 3), not refused."""
    out = R.relay_refusal({"refusal": {**_NAMES, "candidates": ["OTHER_PROGRAM"],
                                       "grantable_by": "an engine may not speak for the deployment",
                                       "unknown": "x"}})
    assert out["refusal"] == R.refusal("groups", "member_of(g)")
    assert "OTHER_PROGRAM" not in json.dumps(out)


#: Names that pass the relay's gate and that no refusal can be completed from. Measured against
#: the relay before this seal: a non-string raised AttributeError, `:key` and a blank binding raised
#: ValueError, each a 500 on the deny path; a blank policy id relayed a "not declared" envelope.
_UNCOMPLETABLE = [
    {"policy_id": 5, "missing_binding": "m"},
    {"policy_id": "groups", "missing_binding": 5},
    {"policy_id": ":SECRET_KEY", "missing_binding": "m"},
    {"policy_id": "   ", "missing_binding": "m"},
    {"policy_id": "groups", "missing_binding": "   "},
    {"policy_id": ["program_members:SECRET_KEY"], "missing_binding": "m"},
]


@pytest.mark.parametrize("r", _UNCOMPLETABLE, ids=lambda r: repr(r)[:40])
def test_names_that_cannot_be_completed_lose_the_envelope_and_keep_the_deny(r, caplog):
    up = {"error": "not_entitled", "message": "no", "refusal": {**r, "grantable_by": "engine"}}
    with caplog.at_level(logging.ERROR, logger=R.logger.name):
        out = R.relay_refusal(up)
    assert out == {"error": "not_entitled", "message": "no"}
    assert "could not be completed" in caplog.text


def test_a_map_that_will_not_load_keeps_the_deny(monkeypatch, caplog):
    """`DeclarationError` is a ValueError: the same arm, and the same answer."""
    def broken():
        raise R._declaration_error()("a broken overlay row")

    monkeypatch.setattr(R, "grantors", broken)
    with caplog.at_level(logging.ERROR, logger=R.logger.name):
        out = R.relay_refusal({"error": "x", "refusal": dict(_NAMES)})
    assert out == {"error": "x"}
    assert "could not be completed" in caplog.text


def test_a_key_on_an_object_scoped_family_still_narrows():
    """Control for the arm above: a body it CAN complete keeps its envelope."""
    out = R.relay_refusal({"refusal": {"policy_id": "program_members:SECRET_KEY",
                                       "missing_binding": "m"}})
    assert out["refusal"]["policy_id"] == "program_members"
    assert out["refusal"]["grantable_by"]
    assert "SECRET_KEY" not in json.dumps(out)


@pytest.mark.parametrize("bad", ["", "   ", None, 5], ids=repr)
def test_an_unusable_candidate_is_omitted_and_the_rest_are_kept(bad, caplog):
    """Candidates are data, so a bad row is not a malformed call site."""
    with caplog.at_level(logging.ERROR, logger=R.logger.name):
        out = R.refusal("groups", "member_of(g)", ["a", bad, "b"])
    assert out["candidates"] == ["a", "b"]
    assert "omitted 1" in caplog.text


@pytest.mark.parametrize("call", [("", "m"), ("groups", ""), ("groups", "   "), (":k", "m")],
                         ids=repr)
def test_a_malformed_call_site_is_still_a_value_error(call):
    with pytest.raises(ValueError):
        R.refusal(*call)


def test_the_published_refusal_models_are_the_sdks():
    """The two contract models were hand-copies. They stay named, because the published schemas
    name them, and differ from the SDK's only where those schemas already did."""
    from src.iagent import gateway, ingest_api
    for model in (gateway.CanvasSeedRefusal, ingest_api.RefusalEnvelope):
        assert issubclass(model, Refusal)
        assert tuple(model.model_fields) == tuple(Refusal.model_fields)
        assert model.model_fields["candidates"].is_required()


def test_the_wire_form_is_json_ready():
    """A plain dict with a list, not a model or the SDK's tuple: it goes in an HTTPException."""
    out = R.refusal("groups", "member_of(g)", ("a",))
    assert type(out) is dict and type(out["candidates"]) is list
    assert json.loads(json.dumps(out)) == out
