"""Every declared-query verb an overlay ships is granted, to exactly the users its domain admits.

An overlay verb (policy/overlays/*/verbs/*.yaml) declares a `capability` and a `domain` and no
persona, so its invokers are the members of every group granting a cell in that domain. With no
grant, `can_invoke` is not-found and every caller is denied. The grantees are derived, never
chosen: verb -> domain -> the groups granting any cell in it (groups.yaml) -> their members
(users.yaml). The verbs are globbed, so a new overlay verb reds here before it can go ungranted.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[1]


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
    assert set(grant["grant_to"]) == derived, (doc["capability"], sorted(grant["grant_to"]), sorted(derived))
