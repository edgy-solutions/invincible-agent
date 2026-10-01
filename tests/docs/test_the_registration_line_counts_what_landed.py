"""engine-docs says `registered N/M` only for verbs that landed, and /health tracks the retry.

MEASURED 2026-10-01: after the 03:33Z roll the shared helper logged `mesh registration:
UNREGISTERED` for engine-docs and engine-docs then printed `registered 1/1 verbs`. Two halves:

  PRODUCER. `register_engine_to_mesh` documents that every exit returns a `RegistrationResult`,
  and the live path -- MESH_REGISTRAR_URL set -- returned a bare `None` on success AND failure.
  CONSUMER. engine-docs counted every call that did not raise as a registration.

The arms drive the REAL helper. Only `register_with_mesh` (the SDK's network call) and
`_start_retry` (a daemon thread) are replaced, so the URN engine-docs derives is checked against
the key the helper actually records under, not against a restatement of it.
"""
from __future__ import annotations

import asyncio
import sys
import types

import pytest

import agent_fleet.docs_agent.main as m
import agent_fleet.utils.mesh_registration as mr
from iagent_mesh.registration_transport import RegistrationResult as SdkResult

N = len(m.VERBS)
VERB_IDS = [v["verb"] for v in m.VERBS]
_STATE_ATTRS = ("registration_failed", "registration_pending", "registration_status")


class _Registrar:
    """Stands in for the SDK transport: answers with the outcome it is set to, records calls."""

    def __init__(self, ok: bool):
        self.ok, self.calls = ok, []

    def __call__(self, registrar_url, manifest, component=None, mint=None, timeout=None):
        self.calls.append(component)
        return SdkResult(self.ok, "" if self.ok else "mint failed: keycloak 503", attempts=3)


@pytest.fixture
def fleet(monkeypatch):
    """A clean helper state, the gateway path configured, and engine-docs importing THIS helper."""
    monkeypatch.setattr(mr, "_REG_STATE", {"status": mr._REG_PENDING, "components": {},
                                           "last_error": None})
    retries = []
    monkeypatch.setattr(mr, "_start_retry",
                        lambda component, attempt: (retries.append(component),
                                                    mr._record(component, mr._REG_RETRYING)))
    monkeypatch.setenv("MESH_REGISTER_ON_STARTUP", "true")
    monkeypatch.setenv("MESH_REGISTRAR_URL", "http://registrar.test")
    monkeypatch.setenv("ENGINE_DOCS_CLIENT_SECRET", "unused-the-transport-is-replaced")
    # engine-docs imports FLAT FIRST; pin both spellings to one module object.
    flat = types.ModuleType("utils")
    flat.mesh_registration = mr
    monkeypatch.setitem(sys.modules, "utils", flat)
    monkeypatch.setitem(sys.modules, "utils.mesh_registration", mr)
    for a in _STATE_ATTRS:
        if hasattr(m.app.state, a):
            delattr(m.app.state, a)
    yield retries
    for a in _STATE_ATTRS:
        if hasattr(m.app.state, a):
            delattr(m.app.state, a)


def _start(monkeypatch, capsys, registrar):
    monkeypatch.setattr(mr, "register_with_mesh", registrar)

    async def _drive():
        async with m.lifespan(m.app):
            pass

    asyncio.run(_drive())
    return capsys.readouterr().out


# ── PRODUCER: every exit returns the type ──────────────────────────────────────────────────────

def _call():
    v = m.VERBS[0]
    return mr.register_engine_to_mesh(name="engine_docs_probe", verb=v["verb"],
                                      input_uri=v["input_uri"], output_uri=v["output_uri"],
                                      endpoint_url="http://x/explain", description="d", domains=[])


def test_the_gateway_path_REPORTS_a_refusal(fleet, monkeypatch):
    monkeypatch.setattr(mr, "register_with_mesh", _Registrar(ok=False))
    r = _call()
    assert isinstance(r, mr.RegistrationResult), f"the live path returned {r!r}"
    assert not r and "mint failed" in (r.reason or "")
    assert fleet, "an unregistered verb must still be handed to the background retry"


def test_the_gateway_path_REPORTS_a_success(fleet, monkeypatch):
    monkeypatch.setattr(mr, "register_with_mesh", _Registrar(ok=True))
    r = _call()
    assert isinstance(r, mr.RegistrationResult) and r, f"the live path returned {r!r}"


@pytest.mark.parametrize("gms", [None, "http://gms.test"])
def test_the_configuration_exits_report_too(fleet, monkeypatch, gms):
    """No registrar and no GMS; or GMS set and acryl-datahub absent. Either was a bare `None`."""
    monkeypatch.delenv("MESH_REGISTRAR_URL")
    if gms is None:
        monkeypatch.delenv("DATAHUB_GMS_URL", raising=False)
    else:
        monkeypatch.setenv("DATAHUB_GMS_URL", gms)
        monkeypatch.setitem(sys.modules, "datahub", None)  # import fails
    r = _call()
    assert isinstance(r, mr.RegistrationResult) and not r and r.reason, f"returned {r!r}"


# ── CONSUMER: the line engine-docs prints ──────────────────────────────────────────────────────

def test_a_REFUSED_registration_is_not_printed_as_registered(fleet, monkeypatch, capsys):
    out = _start(monkeypatch, capsys, _Registrar(ok=False))
    assert f"registered {N}/{N} verbs" not in out, out
    assert f"registered 0/{N} verbs" in out, out
    for verb in VERB_IDS:
        assert f"NOT REGISTERED {verb}: mint failed" in out, out
    assert m.health()["registration_incomplete"] == VERB_IDS
    assert m.health()["ready"] is False


def test_CONTROL_an_accepted_registration_is_counted(fleet, monkeypatch, capsys):
    """Differs in exactly one thing, the registrar's answer."""
    out = _start(monkeypatch, capsys, _Registrar(ok=True))
    assert f"registered {N}/{N} verbs" in out and "NOT REGISTERED" not in out, out
    assert m.health()["registration_incomplete"] is None


def test_a_verb_the_retry_LANDS_stops_being_incomplete(fleet, monkeypatch, capsys):
    """THE JOIN. The retry records under the key the helper chose; /health must read that key.
    Recovery is recorded exactly as `_retry_forever` records it, on the component the helper
    itself handed to the retry -- never on a URN this test spells."""
    _start(monkeypatch, capsys, _Registrar(ok=False))
    assert m.health()["registration_incomplete"] == VERB_IDS
    assert len(fleet) == N
    for component in fleet:
        mr._record(component, mr._REG_OK)
    assert m.health()["registration_incomplete"] is None


def test_a_helper_that_reports_NOTHING_is_not_counted_as_registered(fleet, monkeypatch, capsys):
    """`None` is not a success. An older helper, or a new exit that forgets to return, must read
    as not landed rather than revive the original lie."""
    monkeypatch.setattr(mr, "register_engine_to_mesh", lambda **_kw: None)
    out = _start(monkeypatch, capsys, _Registrar(ok=True))
    assert f"registered 0/{N} verbs" in out, out
    assert "the helper reported no outcome" in out, out


def test_a_call_that_RAISED_stays_incomplete(fleet, monkeypatch, capsys):
    """Nothing retries a call that raised, so no recorded status may clear it."""
    def _boom(**_kw):
        raise TypeError("unexpected keyword argument 'endpoint'")

    monkeypatch.setattr(mr, "register_engine_to_mesh", _boom)
    out = _start(monkeypatch, capsys, _Registrar(ok=True))
    assert f"registered 0/{N} verbs" in out and "REGISTRATION FAILED" in out, out
    assert m.health()["registration_incomplete"] == VERB_IDS
