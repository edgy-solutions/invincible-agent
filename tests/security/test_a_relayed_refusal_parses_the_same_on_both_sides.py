"""A refusal relayed through a Restate TerminalError parses to the same dict on both sides.

Architect, 2026-10-27 (ruling 1 on the policy-refusal rule): the refusal rides as `refusal:` + its
JSON in the TerminalError message and is parsed at the BFF; "until then your prefix form, with a
seal that both parse to the same dict". The engines' half is `agent_fleet.utils.terminal_refusal`,
the BFF's is `src.iagent.authz.refusal` (`TERMINAL_PREFIX`, `from_terminal`). Two copies, because an
engine image carries no `src/`; this file is what keeps them one format.

The agreement arm is DIFFERENTIAL over a population that holds both outcomes -- messages that
carry a refusal and messages that do not -- so it cannot pass by both sides answering None.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from agent_fleet.utils import terminal_refusal as engine
from src.iagent.authz import refusal as bff

ROOT = Path(__file__).resolve().parents[2]

#: (policy_id, missing_binding, candidates) an engine may send. Colons, unicode and quotes ride in
#: the JSON, never in the prefix.
_SENT = [
    ("capability_grants:mesh:startReview", "can_invoke(mesh:startReview)", ()),
    ("program_members", "can_view_program(program)", ("NP-MERIDIAN", "SANDBOX_PROGRAM_ALPHA")),
    ("config:DELEGATE_ON_BEHALF_OF", 'delegate_of("svc:é")', ()),
]

#: Messages that carry no refusal, each a way a parser could disagree with its twin.
_NOT_REFUSALS = [
    None, 42, b"refusal:{}", "", "refusal:", "refusal:{", "refusal:[]", "refusal:null",
    'refusal:"x"', "Refusal:{}", " refusal:{}", "access denied (can_invoke) on service task t",
    "refusal:" + "[" * 5000 + "]" * 5000,  # deep enough to recurse past the interpreter's limit
]


def _population():
    return [engine.to_terminal(*s) for s in _SENT] + _NOT_REFUSALS + [
        'refusal: {"policy_id":"groups","missing_binding":"member_of(g)"}',  # space after prefix
        'refusal:{"policy_id":"groups"}',  # incomplete: parsed, and relay_refusal declines it
    ]


def test_the_prefix_is_one_string_on_both_sides():
    assert engine.PREFIX == bff.TERMINAL_PREFIX == "refusal:"


@pytest.mark.parametrize("message", _population(), ids=lambda m: repr(m)[:40])
def test_both_sides_parse_every_message_to_the_same_dict(message):
    assert engine.from_terminal(message) == bff.from_terminal(message)


def test_the_population_holds_both_outcomes():
    """Control: agreement over messages that all parse to None would prove nothing."""
    out = [bff.from_terminal(m) for m in _population()]
    assert any(o is None for o in out) and any(isinstance(o, dict) for o in out)
    assert all(bff.from_terminal(m) is None for m in _NOT_REFUSALS)


@pytest.mark.parametrize("sent", _SENT, ids=lambda s: s[0])
def test_what_an_engine_sends_is_what_the_bff_reads(sent):
    policy_id, missing, candidates = sent
    assert bff.from_terminal(engine.to_terminal(*sent)) == {
        "policy_id": policy_id, "missing_binding": missing, "candidates": list(candidates)}


def test_an_engine_never_writes_the_grantor():
    """The grantor is the deployment's fact: the BFF fills it from its map, never the engine."""
    body = engine.from_terminal(engine.to_terminal("groups", "member_of(g)"))
    assert "grantable_by" not in body


def test_a_relayed_message_reaches_the_caller_filled_and_narrowed(monkeypatch):
    """The whole BFF path for one relayed refusal: Restate's error body, the BFF's own message
    extractor, the decoder, then `relay_refusal` -- which fills the grantor from this deployment's
    map and narrows a key an engine should not have named."""
    import sys
    if str(ROOT / "src") not in sys.path:
        sys.path.insert(0, str(ROOT / "src"))
    import iagent.gateway as gw
    import iagent.authz.refusal as live
    monkeypatch.setattr(live, "_GRANTORS_CACHE", None)
    monkeypatch.delenv("GRANTOR_OVERLAY_DIRS", raising=False)

    def restate(message):
        return httpx.Response(500, json={"code": 500, "message": message})

    msg = engine.to_terminal("capability_grants:mesh:startReview", "can_invoke(mesh:startReview)")
    parsed = live.from_terminal(gw._restate_refusal_message(restate(msg)))
    assert parsed is not None
    out = live.relay_refusal({"refusal": parsed})["refusal"]
    assert out == live.refusal("capability_grants:mesh:startReview", "can_invoke(mesh:startReview)")
    seed = live.grantors()["capability_grants"]
    assert out["grantable_by"] == f"{seed.who}; {seed.how}"

    leaky = engine.to_terminal("program_members:SECRET_PROGRAM", "can_view_program(program)")
    narrowed = live.relay_refusal(
        {"refusal": live.from_terminal(gw._restate_refusal_message(restate(leaky)))})
    assert narrowed["refusal"]["policy_id"] == "program_members"
    assert "SECRET_PROGRAM" not in json.dumps(narrowed)

    # Ruling 3: a candidate is an object the caller holds a view grant on, and the BFF cannot
    # check an engine's list against the caller, so a relay offers none.
    offered = engine.to_terminal("groups", "member_of(g)", ["OTHER_PROGRAM"])
    relayed = live.relay_refusal(
        {"refusal": live.from_terminal(gw._restate_refusal_message(restate(offered)))})
    assert relayed["refusal"]["candidates"] == []

    # A TerminalError that carries no refusal is still the plain reason it was.
    plain = gw._restate_refusal_message(restate("access denied (x) on service task t"))
    assert live.from_terminal(plain) is None and plain.startswith("access denied")
