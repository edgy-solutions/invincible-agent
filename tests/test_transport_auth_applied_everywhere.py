"""THE EXPAND PHASE'S SEAL — every engine observes, mints through one function, and SAYS SO.

Three obligations, asserted over the COMPLETE set of engines, because each is only meaningful
universally:

  1. INBOUND  — the app carries the transport-auth dependency, so every request's caller
     posture is validated and recorded. One engine missing it is a hole the gauge cannot see:
     its endpoints report nothing, which is indistinguishable from "no callers yet".
  2. OUTBOUND — nothing re-implements the mint. A stray inline `httpx.post` to a token
     endpoint is a second implementation, and the two mints that existed before this arc had
     ALREADY diverged on env contracts while everyone believed they were transcriptions.
  3. ANNOUNCED — each engine emits its posture at startup. An engine that took the dependency
     but lost the announcement (import-order accident, log config swallowing it) has a REAL
     posture that is ILLEGIBLE, and the contract flip's readiness is read from these lines.
     `transport auth: OBSERVE (default)` is also the pre-positioned string the fresh-deploy
     test will one day assert ABSENT — which only works if it is emitted now.

WHY A SUITE PROPERTY AND NOT A REVIEW HABIT: this is exactly the edit that lands on nine
engines and misses the tenth. The earlier fleet enumeration missed an inline presence-check
because it grepped for framework vocabulary; this asserts the wiring itself, over a set
derived from "has a FastAPI app", not from memory.

Run:  uv run --frozen python -m pytest tests/test_transport_auth_applied_everywhere.py -q
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_FLEET = _ROOT / "agent_fleet"

# Derived, never hand-listed: any module constructing a FastAPI app is in scope. A hand-list
# is how the tenth engine goes missing.
_APPS = sorted(
    p for p in _FLEET.glob("*/main.py")
    if re.search(r"^app = FastAPI\(", p.read_text(encoding="utf-8"), re.M)
)


def test_the_fleet_is_not_empty():
    """Positive control: a glob that matches nothing would make every assertion below
    vacuously true — the shape in which a cross-cutting seal silently stops sealing."""
    assert len(_APPS) >= 10, f"only {len(_APPS)} engine apps discovered — glob broken?"


@pytest.mark.parametrize("app", _APPS, ids=lambda p: p.parent.name)
def test_inbound_every_engine_carries_the_transport_auth_dependency(app: Path):
    s = app.read_text(encoding="utf-8")
    assert "make_transport_auth_dependency" in s, f"{app.parent.name}: no transport auth import"
    assert re.search(r"dependencies=\[Depends\(_transport_auth\(", s), (
        f"{app.parent.name}: app does not APPLY the dependency — importable is not applied"
    )


@pytest.mark.parametrize("app", _APPS, ids=lambda p: p.parent.name)
def test_announced_every_engine_emits_its_posture(app: Path):
    s = app.read_text(encoding="utf-8")
    assert "_announce_transport_auth(component=" in s, (
        f"{app.parent.name}: posture not announced — a real posture the gauge cannot read"
    )


@pytest.mark.parametrize("app", _APPS, ids=lambda p: p.parent.name)
def test_outbound_no_engine_reimplements_the_mint(app: Path):
    """One implementation, proven by absence at every consumer."""
    s = app.read_text(encoding="utf-8")
    assert "openid-connect/token" not in s, (
        f"{app.parent.name}: mints its own token — use iagent_mesh.service_identity.mint_token"
    )


@pytest.mark.parametrize("app", _APPS, ids=lambda p: p.parent.name)
def test_every_consuming_package_pins_the_sdk_to_a_tag(app: Path):
    """Pin follows consumption. An engine that took the dependency without pinning it is one
    SDK commit away from a security-behaviour change nobody reviewed."""
    pp = app.parent / "pyproject.toml"
    if not pp.exists():
        pytest.skip(f"{app.parent.name} has no pyproject")
    m = re.search(r'"iagent-mesh @ git\+[^"@]+\.git@(?P<ref>[^"]+)"', pp.read_text(encoding="utf-8"))
    assert m, f"{app.parent.name}: consumes the SDK but does not pin it"
    assert re.fullmatch(r"v\d+\.\d+\.\d+", m.group("ref")), (
        f"{app.parent.name}: pins {m.group('ref')!r} — a ref, not a version"
    )
