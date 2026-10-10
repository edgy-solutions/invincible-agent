"""PCN26-184: the notice slot is required, and an empty one is ASKED, never routed.

`FillVerbSlots` rule 2 calls an omitted parameter "correct and safe, the operation has its own
default". A REQUIRED slot has no default. The CODE fix, model-free: a required slot given
`""`/`null`/`[]` is refused by `/fill_slots` and by `accept_slots`, so it is ABSENT, and an absent
mandatory slot is an ask. `0` and `False` are answers. Optional slots are unchanged.

THE PROMPT IS UNCHANGED. The rule for a wording change is one wording filling 3/3 on every pinned
fleet model. The fill-slots step has one: `gpt-oss-128k:120b` (values-sandbox
`config.OLLAMA_MODEL`, reached at `config.OLLAMA_BASE_URL`). Measured 2026-10-09 against it, three
independent calls per wording: master's `_slot_spec` wording filled `notice_id` 3/3, and so did
the longer REQUIRED-plus-class wording it would have replaced. The wording already holds on the
model the fleet calls, so none is changed; the live arm below is that measurement, re-runnable.

"3/3 MUST HOLD" is read as: the live slot arm (`IA_LIVE_SLOT_MODEL` set) fills `notice_id` with
PCN26-184 on each of three independent calls. The deterministic arms do not need repeating.
"""
from __future__ import annotations

import asyncio
import json
import os

import pytest

from agent_fleet.ontology_service import notice_parts as np_mod
from agent_fleet.utils.slot_declarations import derive_slots

NOTICE = "PCN26-184"
QUESTION = "which parts does PCN26-184 affect"


def _which_parts(notice_id: str):
    """The verb's spoken surface: one notice. Stands in for a handler signature so the
    declaration comes from `derive_slots`, the same deriver every registration uses."""


def _decls():
    return derive_slots(_which_parts, referents={"notice_id": np_mod.INPUT_URI})


# ── an empty required slot is asked, never routed ────────────────────────────────────────
#
# `FillVerbSlots` rule 2 calls an omitted parameter "correct and safe, the operation has its own
# default". `notice_id` has no default. Whatever the model does with the prompt, the CODE must not
# let a required slot through empty: `""`/`null`/`[]` is PRESENT, the supervisor's `ask` fires
# only on an ABSENT mandatory slot, so an accepted empty routes as filled. Model-free throughout.

_EMPTIES = ["", "   ", None, []]


def test_THE_NOTICE_SLOT_IS_A_REQUIRED_REFERENT_TO_A_SUSTAINMENT_NOTICE():
    """The fixture's own premise: if the deriver stops marking it, the arms below test nothing."""
    (d,) = _decls()
    assert (d["name"], d["kind"], d["required"], d["referent"]) == (
        "notice_id", "spoken-mandatory", True, np_mod.INPUT_URI)


def _fill(monkeypatch, slots_json):
    """`/fill_slots` with the model stubbed to return `slots_json`, and the resolver stubbed to
    RECORD: an empty required slot must never reach `resolveInstance` (its `empty` abstains)."""
    from agent_fleet.ontology_service import main as eo
    resolved = []

    class _Filled:
        confidence, reasoning = 0.9, "stub"

    _Filled.slots_json = slots_json

    async def _fake_fill(**kw):
        return _Filled()

    async def _fake_resolve(spoken, *a, **kw):
        resolved.append(spoken)
        return None, {"instance_match": "empty"}

    monkeypatch.setattr(eo.b, "FillVerbSlots", _fake_fill)
    monkeypatch.setattr(eo, "_resolve_instance", _fake_resolve)
    out = asyncio.run(eo.fill_slots(eo.FillSlotsRequest(
        query=QUESTION, verb_iri=np_mod.VERB, declarations=json.dumps(_decls()))))
    return out, resolved


def _disposition(slots, resolution):
    from iagent_pure.slot_acceptance import SLOT_SOURCE_FILLED, accept_slots
    from iagent_pure.slot_disposition import decide_disposition
    acc = accept_slots(slots, _decls(), {k: SLOT_SOURCE_FILLED for k in slots})
    return acc, decide_disposition(accepted=acc.params, declared=_decls(),
                                   resolution=resolution, enumerate_class=None)


@pytest.mark.parametrize("empty", _EMPTIES, ids=repr)
def test_AN_EMPTY_REQUIRED_SLOT_FROM_THE_MODEL_IS_REFUSED_AND_NEVER_RESOLVED(monkeypatch, empty):
    out, resolved = _fill(monkeypatch, json.dumps({"notice_id": empty}))
    assert out.slots == {} and out.resolution == {}, (out.slots, out.resolution)
    assert resolved == [], "an empty required slot reached resolveInstance"
    assert [r for r in out.refused if r.startswith("notice_id=") and "required" in r], out.refused


@pytest.mark.parametrize("empty", _EMPTIES, ids=repr)
def test_THE_EMPTY_REQUIRED_SLOT_SURFACES_AS_AN_ASK(monkeypatch, empty):
    """The whole path the supervisor takes: fill, accept, decide. An ask for `notice_id`."""
    from iagent_pure.slot_disposition import ASK
    out, _ = _fill(monkeypatch, json.dumps({"notice_id": empty}))
    _, disp = _disposition(out.slots, out.resolution)
    assert (disp.action, disp.slot, disp.reason) == (ASK, "notice_id", "slot-unfilled"), disp


@pytest.mark.parametrize("empty", _EMPTIES, ids=repr)
def test_A_PRESENT_EMPTY_REQUIRED_SLOT_IS_REFUSED_AT_THE_SUPERVISOR_TOO(empty):
    """`accept_slots` is fed by more than the filler (a carried hop, an API caller). It refuses
    the empty value itself, so the ask does not depend on engine-o having dropped it."""
    from iagent_pure.slot_acceptance import EMPTY_MANDATORY
    from iagent_pure.slot_disposition import ASK
    acc, disp = _disposition({"notice_id": empty}, {})
    assert acc.params == {} and [r.reason for r in acc.refusals] == [EMPTY_MANDATORY]
    assert (disp.action, disp.slot) == (ASK, "notice_id"), disp


def test_CONTROL_A_FILLED_REQUIRED_SLOT_ROUTES():
    """Differs from the arms above in the VALUE only."""
    from iagent_pure.slot_disposition import ROUTE
    acc, disp = _disposition({"notice_id": NOTICE}, {})
    assert acc.params == {"notice_id": NOTICE} and not acc.refusals
    assert disp.action == ROUTE, disp


def test_CONTROL_AN_EMPTY_OPTIONAL_SLOT_IS_NOT_REFUSED():
    """Differs in ONE thing, the kind. Rule 2 is right about an optional slot, and this change
    leaves its handling exactly as it was."""
    from iagent_pure.slot_acceptance import SLOT_SOURCE_FILLED, accept_slots
    (d,) = _decls()
    opt = [{**d, "kind": "spoken-optional", "required": False}]
    acc = accept_slots({"notice_id": ""}, opt, {"notice_id": SLOT_SOURCE_FILLED})
    assert acc.params == {"notice_id": ""} and not acc.refusals


def test_CONTROL_AN_EMPTY_OPTIONAL_SLOT_PASSES_FILL_SLOTS_AS_BEFORE(monkeypatch):
    """The `/fill_slots` half of the control above, on a slot with no referent so the resolver is
    not involved: an optional slot's empty is accepted exactly as it was before this change."""
    from agent_fleet.ontology_service import main as eo
    (d,) = _decls()
    opt = {k: v for k, v in d.items() if k != "referent"}
    opt.update(kind="spoken-optional", required=False)

    class _Filled:
        slots_json, confidence, reasoning = json.dumps({"notice_id": ""}), 0.9, "stub"

    async def _fake_fill(**kw):
        return _Filled()

    monkeypatch.setattr(eo.b, "FillVerbSlots", _fake_fill)
    out = asyncio.run(eo.fill_slots(eo.FillSlotsRequest(
        query=QUESTION, verb_iri=np_mod.VERB, declarations=json.dumps([opt]))))
    assert out.slots == {"notice_id": ""} and out.refused == [], (out.slots, out.refused)


@pytest.mark.parametrize("answer", [0, False], ids=repr)
def test_CONTROL_ZERO_AND_FALSE_ARE_ANSWERS_NOT_EMPTIES(answer):
    from iagent_pure.slot_acceptance import SLOT_SOURCE_FILLED, accept_slots
    decl = [{"name": "lot", "kind": "spoken-mandatory", "type": "", "required": True}]
    acc = accept_slots({"lot": answer}, decl, {"lot": SLOT_SOURCE_FILLED})
    assert acc.params == {"lot": answer} and not acc.refusals


# ── live: 3/3, against the fleet's pinned model only ────────────────────────────────────────
#
# NEVER LOCAL INFERENCE. A harness that defaulted to the local Ollama port was answered by a
# laptop model and ate two cores on demo morning. The fleet's fill-slots model is the `Ollama`
# BAML client: `base_url env.OLLAMA_BASE_URL`, `model env.OLLAMA_MODEL`. So the arm REFUSES
# unless OLLAMA_HOST is set and is not the local default, OLLAMA_BASE_URL names the SAME endpoint
# (the client reads BASE_URL; a guard on HOST alone checks a variable nothing calls), and the
# model id is named explicitly. The fleet's server is a LAN GPU host on the default port, called
# direct; only a LOCAL host on that port is refused, so the default port alone is no refusal.

_LOCAL_HOSTS = ("localhost", "::1", "0.0.0.0")
_OLLAMA_DEFAULT_PORT = "11434"


def _endpoint(raw: str) -> tuple[str, str]:
    from urllib.parse import urlsplit
    raw = raw.strip()
    parts = urlsplit(raw if "//" in raw else "//" + raw)
    return (parts.hostname or "").lower(), str(parts.port or _OLLAMA_DEFAULT_PORT)


def _is_local(host: str) -> bool:
    return host in _LOCAL_HOSTS or host.startswith("127.")


def live_target_refusal(env) -> str | None:
    """Why the live arm must not run against `env`, or None. Pure, so it is tested below
    without any model and the scratch harnesses import the same rule."""
    host_raw = (env.get("OLLAMA_HOST") or "").strip()
    base_raw = (env.get("OLLAMA_BASE_URL") or "").strip()
    if not host_raw:
        return "OLLAMA_HOST is unset"
    host = _endpoint(host_raw)
    if _is_local(host[0]) and host[1] == _OLLAMA_DEFAULT_PORT:
        return f"OLLAMA_HOST={host_raw} is the local default; nothing local may answer"
    if not base_raw:
        return "OLLAMA_BASE_URL is unset (it is what the Ollama client calls)"
    if _endpoint(base_raw) != host:
        return f"OLLAMA_BASE_URL={base_raw} is not the endpoint OLLAMA_HOST={host_raw} names"
    if not (env.get("OLLAMA_MODEL") or "").strip():
        return "OLLAMA_MODEL is unset; name the pinned model id"
    return None


_FWD = "127.0.0.1:" + str(int(_OLLAMA_DEFAULT_PORT) + 1)   # a forwarded port, never the default
_LAN = "gpu-host.lan:" + _OLLAMA_DEFAULT_PORT                 # a named LAN host, the default port


_LOCAL_DEFAULT = "127.0.0.1:" + _OLLAMA_DEFAULT_PORT
_OK = {"OLLAMA_HOST": _FWD, "OLLAMA_BASE_URL": "http://" + _FWD + "/v1", "OLLAMA_MODEL": "m"}


# EACH FIXTURE IS THE ADMITTED TARGET WITH ONE THING CHANGED, and the arm names the refusal it
# must get. Asserting only "refused" let one check stand in for another: an unset host is also a
# host that disagrees with BASE_URL, so deleting the unset check stayed green.
@pytest.mark.parametrize("change, why", [
    ({"OLLAMA_HOST": None}, "OLLAMA_HOST is unset"),
    ({"OLLAMA_HOST": "   "}, "OLLAMA_HOST is unset"),
    ({"OLLAMA_HOST": "localhost:" + _OLLAMA_DEFAULT_PORT,
      "OLLAMA_BASE_URL": "http://localhost:" + _OLLAMA_DEFAULT_PORT + "/v1"}, "local default"),
    ({"OLLAMA_HOST": _LOCAL_DEFAULT, "OLLAMA_BASE_URL": "http://" + _LOCAL_DEFAULT + "/v1"},
     "local default"),
    ({"OLLAMA_HOST": "http://localhost", "OLLAMA_BASE_URL": "http://localhost/v1"}, "local default"),
    ({"OLLAMA_BASE_URL": None}, "OLLAMA_BASE_URL is unset"),
    ({"OLLAMA_BASE_URL": "http://" + _LOCAL_DEFAULT + "/v1"}, "is not the endpoint"),
    ({"OLLAMA_MODEL": " "}, "OLLAMA_MODEL is unset"),
], ids=["unset", "blank", "localhost", "loopback", "default-port", "no-base", "base-local", "no-model"])
def test_THE_LIVE_HARNESS_REFUSES_A_LOCAL_OR_UNNAMED_TARGET(change, why):
    env = {k: v for k, v in {**_OK, **change}.items() if v is not None}
    got = live_target_refusal(env)
    assert got and why in got, (env, got)


@pytest.mark.parametrize("target", [_LAN, _FWD], ids=["lan-host", "forwarded"])
def test_CONTROL_A_NON_LOCAL_PINNED_TARGET_IS_ADMITTED(target):
    """The fleet's own host on the default port, and a forwarded loopback port. The first is what
    the arm is run against; it also kills a refusal that reads the port alone."""
    env = {"OLLAMA_HOST": target, "OLLAMA_BASE_URL": "http://" + target + "/v1",
           "OLLAMA_MODEL": "pinned:tag"}
    assert live_target_refusal(env) is None


@pytest.mark.skipif(not os.environ.get("IA_LIVE_SLOT_MODEL"),
                    reason="live model arm: set IA_LIVE_SLOT_MODEL=1 plus OLLAMA_HOST, "
                           "OLLAMA_BASE_URL and OLLAMA_MODEL naming the fleet's pinned model")
def test_LIVE_THE_MODEL_FILLS_THE_NOTICE_THREE_TIMES_OF_THREE():
    """`FillVerbSlots` itself, with the spec `_slot_spec` builds. Three independent calls; each
    must fill `notice_id` with the notice as spoken. A miss is printed, not retried.

    PINNED TO THE FLEET'S `Ollama` CLIENT. `MainAgent` falls back OpenRouter -> OpenAI -> Ollama,
    and a missing cloud key is a BamlError, not a fallthrough; the registry skips the cloud legs
    so the arm measures the prompt, not which key this box happens to hold. REFUSES (fails, not
    skips) on a local or unnamed target: see `live_target_refusal`."""
    why = live_target_refusal(os.environ)
    if why:
        pytest.fail(f"refusing to run the live arm: {why}")
    from baml_py import ClientRegistry
    from agent_fleet.ontology_service import main as eo
    cr = ClientRegistry()
    cr.set_primary("Ollama")
    spec, _ = eo._slot_spec(_decls())
    got = []
    for _ in range(3):
        filled = asyncio.run(eo.b.FillVerbSlots(
            question=QUESTION, verb=np_mod.VERB, slot_spec=spec, today="unknown",
            baml_options={"client_registry": cr}))
        got.append(json.loads(filled.slots_json or "{}").get("notice_id"))
    assert got == [NOTICE] * 3, got
