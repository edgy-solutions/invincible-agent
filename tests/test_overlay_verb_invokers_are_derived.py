"""Every declared-query verb an overlay ships is granted, to exactly the users its domain admits.

An overlay verb (policy/overlays/*/verbs/*.yaml) declares a `capability` and a `domain` and no
persona, so its invokers are the members of every group granting a cell in that domain. With no
grant, `can_invoke` is not-found and every caller is denied. The grantees are derived, never
chosen: verb -> domain -> the groups granting any cell in it (groups.yaml) -> their members
(users.yaml). The verbs are globbed, so a new overlay verb reds here before it can go ungranted.

ONE ENUMERATED EXCEPTION, ruled 2026-10-11 (Chris): a step that runs on_behalf_of an OpenDDIL
event's dropped_by runs as the delegate `svc:openddil`, which holds the fault-walk grant. A service
is not a person and never gets a group or a cell, so it can never be DERIVED; it is named in
`_RULED_SERVICE_INVOKERS` instead, and the arms below seal that the name stays a service with no
cell, is actually granted, and that `svc:case-runner` holds no `mesh:` grant at all.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[1]


#: capability -> the service invokers a ruling adds beyond the derived members. Nothing else.
_RULED_SERVICE_INVOKERS: dict[str, set[str]] = {"mesh:s1000dFaultWalk": {"svc:openddil"}}


def _load(rel: str):
    return yaml.safe_load((_REPO / rel).read_text(encoding="utf-8"))


def _overlay_verbs() -> list[Path]:
    return sorted(_REPO.glob("policy/overlays/*/verbs/*.yaml"))


def _members_of_domain(domain: str) -> set[str]:
    groups = _load("policy/groups.yaml")["groups"]
    users = _load("policy/users.yaml")["users"]
    granting = {n for n, d in groups.items()
                if any(x.get("domain") == domain for x in (d or {}).get("grants", []))}
    return {u["id"] for u in users if set(u.get("groups") or []) & granting}


def test_the_glob_finds_the_overlay_verbs():
    # A glob that matches nothing would pass every arm below vacuously.
    assert any(p.name == "s1000d_fault_walk.yaml" for p in _overlay_verbs()), _overlay_verbs()


@pytest.mark.parametrize("path", _overlay_verbs(), ids=lambda p: p.stem)
def test_each_overlay_verb_is_granted_to_exactly_its_domains_members(path):
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert "persona" not in doc and "owner_persona" not in doc, (
        f"{path.name} names a persona; derive its invokers from the cell, not the domain alone")
    derived = _members_of_domain(doc["domain"])
    assert derived, f"no user holds a {doc['domain']} cell, so {doc['capability']} grants nobody"
    grant = _load("policy/capability_grants.yaml")["capabilities"].get(doc["capability"])
    assert grant is not None, f"{doc['capability']} ({path.name}) has no capability grant"
    expected = derived | _RULED_SERVICE_INVOKERS.get(doc["capability"], set())
    assert set(grant["grant_to"]) == expected, (doc["capability"], sorted(grant["grant_to"]), sorted(expected))


@pytest.mark.parametrize("capability", sorted(_RULED_SERVICE_INVOKERS))
def test_a_ruled_invoker_is_a_service_with_no_cell(capability):
    users = {u["id"]: u for u in _load("policy/users.yaml")["users"]}
    for sid in _RULED_SERVICE_INVOKERS[capability]:
        assert sid.startswith("svc:"), f"{sid} is not a service; a person's grant must be derived"
        assert sid in users, f"{sid} is not declared in users.yaml"
        assert not (users[sid].get("groups") or []), f"{sid} holds groups {users[sid]['groups']}"


@pytest.mark.parametrize("capability", sorted(_RULED_SERVICE_INVOKERS))
def test_a_ruled_invoker_is_actually_granted_on_an_overlay_verb(capability):
    # A stale allowance for a verb that no longer exists, or a grant nobody wrote, reds here.
    verbs = {yaml.safe_load(p.read_text(encoding="utf-8"))["capability"] for p in _overlay_verbs()}
    assert capability in verbs, f"{capability} is no overlay verb's capability"
    grant = _load("policy/capability_grants.yaml")["capabilities"][capability]
    assert _RULED_SERVICE_INVOKERS[capability] <= set(grant["grant_to"]), sorted(grant["grant_to"])


def test_the_case_runner_holds_no_mesh_grant():
    caps = _load("policy/capability_grants.yaml")["capabilities"]
    held = sorted(c for c, g in caps.items() if "svc:case-runner" in (g or {}).get("grant_to", []))
    assert held, "svc:case-runner holds no grant at all; the control below is vacuous"
    assert not [c for c in held if c.startswith("mesh:")], held
