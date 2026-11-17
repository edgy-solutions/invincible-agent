"""A name known only outside the asked domains abstains as `domain_scope_excluded`, not
`instance_not_found`.

MEASURED 2026-11-16 on sandbox, read-only, through engine-o's own `/resolve_instance`. A notice
id was asked with three active domains (a picker cell outside the notice's domain). The one
provider that knew the id exactly sat in a fourth domain that the caller holds but had not made
active. Its claim was demoted, which is correct (`test_an_out_of_domain_hit_is_a_candidate_not_an_authority.py`).
The structural gate then reported "No provider in the mesh recognizes it". That was false, and
it told the caller to check their spelling. A second try, made after the browser sent the
notice's domain, answered.

THE RULE. The demoted claims never resolve the question. They are put through the SAME decision
table, and only when nothing in the asked domains resolved. If they would have resolved it, the
name is known elsewhere and the abstention says so, naming the resolving provider's declared
domains. Every existing gate comes first: an infra non-answer and a generic term still keep
their current behaviour.

The candidate set below is the 14 the provider returned for the dropper, as measured. The
controls are the 3 sub-floor candidates it returned for a caller who cannot see the notice, a
name nobody knows, the same 14 asked in the provider's own domain, and a generic term.

IN-PROCESS: the fan-out and the class-chain read are stubbed, as in the sibling seal.

Run: uv run --frozen pytest tests/routing/test_a_name_known_in_another_domain_says_so.py -v
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import re
import sys
from pathlib import Path

import httpx
import pytest

_REPO = Path(__file__).resolve().parents[2]
_OS = _REPO / "agent_fleet" / "ontology_service"
if str(_OS) not in sys.path:
    sys.path.insert(0, str(_OS))

_MOD_NAME = "ontology_service_main_known_elsewhere"
_spec = importlib.util.spec_from_file_location(_MOD_NAME, str(_OS / "main.py"))
if _spec is None or _spec.loader is None:  # pragma: no cover
    pytest.skip("ontology_service/main.py not found", allow_module_level=True)
main = importlib.util.module_from_spec(_spec)
sys.modules[_MOD_NAME] = main
try:
    _spec.loader.exec_module(main)
except Exception as _exc:  # noqa: BLE001
    sys.modules.pop(_MOD_NAME, None)
    pytest.skip(
        f"ontology_service not importable here ({type(_exc).__name__}: {_exc}). "
        f"Run: uv run --frozen --with rdflib pytest {Path(__file__).name}",
        allow_module_level=True,
    )


class _Cand:
    def __init__(self, instance_id, class_uri, label, score, provider, matched_on=""):
        self.instance_id, self.class_uri = instance_id, class_uri
        self.label, self.score, self.provider = label, score, provider
        self.matched_on = matched_on


class _Outcome:
    def __init__(self, provider, candidates):
        self.provider, self.candidates = provider, candidates
        self.status, self.endpoint_url, self.elapsed_s = "ok", "http://stub", 0.01


_NS = "http://internal/sustainment/"
_PCN = _NS + "pcn#ProcessChangeNotification"
_PDN = _NS + "pcn#ProductDiscontinuationNotice"
_PROVIDER = "provider-under-test"
_PROVIDER_DOMAIN = "DOMAIN_OF_THE_NOTICE"
_ASKED = ["ASKED_A", "ASKED_B", "ASKED_C"]
_ID = "PCN26-182"


def _c(label, score, cls=_PCN):
    return _Cand(_NS + "doc/" + label, cls, label, score, _PROVIDER)


#: what the provider returned to the notice's dropper (measured, score and class as served)
_DROPPER_SEES = [
    _c("PCN26-182", 1.0),
    _c("PCN26-121", 0.889), _c("PCN26-180", 0.889), _c("PCN26-184", 0.889), _c("PCN26-185", 0.889),
    _c("PCN26-117", 0.778), _c("PCN26-119", 0.778), _c("PCN26-207", 0.778),
    _c("PCN-2683", 0.706), _c("PCN24-029", 0.667), _c("PCN-24-210412", 0.636),
    _c("PCN-23-002", 0.632), _c("PCN-24-060", 0.526), _c("PDN-23_0120", 0.5, _PDN),
]
#: what it returned to a caller who cannot see the notice: all below the floor
_OTHERS_SEE = [_c("PCN24-029", 0.667), _c("PCN-23-002", 0.632), _c("PDN-23_0120", 0.5, _PDN)]


_PERSON = "caller@example.org"
_OTHER_DOMAIN = "SECOND_DOMAIN_OF_THE_PROVIDER"


class _Held:
    """A recording fake for `main._held_domains_of`: what the directory returns, and who asked."""

    def __init__(self, result=(), raises=None):
        self.result, self.raises, self.calls = set(result), raises, []

    def __call__(self, user_id):
        self.calls.append(user_id)
        if self.raises is not None:
            raise self.raises
        return frozenset(self.result)


def _resolve(monkeypatch, candidates, asked, identifier=_ID, *, held=None,
             user_email=_PERSON, provider_domains=(_PROVIDER_DOMAIN,)):
    held = held if held is not None else _Held()
    monkeypatch.setattr(main, "_held_domains_of", held, raising=False)
    resolvers = [{"provider": _PROVIDER, "endpoint_url": "http://p", "timeout_s": None,
                  "domains": list(provider_domains)}]
    monkeypatch.setattr(main, "_discover_instance_resolvers",
                        lambda *a, **k: main.MeshResult.answered(resolvers))

    async def _fake_call(resolver, term, query, **_caller):
        return _Outcome(_PROVIDER, list(candidates))

    async def _no_chains(uris):
        return {}, "unavailable"

    monkeypatch.setattr(main, "_call_resolver", _fake_call)
    monkeypatch.setattr(main, "_read_class_chains", _no_chains)
    return asyncio.run(main._resolve_instance(
        identifier, "which parts does it affect", asked,
        user_email=user_email, entitled_domains=list(asked)))


def _answer(identifier, subject, prov):
    """The user-visible pair `resolve()` builds from what `_resolve_instance` returned, by the
    SAME functions and arguments it calls (this does not run `resolve()` itself)."""
    reason = _gate(identifier, subject, prov)
    if reason == "domain_scope_excluded":
        return reason, main._ir_out_of_domain_msg(
            identifier, prov.get("instance_out_of_domain_domains"))
    return reason, main._ir_not_found_msg(identifier)


def _gate(identifier, subject, prov):
    """The call site's own arguments, read from the provenance the call site reads."""
    return main._ir_abstention(
        identifier=identifier,
        instance_subject=subject,
        instance_match=str(prov.get("instance_match") or ""),
        resolves_out_of_domain=bool(prov.get("instance_resolves_out_of_domain")),
    )


# ── the seal ──────────────────────────────────────────────────────────────────────────

def test_A_NAME_KNOWN_ONLY_ELSEWHERE_SAYS_SO_to_a_caller_entitled_to_that_domain(monkeypatch):
    held = _Held({_PROVIDER_DOMAIN.lower()})
    subject, prov = _resolve(monkeypatch, _DROPPER_SEES, _ASKED, held=held)
    assert subject is None, (
        f"the out-of-domain claim RESOLVED the question to {subject!r}: the shadow decision "
        f"is acting as an authority, which the 2026-09-11 ruling forbids")
    assert prov.get("instance_resolves_out_of_domain") is True, (
        f"an exact out-of-domain hit was not recorded as one: {sorted(prov)}")
    assert prov.get("instance_out_of_domain_domains") == [_PROVIDER_DOMAIN]
    assert held.calls == [_PERSON]
    reason, msg = _answer(_ID, subject, prov)
    assert reason == "domain_scope_excluded", (
        f"abstained as {reason!r}: the caller is told nobody knows a name one provider "
        f"knows exactly")
    assert _ID in msg and _PROVIDER_DOMAIN in msg
    assert "recognizes" not in msg, "the message still claims nobody recognizes the name"


def _assert_plain_not_found(subject, prov, unnamed, domains=(_PROVIDER_DOMAIN,)):
    assert subject is None
    assert "instance_resolves_out_of_domain" not in prov
    assert "instance_out_of_domain_domains" not in prov
    assert prov.get("instance_out_of_domain_unnamed") == unnamed
    reason, msg = _answer(_ID, subject, prov)
    assert reason == "instance_not_found"
    assert msg == main._ir_not_found_msg(_ID), "not byte-identical to a name nobody knows"
    seen = json.dumps([reason, msg])
    for d in domains:
        assert d not in seen, f"{d} reached the user-visible answer"


def test_A_NAME_KNOWN_ELSEWHERE_is_a_plain_not_found_to_a_caller_NOT_entitled(monkeypatch):
    held = _Held({"SOMETHING_ELSE"})
    subject, prov = _resolve(monkeypatch, _DROPPER_SEES, _ASKED, held=held)
    _assert_plain_not_found(subject, prov, "not_entitled")
    assert held.calls == [_PERSON]


def test_an_empty_entitlement_is_not_entitled(monkeypatch):
    subject, prov = _resolve(monkeypatch, _DROPPER_SEES, _ASKED, held=_Held())
    _assert_plain_not_found(subject, prov, "not_entitled")


def test_PARTIAL_only_the_held_domain_is_named(monkeypatch):
    held = _Held({_PROVIDER_DOMAIN})
    subject, prov = _resolve(monkeypatch, _DROPPER_SEES, _ASKED, held=held,
                             provider_domains=(_PROVIDER_DOMAIN, _OTHER_DOMAIN))
    assert prov.get("instance_out_of_domain_domains") == [_PROVIDER_DOMAIN]
    reason, msg = _answer(_ID, subject, prov)
    assert reason == "domain_scope_excluded" and _PROVIDER_DOMAIN in msg
    assert _OTHER_DOMAIN not in json.dumps([reason, msg, prov["instance_out_of_domain_domains"]])


def test_DIRECTORY_DOWN_fails_closed_to_a_plain_not_found(monkeypatch):
    held = _Held(raises=httpx.ConnectError("directory down"))
    subject, prov = _resolve(monkeypatch, _DROPPER_SEES, _ASKED, held=held)
    _assert_plain_not_found(subject, prov, "directory_unavailable")
    assert held.calls == [_PERSON]


@pytest.mark.parametrize("who", ["svc:x", ""])
def test_NOT_A_PERSON_gets_no_lookup_and_a_plain_not_found(monkeypatch, who):
    held = _Held({_PROVIDER_DOMAIN})
    subject, prov = _resolve(monkeypatch, _DROPPER_SEES, _ASKED, held=held, user_email=who)
    _assert_plain_not_found(subject, prov, "no_person")
    assert held.calls == [], "the directory was asked about a non-person"


def test_NO_LOOKUP_off_the_shadow_path(monkeypatch):
    held = _Held({_PROVIDER_DOMAIN})
    _resolve(monkeypatch, _DROPPER_SEES, _ASKED + [_PROVIDER_DOMAIN], held=held)
    _resolve(monkeypatch, [], _ASKED, identifier="ZZQ-0000", held=held)
    _resolve(monkeypatch, _OTHERS_SEE, _ASKED, held=held)
    assert held.calls == [], "the directory was read on a path that is not the shadow decision"


def test_the_supervisor_keeps_no_out_of_domain_provenance_key():
    sup = (_REPO / "src" / "iagent" / "defs" / "dynamic_supervisor.py").read_text(encoding="utf-8")
    i = sup.index('provenance = data.get("provenance") or {}')
    block = sup[i:sup.index("def _find_compatible_verbs", i)]
    keys = set(re.findall(r'provenance\.get\("([^"]+)"\)', block))
    assert keys == {"instance_id", "abstention_reason", "instance_label"}, keys
    assert "instance_out_of_domain" not in block


# ── its controls ──────────────────────────────────────────────────────────────────────

def test_control_SUB_FLOOR_claims_elsewhere_are_still_not_found(monkeypatch):
    """Known-elsewhere must mean RESOLVES elsewhere. A fuzzy near-miss is not knowing it."""
    subject, prov = _resolve(monkeypatch, _OTHERS_SEE, _ASKED)
    assert prov.get("instance_out_of_domain_demoted"), "CONTROL INVALID: nothing was demoted"
    assert not prov.get("instance_resolves_out_of_domain")
    assert _gate(_ID, subject, prov) == "instance_not_found"


def test_control_A_NAME_NOBODY_KNOWS_is_still_not_found(monkeypatch):
    subject, prov = _resolve(monkeypatch, [], _ASKED, identifier="ZZQ-0000")
    assert not prov.get("instance_resolves_out_of_domain")
    assert _gate("ZZQ-0000", subject, prov) == "instance_not_found"


def test_control_THE_SAME_CLAIMS_ASKED_IN_THEIR_OWN_DOMAIN_resolve(monkeypatch):
    """Without this the seal could pass on a candidate set that never resolves at all."""
    subject, prov = _resolve(monkeypatch, _DROPPER_SEES, _ASKED + [_PROVIDER_DOMAIN])
    assert subject == _PCN and prov.get("instance_match") == "exact", (
        subject, prov.get("instance_match"))
    assert not prov.get("instance_resolves_out_of_domain")


def test_control_A_GENERIC_TERM_keeps_the_class_fallback(monkeypatch):
    """The existing gates come first: a phrase that is not instance-shaped is not abstained on."""
    subject, prov = _resolve(monkeypatch, _DROPPER_SEES, _ASKED, identifier="the notice")
    assert _gate("the notice", subject, prov) is None


# ── the wiring the seal relies on ─────────────────────────────────────────────────────

def test_the_call_site_reads_the_flag_and_returns_the_reason():
    src = (_OS / "main.py").read_text(encoding="utf-8")
    i = src.index("STRUCTURAL ABSTENTION GATE")
    block = src[i:i + 2500]
    assert re.search(r'resolves_out_of_domain=bool\(\s*instance_provenance\.get\(\s*'
                     r'"instance_resolves_out_of_domain"\)\)', block), \
        "the abstention gate does not read the out-of-domain flag"
    assert 'abstention_reason"] = _abstain' in block
    assert "_ir_out_of_domain_msg(" in block


def test_the_router_passes_the_reason_through():
    sup = (_REPO / "src" / "iagent" / "defs" / "dynamic_supervisor.py").read_text(encoding="utf-8")
    i = sup.index("_ENGINE_O_ABSTENTION_REASONS = frozenset({")
    assert '"domain_scope_excluded"' in sup[i:i + 300], (
        "engine-o's reason would flatten to subject_unknown at the router")
