"""EFFECT-WRITE GATE SEAL — engine-o's two `ungated_by_accident` writes, closed.

`/write_item_state` and `/write_decision_record` were classed `ungated_by_accident` by the
endpoint-gating manifest: transport auth is app-wide, so an UNAUTHENTICATED caller is refused
once REQUIRE flips — but nothing checked WHICH authenticated caller may perform the effect.
Any minted service could stamp disposition state or append to the decision corpus.

WHAT THIS SEALS, and the shape is the approval-bypass precedent's:
  * the DENY arm — a caller without the capability is refused;
  * the ALLOW arm — the granted caller passes. A deny-only assertion cannot tell a working
    gate from one stuck shut, and this arc has already shipped that bug once (a stub patched
    onto the wrong module object made a DENY pass while the stub was never consulted);
  * the DISCRIMINATING PAIR — allow and deny differ BY CALLER on the same capability, which
    is what proves the gate reads identity rather than answering uniformly;
  * the NO-OP phase — with ENABLE_AGENTIC_AUTH off the gate must not refuse, because the
    caller's `_fail_terminal_on_4xx` classes 403 as TERMINAL and a premature gate would make
    every disposition write PERMANENTLY fail rather than retry.

Run: uv run --frozen --with pytest --with httpx pytest tests/security/test_effect_write_gate.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_EO = _REPO / "agent_fleet" / "ontology_service"
for _p in (str(_EO), str(_REPO)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _mod():
    """Import engine-o's module. Skipped rather than failed when its heavy deps are absent —
    a missing optional dependency is not a security finding, and pretending otherwise would
    make this suite a flaky red that people learn to ignore."""
    try:
        import main as eo  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"engine-o module not importable in this env: {type(exc).__name__}: {exc}")
    return eo


class _Caller:
    def __init__(self, authz_id):
        self.authz_id = authz_id
        self.verified = bool(authz_id)
        self.reason = "test"


_GRANTED = "svc:review-starter"
_UNGRANTED = "svc:some-other-service"


def _decider(monkeypatch, eo, allow_for):
    """Stub the single decider so the gate's own logic is what is under test.

    The stub is keyed on (caller, capability) so the ALLOW and DENY arms differ by CALLER
    alone — a stub returning a constant would make the pair vacuous.
    """
    monkeypatch.setattr(eo, "ENABLE_AGENTIC_AUTH", True, raising=False)
    monkeypatch.setattr(eo, "TOPAZ_DIRECTORY_URL", "http://topaz-svc:8282", raising=False)
    monkeypatch.setattr(
        eo, "_can_invoke_capability",
        lambda who, cap: who == allow_for and bool(cap),
        raising=False,
    )


@pytest.mark.parametrize("cap_attr,what", [
    ("CAP_WRITE_ITEM_STATE", "write_item_state"),
    ("CAP_WRITE_DECISION_RECORD", "write_decision_record"),
])
def test_ungranted_caller_is_refused(monkeypatch, cap_attr, what):
    eo = _mod()
    _decider(monkeypatch, eo, allow_for=_GRANTED)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        eo._require_capability(_Caller(_UNGRANTED), getattr(eo, cap_attr), what)
    assert exc.value.status_code == 403


@pytest.mark.parametrize("cap_attr,what", [
    ("CAP_WRITE_ITEM_STATE", "write_item_state"),
    ("CAP_WRITE_DECISION_RECORD", "write_decision_record"),
])
def test_granted_caller_is_allowed(monkeypatch, cap_attr, what):
    """THE POSITIVE CONTROL. Without it a gate stuck permanently shut passes the deny arm."""
    eo = _mod()
    _decider(monkeypatch, eo, allow_for=_GRANTED)
    assert eo._require_capability(_Caller(_GRANTED), getattr(eo, cap_attr), what) == _GRANTED


def test_the_pair_discriminates_by_caller(monkeypatch):
    """Allow and deny on the SAME capability, differing only in who is asking."""
    eo = _mod()
    _decider(monkeypatch, eo, allow_for=_GRANTED)
    from fastapi import HTTPException
    assert eo._require_capability(_Caller(_GRANTED), eo.CAP_WRITE_ITEM_STATE, "w") == _GRANTED
    with pytest.raises(HTTPException):
        eo._require_capability(_Caller(_UNGRANTED), eo.CAP_WRITE_ITEM_STATE, "w")


def test_anonymous_caller_is_refused(monkeypatch):
    """No identity is not a pass. `authz_id=None` is the token-less caller the OBSERVE-phase
    `outbound_auth_headers` produces on a mint failure — it must be refused under the flag,
    not treated as trusted-by-default."""
    eo = _mod()
    _decider(monkeypatch, eo, allow_for=_GRANTED)
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        eo._require_capability(_Caller(None), eo.CAP_WRITE_ITEM_STATE, "w")


def test_gate_is_a_NOOP_before_the_flip(monkeypatch):
    """PHASE DISCIPLINE, and the reason this can land today.

    With ENABLE_AGENTIC_AUTH off the gate must allow even an ungranted caller. Gating before
    the flip would refuse every disposition write, and the caller's `_fail_terminal_on_4xx`
    classes 403 as TERMINAL — so those refusals would be PERMANENT rather than retried. The
    coordinated half of this fix is that the flip wires TOPAZ_DIRECTORY_URL at the same time.
    """
    eo = _mod()
    monkeypatch.setattr(eo, "ENABLE_AGENTIC_AUTH", False, raising=False)
    assert eo._can_invoke_capability(_UNGRANTED, eo.CAP_WRITE_ITEM_STATE) is True
    assert eo._require_capability(_Caller(_UNGRANTED), eo.CAP_WRITE_ITEM_STATE, "w") == _UNGRANTED


def test_fails_CLOSED_when_the_directory_url_is_unwired(monkeypatch):
    """The NAMED UNMET PRECONDITION, asserted rather than trusted.

    A DEFENSIVE property, not an outstanding precondition. The env IS wired
    (TOPAZ_DIRECTORY_URL=http://topaz-svc:9393 on both engines via iagent-config, verified in
    the running pods 2026-08-13) — an earlier version of this docstring said otherwise, from
    reading the deployment's env[] array without envFrom. The assertion still earns its place:
    it is what goes red if the env is ever dropped from the configMap.
    """
    eo = _mod()
    monkeypatch.setattr(eo, "ENABLE_AGENTIC_AUTH", True, raising=False)
    monkeypatch.setattr(eo, "TOPAZ_DIRECTORY_URL", "", raising=False)
    assert eo._can_invoke_capability(_GRANTED, eo.CAP_WRITE_ITEM_STATE) is False


def test_decider_errors_fail_CLOSED(monkeypatch):
    """A security gate must not fail open. Any transport error denies."""
    eo = _mod()
    monkeypatch.setattr(eo, "ENABLE_AGENTIC_AUTH", True, raising=False)
    monkeypatch.setattr(eo, "TOPAZ_DIRECTORY_URL", "http://topaz-svc:8282", raising=False)

    def _boom(*a, **k):
        raise RuntimeError("topaz unreachable")

    monkeypatch.setattr(eo.httpx, "post", _boom, raising=False)
    assert eo._can_invoke_capability(_GRANTED, eo.CAP_WRITE_ITEM_STATE) is False
