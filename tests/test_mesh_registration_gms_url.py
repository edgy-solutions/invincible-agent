"""DATAHUB_GMS_URL shape collision — the direct-emit fallback's 404.

THE BUG THIS PINS (work cluster, 2026-07-17): DATAHUB_GMS_URL serves two
consumers with incompatible shapes — GraphQL readers use it verbatim
(``…/api/graphql``) while DatahubRestEmitter wants the bare GMS base and
appends ``/aspects``. With the (reader-correct) graphql form in the
shared agentFleet.env and no MESH_REGISTRAR_URL, every engine's
registration fallback 404'd at ``/api/graphql/aspects``. Sandbox never
saw it: engines there register via the mesh-registrar path, so the
fallback never ran. _gms_server_base normalizes at the emitter boundary
so ONE env value serves both consumers.

Run:  pytest tests/test_mesh_registration_gms_url.py -v
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_MOD = Path(__file__).resolve().parent.parent / "agent_fleet" / "utils" / "mesh_registration.py"
_spec = importlib.util.spec_from_file_location("mesh_registration_under_test", _MOD)
mesh_registration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mesh_registration)

_gms_server_base = mesh_registration._gms_server_base


def test_graphql_shaped_url_is_normalized_to_server_base():
    assert (
        _gms_server_base("http://datahub-datahub-gms:8080/api/graphql")
        == "http://datahub-datahub-gms:8080"
    )


def test_trailing_slash_variants_normalize_identically():
    assert _gms_server_base("http://gms:8080/api/graphql/") == "http://gms:8080"
    assert _gms_server_base("http://gms:8080/") == "http://gms:8080"


def test_bare_server_base_passes_through():
    assert _gms_server_base("http://datahub-datahub-gms:8080") == "http://datahub-datahub-gms:8080"


def test_non_graphql_paths_are_preserved():
    """Only the known graphql suffix is stripped — a deployment fronting
    GMS under a path prefix must not lose it."""
    assert _gms_server_base("https://corp.example/datahub") == "https://corp.example/datahub"
