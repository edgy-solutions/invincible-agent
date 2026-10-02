"""Every verb a docs page explains is granted in the capability namespace, to exactly the
users the entitlement model already lets invoke it.

engine-docs' page gate (dark until ENABLE_AGENTIC_AUTH) withholds a page unless the asker holds
`can_invoke` on every verb the page explains. With no grant, `can_invoke` is not-found, so every
asker is denied and the flip would withhold every such page from everyone.

The grantees are derived, never chosen: verb -> each provider's owner cell -> the groups that
grant that cell (groups.yaml) -> their members (users.yaml). The population of verbs is read
from the corpus, and each verb's providers are re-read from the registering source, so a new
page, a new verb or a new provider reds here before it can go ungranted.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[2]
_MESH = "http://invincible-agent/mesh#"

# verb -> {provider source: [(owner_persona, domain), ...]}. The cells are cited from each
# provider's registration; the provider SET is re-derived from source by the arm below, so this
# table cannot silently lose or gain a provider. A provider whose persona is not in
# personas.yaml is listed with its cells anyway: it contributes nobody, and that is asserted.
_PROVIDERS = {
    "seedCanvas": {"src/iagent/gateway.py": [("PORTFOLIO_LEAD", "PORTFOLIO_PLANNING")]},
    "seedPortfolioCanvas": {"src/iagent/gateway.py": [("PORTFOLIO_LEAD", "PORTFOLIO_PLANNING")]},
    "finProgramBrief": {"policy/graphs/fin_program_brief.yaml": None},
    "costLotCostingReview": {"policy/graphs/cost_lot_costing_review.yaml": None},
    "resolveInstance": {
        "agent_fleet/planning_agent/main.py": [("PORTFOLIO_LEAD", "PORTFOLIO_PLANNING")],
        "agent_fleet/finance_agent/main.py": [("PROGRAM_FINANCE_ANALYST", "PROGRAM_FINANCE")],
        "agent_fleet/cost_agent/main.py": [("COST_ANALYST", "PRODUCTION_COST")],
        "agent_fleet/datahub_wrapper/main.py": [("DATA_STEWARD", "DATA_ENGINEERING")],
        "agent_fleet/ontology_service/main.py": [("OPS_OPERATOR", "SUSTAINMENT")],
        "agent_fleet/neo4j_expert/main.py": [("AUDITOR", "MAINTENANCE"), ("AUDITOR", "MANUFACTURING"),
                                             ("TECH_WRITER", "MAINTENANCE")],
        "agent_fleet/safety_agent/main.py": [("SAFETY_ENGINEER", "SUSTAINMENT")],
    },
    "enumerateInstances": {
        "agent_fleet/planning_agent/main.py": [("PORTFOLIO_LEAD", "PORTFOLIO_PLANNING")],
        "agent_fleet/finance_agent/main.py": [("PROGRAM_FINANCE_ANALYST", "PROGRAM_FINANCE")],
        "agent_fleet/cost_agent/main.py": [("COST_ANALYST", "PRODUCTION_COST")],
        "agent_fleet/safety_agent/main.py": [("SAFETY_ENGINEER", "SUSTAINMENT")],
    },
}


def _explained_verbs() -> set[str]:
    import rdflib

    g = rdflib.Graph().parse(_REPO / "setup" / "ontologies" / "docs_corpus.ttl", format="turtle")
    out = set()
    for o in g.objects(None, rdflib.URIRef(_MESH + "explains")):
        local = str(o).rsplit("#", 1)[-1]
        if local[:1].islower():  # verbs are properties (lowerCamel); classes are not gated
            out.add(local)
    return out


def _cells(verb: str) -> set[tuple[str, str]]:
    cells = set()
    for src, cs in _PROVIDERS[verb].items():
        if cs is None:  # a graph verb: its owner cell is in its own policy file
            doc = yaml.safe_load((_REPO / src).read_text(encoding="utf-8"))
            cs = [(doc["owner_persona"], d) for d in doc["domains"]]
        cells |= set(cs)
    return cells


def _members_of(cells: set[tuple[str, str]]) -> set[str]:
    groups = yaml.safe_load((_REPO / "policy" / "groups.yaml").read_text(encoding="utf-8"))["groups"]
    users = yaml.safe_load((_REPO / "policy" / "users.yaml").read_text(encoding="utf-8"))["users"]
    granting = {n for n, d in groups.items()
                if any((x.get("persona"), x.get("domain")) in cells for x in (d or {}).get("grants", []))}
    return {u["id"] for u in users if set(u.get("groups") or []) & granting}


def _grants() -> dict:
    return yaml.safe_load((_REPO / "policy" / "capability_grants.yaml").read_text(encoding="utf-8"))["capabilities"]


def test_the_table_covers_every_verb_the_corpus_explains():
    explained = _explained_verbs()
    assert explained, "no verb found in mesh:explains: the corpus parse matched nothing"
    assert explained == set(_PROVIDERS), (
        f"explained but not tabulated: {sorted(explained - set(_PROVIDERS))}; "
        f"tabulated but no longer explained: {sorted(set(_PROVIDERS) - explained)}"
    )


@pytest.mark.parametrize("verb", sorted(v for v in _PROVIDERS
                                        if not any(s.startswith("policy/graphs/") for s in _PROVIDERS[v])))
def test_the_provider_set_is_what_the_source_registers(verb):
    pat = re.compile(r'(?:verb\s*=\s*|"verb":\s*)"mesh:' + verb + r'"')
    found = {str(p.relative_to(_REPO)).replace("\\", "/")
             for p in [*(_REPO / "agent_fleet").glob("*/main.py"), _REPO / "src" / "iagent" / "gateway.py"]
             if pat.search(p.read_text(encoding="utf-8"))}
    assert found == set(_PROVIDERS[verb]), (
        f"mesh:{verb} is registered by {sorted(found)}, tabulated as {sorted(_PROVIDERS[verb])}"
    )


@pytest.mark.parametrize("verb", sorted(_PROVIDERS))
def test_each_explained_verb_is_granted_to_exactly_its_derived_invokers(verb):
    derived = _members_of(_cells(verb))
    granted = set((_grants().get(f"mesh:{verb}") or {}).get("grant_to") or [])
    assert derived, f"mesh:{verb} has no derivable invoker; its page would be withheld from everyone"
    assert granted == derived, (
        f"mesh:{verb}: granted {sorted(granted)}, the entitlement model derives {sorted(derived)}"
    )


def test_a_provider_outside_the_persona_vocabulary_grants_nobody():
    """The control on the derivation: the personas cited without a cell really are absent, so
    their providers contribute nobody. When one is added, this reds and the grant is rewritten."""
    vocab = set(yaml.safe_load((_REPO / "policy" / "personas.yaml").read_text(encoding="utf-8"))["personas"])
    absent = {"OPS_OPERATOR", "AUDITOR", "TECH_WRITER"}
    assert not (absent & vocab), f"now in personas.yaml: {sorted(absent & vocab)}; re-derive the grants"
    assert _members_of({("OPS_OPERATOR", "SUSTAINMENT"), ("AUDITOR", "MAINTENANCE"),
                        ("TECH_WRITER", "MAINTENANCE")}) == set()
