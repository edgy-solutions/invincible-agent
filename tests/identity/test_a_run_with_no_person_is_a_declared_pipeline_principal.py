"""SEAL 3 -- a run with no person is a declared `pipeline:<name>` principal.

Architect, overnight: "a run with no person is a declared pipeline principal".

RULED, NOT BUILT. Today a run with no person (a scheduled or ingest-triggered run whose `user_email`
is blank, or a service identity `svc:...`) dispatches as the bare service `svc:supervisor`: lane 01's
#213 states it as INTERIM until the ruled `pipeline:<name>` principal replaces it. This file is the
seal the replacement must satisfy, written before it lands:

  * the identity a no-person run dispatches as is a `pipeline:<name>` principal,
  * that principal is DECLARED in config -- never a bare service identity, never an undeclared name.

WHERE "declared" is read from: the deploy's service-client declarations (`keycloak.serviceClients` in
values.yaml plus `extraServiceClients` in the environment's values), the same place `svc:supervisor`
and the delegates are declared. A declared pipeline principal is one of them whose `authzId` starts
`pipeline:`. If the ruling puts the declaration elsewhere, change `declared_pipelines()` -- the one
function that names the source -- and nothing else.

BEHAVIOUR: the supervisor's outbound credential is what a run dispatches as, so the test drives
`dynamic_supervisor._telemetry_headers(config)` (the single home of outbound auth, per its own
docstring) with the mint stubbed to record WHICH CLIENT it minted for, and asserts that client is a
declared pipeline principal's. It runs against master and against #213 unchanged: it names no symbol
that exists only on one of them.

THE XFAIL IS STRICT: the day the pipeline principal is built it XPASSes, the strict flag turns that
into a failure, and whoever built it deletes the marker and keeps the seal.

Run: uv run pytest tests/identity/test_a_run_with_no_person_is_a_declared_pipeline_principal.py -q
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.iagent.defs import dynamic_supervisor as ds

ROOT = Path(__file__).resolve().parents[2]
CHART = ROOT / "helm" / "invincible-agent"


def _clients():
    out = []
    for name in ("values.yaml", "values-sandbox.yaml"):
        kc = (yaml.safe_load((CHART / name).read_text(encoding="utf-8")) or {}).get("keycloak") or {}
        out += list(kc.get("serviceClients") or []) + list(kc.get("extraServiceClients") or [])
    return out


def declared_pipelines() -> dict[str, str]:
    """{clientId: authzId} of every declared `pipeline:<name>` principal. THE source of the seal."""
    return {c["clientId"]: c["authzId"] for c in _clients()
            if str(c.get("authzId", "")).startswith("pipeline:") and c.get("clientId")}


def _supervisor_client() -> dict:
    (c,) = [c for c in _clients() if c.get("authzId") == "svc:supervisor"]
    return c


class _NoPerson:
    user_persona = None
    trace_id = "t-1"
    session_id = "s-1"

    def __init__(self, user_email):
        self.user_email = user_email


def _minted_for(monkeypatch, user_email):
    from agent_fleet.utils import service_identity as si

    seen: list[str] = []

    def mint(*, client_id, client_secret, timeout=15.0):
        seen.append(client_id)
        return f"token-for-{client_id}"

    sup = _supervisor_client()
    monkeypatch.setenv("SUPERVISOR_CLIENT_ID", sup["clientId"])
    monkeypatch.setenv("SUPERVISOR_CLIENT_SECRET", "x")
    monkeypatch.setattr(si, "mint_token", mint)
    headers = ds._telemetry_headers(_NoPerson(user_email))
    return seen, headers


def test_control_the_source_reads_and_the_supervisor_is_a_declared_service():
    """The declaration source parses, and the bare service identity the interim uses is the one the
    seal says a no-person run must NOT be."""
    assert _supervisor_client()["authzId"] == "svc:supervisor"
    assert all(v.startswith("pipeline:") and len(v) > len("pipeline:") for v in declared_pipelines().values())


@pytest.mark.parametrize("user_email", ["", "   ", "svc:supervisor", "svc:case-runner"])
def test_a_no_person_run_never_dispatches_as_a_person(monkeypatch, user_email):
    """True today and after: no person means no person's token (nothing redeemed, nothing forged)."""
    seen, headers = _minted_for(monkeypatch, user_email)
    assert seen, "a no-person run must dispatch under SOME minted principal"
    assert headers["Authorization"].startswith("Bearer token-for-"), headers


@pytest.mark.xfail(strict=True, reason=(
    "RULED, NOT BUILT: lane 01's #213 keeps a run with no person as `svc:supervisor`, marked INTERIM "
    "(its test_INTERIM_a_run_with_no_person_still_dispatches_as_the_service). No `pipeline:<name>` "
    "principal is declared in the chart (keycloak.serviceClients / extraServiceClients) and the "
    "supervisor mints only for SUPERVISOR_CLIENT_ID. When it is built this XPASSes: delete the marker."))
@pytest.mark.parametrize("user_email", ["", "   ", "svc:supervisor", "svc:case-runner"])
def test_a_no_person_run_dispatches_as_a_declared_pipeline_principal(monkeypatch, user_email):
    declared = declared_pipelines()
    seen, _ = _minted_for(monkeypatch, user_email)
    assert declared, "no pipeline:<name> principal is declared in the deploy's service clients"
    assert seen and all(c in declared for c in seen), (
        f"minted for {seen}, declared pipeline principals {sorted(declared)}")
    assert _supervisor_client()["clientId"] not in seen, "a bare service identity is not a pipeline"
