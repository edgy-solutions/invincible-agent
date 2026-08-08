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

# WHAT "FLEET-WIDE" ENUMERATES — stated, because a coverage claim must name its population.
#
# Until 2026-08-07 this derived from `agent_fleet/*/main.py` alone, so "fleet-wide" silently
# meant TEN ENGINES: the projector and the sandbox domain broker are mesh services that were
# outside the claim purely because the GLOB was the boundary, not a decision. Widened to the
# three trees that actually hold mesh HTTP services. Complete must never be readable into a
# glob — so the population is broad, and the single exclusion below is NAMED.
_APP_GLOBS = (
    "agent_fleet/*/main.py",
    "src/iagent/**/app.py",
    "helm/invincible-agent/files/*.py",
)

# DELIBERATELY EXCLUDED, with its reason — not an oversight, and not permission to add more.
#
# `src/iagent/gateway.py` (cortex-bff) is the USER plane, not the service-transport plane. Its
# inbound auth is Keycloak JWT verification at `get_current_user` — signature verified against
# live JWKS with `algorithms=["RS256"]` pinned, all failure paths 401 — which is a STRONGER and
# semantically different contract than OBSERVE-mode service-transport auth. Layering the fleet
# module there would conflate two auth planes and let an OBSERVE posture be read as covering
# the front door.
#
# That claim is not taken on faith: `core/authz.py` deferred its own signature verification TO
# this gateway, so "the gateway verifies" became load-bearing for the deleted module, the DA
# seam and the whole on_behalf_of design. It is read-confirmed and probed by
# tests/security/test_gateway_jwt_verification.py (forged-vs-legitimate discriminating pair,
# proven by regression). Three separate designs this month rested on
# security-assumed-at-a-boundary-the-component-does-not-control; two were wrong. This one holds.
_EXCLUDED = {
    "src/iagent/gateway.py": "user-plane Keycloak JWT verification; see "
                             "tests/security/test_gateway_jwt_verification.py",
}

_APPS = sorted(
    {p for g in _APP_GLOBS for p in _ROOT.glob(g)
     if re.search(r"^\s*app = FastAPI\(", p.read_text(encoding="utf-8"), re.M)
     and str(p.relative_to(_ROOT)).replace("\\", "/") not in _EXCLUDED}
)

# The count "fleet-wide" currently means. Asserted so that a service silently dropping out of
# the population fails LOUDLY, rather than shrinking a coverage claim without anyone noticing —
# the census rule: cardinality is not a census, so this is checked alongside membership below.
_EXPECTED_FLEET = 12


def test_the_fleet_is_not_empty():
    """Positive control: a glob that matches nothing would make every assertion below
    vacuously true — the shape in which a cross-cutting seal silently stops sealing."""
    assert len(_APPS) >= _EXPECTED_FLEET, (
        f"only {len(_APPS)} mesh apps discovered, expected >= {_EXPECTED_FLEET} — glob broken, "
        f"or a service left the population. Found: "
        f"{sorted(str(p.relative_to(_ROOT)) for p in _APPS)}"
    )


def test_the_excluded_set_is_exactly_what_was_ruled():
    """An exclusion list is a ledger of NAMED decisions, not a place to quiet a failure.

    Every excluded path must still exist (a stale exemption silently widens nothing but lies
    about what was considered) and must still construct an app — otherwise the exemption is
    describing a service that no longer works the way the ruling assumed.
    """
    for rel, reason in _EXCLUDED.items():
        p = _ROOT / rel
        assert p.exists(), f"excluded path {rel} no longer exists — remove the exemption"
        assert reason, f"exclusion of {rel} carries no reason"
        assert re.search(r"FastAPI\(", p.read_text(encoding="utf-8")), (
            f"{rel} is exempted as a FastAPI service but no longer constructs one"
        )


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
        # NOT unchecked — the obligation moves, it does not vanish. The projector and the
        # domain broker have no pyproject of their own: they ship in the IAGENT IMAGE, so their
        # pin is the ROOT pyproject's. A bare `skip("no pyproject")` would read as "this
        # service's pin was not verified", which is the same soft-nothing this suite exists to
        # refuse — so the assertion is REDIRECTED to root rather than dropped.
        pp = _ROOT / "pyproject.toml"
        assert pp.exists(), "root pyproject missing — cannot discharge the pin obligation"
        # PARSED, not grepped: a regex over the whole file matches the dev group too, so it
        # would pass in precisely the case this guards against. `project.dependencies` is the
        # only list that reaches the runtime image.
        import tomllib
        main_deps = tomllib.loads(pp.read_text(encoding="utf-8")).get("project", {}).get(
            "dependencies", [])
        assert any(d.strip().startswith("iagent-mesh") for d in main_deps), (
            f"{app.parent.name} ships in the iagent image and takes the SDK dependency, but "
            f"root does not declare `iagent-mesh` in its MAIN dependencies. Declared only in "
            f"the dev group, it resolves in the dev venv and in this suite and then "
            f"ImportErrors at container start — a passing suite over a broken image."
        )
    m = re.search(r'"iagent-mesh @ git\+[^"@]+\.git@(?P<ref>[^"]+)"', pp.read_text(encoding="utf-8"))
    assert m, f"{app.parent.name}: consumes the SDK but does not pin it"
    assert re.fullmatch(r"v\d+\.\d+\.\d+", m.group("ref")), (
        f"{app.parent.name}: pins {m.group('ref')!r} — a ref, not a version"
    )
