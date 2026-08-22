"""Structural guard for the endpoint-gating audit (the "exceptions are DECLARED, not
accidental" property).

Every agent-reachable HTTP route across the fleet must appear in
``docs/architecture/endpoint_gating_manifest.yaml`` with a gating classification. A
route present in source but ABSENT from the manifest FAILS CI — so a new endpoint
cannot ship without answering "what row does this add?" (the same posture as the
phantom-subject validator: the invalid state — an undeclared surface — refuses loudly).

Extraction is STATIC (regex over source), not by importing the FastAPI apps — importing
them would drag BAML/engine deps and env, and a security guard must not depend on the
thing it audits being importable.

Run:  pytest tests/test_endpoint_gating_manifest.py -v
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parent.parent
_MANIFEST = _REPO / "docs" / "architecture" / "endpoint_gating_manifest.yaml"

# The FastAPI services whose HTTP routes are agent-reachable. Restate VirtualObject /
# Workflow handlers are documented in the manifest narrative but are not @app-decorated,
# so the static HTTP-route check below does not cover them (they have no browser surface).
SERVICE_FILES: dict[str, str] = {
    "ontology_service": "agent_fleet/ontology_service/main.py",
    "datahub_wrapper": "agent_fleet/datahub_wrapper/main.py",
    "neo4j_expert": "agent_fleet/neo4j_expert/main.py",
    "weaviate_expert": "agent_fleet/weaviate_expert/main.py",
    "restate_analyst": "agent_fleet/restate_analyst/main.py",
    "data_analyst": "agent_fleet/data_analyst/main.py",
    "planning_agent": "agent_fleet/planning_agent/main.py",
    "presentation_agent": "agent_fleet/presentation_agent/main.py",
    "mesh_registrar": "agent_fleet/mesh_registrar/main.py",
    "projector": "src/iagent/projector/app.py",
    "gateway": "src/iagent/gateway.py",
    "domain_broker": "helm/invincible-agent/files/domain-broker.py",
    "swarms_scraper": "agent_fleet/swarms_scraper/main.py",
    "langgraph_support": "agent_fleet/langgraph_support/main.py",
    # `core_authz` removed 2026-08-07: agent_fleet/core/authz.py is DELETED. It defined no
    # routes; it was carried here only so the manifest could describe the gate helper the
    # ungated rows were told to adopt. That recommendation was the false row — the helper
    # decoded bearers with verify_signature=False. Inbound verification is now the SDK's
    # `iagent_mesh.transport_auth`, declared per-service in the manifest as
    # `inbound_transport_auth` and asserted by tests/test_transport_auth_applied_everywhere.py.
}

_HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head", "options"}
# `retired` = a route kept PRESENT (returns 410) but slated for deletion once its
# replacement lands — the manifest tracks it live -> retired -> deleted, so the guard
# keeps seeing it and it never falls into the undeclared-route failure.
_VALID_CLASSES = {
    "gated", "releasable_by_design", "ungated_by_accident", "delegates", "internal",
    "retired",
}
_NEEDS_JUSTIFICATION = {"releasable_by_design", "ungated_by_accident", "retired"}


def _extract_routes(source_path: Path) -> set[tuple[str, str]]:
    """Find REAL route decorators via AST (`@app.post("/x")` / `@router.get("/y")`) on
    actual function defs — NOT via regex, so decorators inside docstrings/comments (e.g.
    a usage example in a helper's docstring) are never mistaken for routes. Literal path
    only; a non-literal (f-string) path is surfaced by the audit, not silently missed."""
    if not source_path.is_file():
        return set()
    try:
        tree = ast.parse(source_path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return set()
    out: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)):
                continue
            method = dec.func.attr.lower()
            base = getattr(dec.func.value, "id", None) or getattr(dec.func.value, "attr", None)
            if method in _HTTP_METHODS and base in {"app", "router"} and dec.args:
                first = dec.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    out.add((method.upper(), first.value))
    return out


def _load_manifest() -> dict:
    assert _MANIFEST.is_file(), f"endpoint gating manifest missing: {_MANIFEST}"
    return yaml.safe_load(_MANIFEST.read_text(encoding="utf-8")) or {}


def _declared_routes(manifest: dict, service: str) -> set[tuple[str, str]]:
    svc = (manifest.get("services") or {}).get(service) or {}
    out: set[tuple[str, str]] = set()
    for r in svc.get("routes") or []:
        out.add((str(r.get("method", "")).upper(), str(r.get("path", ""))))
    return out


@pytest.mark.parametrize("service,rel", sorted(SERVICE_FILES.items()))
def test_every_source_route_is_declared(service, rel):
    """A route in source but ABSENT from the manifest fails CI — new surfaces must
    declare their gating posture, so an ungated endpoint can never ship unnoticed."""
    manifest = _load_manifest()
    source = _extract_routes(_REPO / rel)
    declared = _declared_routes(manifest, service)
    undeclared = source - declared
    assert not undeclared, (
        f"{service}: {len(undeclared)} route(s) in {rel} are NOT declared in the "
        f"endpoint-gating manifest: {sorted(undeclared)}. Add each with an identity/gate/"
        f"class row (gated | releasable_by_design | ungated_by_accident | delegates | internal)."
    )


def test_manifest_entries_are_well_formed():
    """Every declared route carries a valid classification; an UNGATED route (gate: none)
    must be justified as releasable_by_design or flagged ungated_by_accident — never a
    silent 'none' with no class."""
    manifest = _load_manifest()
    problems: list[str] = []
    for service, svc in (manifest.get("services") or {}).items():
        for r in svc.get("routes") or []:
            path = f"{service} {r.get('method')} {r.get('path')}"
            cls = r.get("class")
            if cls not in _VALID_CLASSES:
                problems.append(f"{path}: class {cls!r} not in {sorted(_VALID_CLASSES)}")
            if str(r.get("gate", "none")).lower() == "none" and cls == "gated":
                problems.append(f"{path}: class 'gated' but gate is 'none' (contradiction)")
            if cls in _NEEDS_JUSTIFICATION and not r.get("justification"):
                problems.append(f"{path}: {cls} requires a justification")
    assert not problems, "manifest well-formedness:\n  " + "\n  ".join(problems)


def test_no_stale_manifest_routes():
    """A manifest route that no longer exists in source is stale — keeps the manifest
    honest (the reverse direction of the undeclared check)."""
    manifest = _load_manifest()
    stale: list[str] = []
    for service, rel in SERVICE_FILES.items():
        source = _extract_routes(_REPO / rel)
        for m, p in _declared_routes(manifest, service):
            # Only flag literal paths (routes with {vars} still match literally here).
            if (m, p) not in source:
                stale.append(f"{service} {m} {p}")
    assert not stale, f"stale manifest routes (not found in source): {stale}"
