"""Tests for the routing-HUD "Handled by" engine-name resolution.

The load-bearing property: engine-name derivation is RELEASE-AGNOSTIC. The
service prefix is `iagent-` in the sandbox release but `invincible-agent-` at
work, and endpoints are now the full FQDN form
(`…-engine-a.<ns>.svc.cluster.local:8081`, the svcDomain/NO_PROXY fix). A prior
regex anchored on `iagent-engine-` showed "Unknown engine" at work on an
otherwise-correct route (2026-07-21). These pin that it resolves regardless of
release prefix and bare-vs-FQDN host.
"""
from __future__ import annotations

import pytest

from iagent.engine_names import engine_name_from_endpoint, engine_name_from_provider
from iagent.engine_names import handler_name_from_endpoint


@pytest.mark.parametrize("endpoint,expected", [
    # WORK: release invincible-agent, FQDN host — the case that showed Unknown.
    ("http://invincible-agent-engine-a.prod-ns.svc.cluster.local:8081/analyze", "Engine A"),
    ("http://invincible-agent-engine-d.prod-ns.svc.cluster.local:8085/query_metadata", "Engine D"),
    ("http://invincible-agent-engine-o.prod-ns.svc.cluster.local:8084/resolve", "Engine O"),
    # SANDBOX: release iagent, bare host.
    ("http://iagent-engine-a:8081/analyze", "Engine A"),
    ("http://iagent-engine-f:8087/render_ui", "Engine F"),
    ("http://iagent-engine-w:8086/x", "Engine W"),
    # engine-fin: THREE letters, so `engine-([a-z]{1,2})\b` misses it — the HUD read
    # "Handled by: Unknown engine" on a finance answer that had routed perfectly
    # (Program 0.97 -> finVarianceAnalysis 0.95). Both releases, FQDN and bare.
    ("http://invincible-agent-engine-fin.prod-ns.svc.cluster.local:8096/measure/fin_burn_rate",
     "Engine F (Finance)"),
    ("http://iagent-engine-fin.sandbox.svc.cluster.local:8096/measure/fin_variance_analysis",
     "Engine F (Finance)"),
    ("http://iagent-engine-fin:8096/measure/fin_funding_status", "Engine F (Finance)"),
    # AND THE COLLISION STAYS DISAMBIGUATED: engine-f is the PRESENTATION agent and
    # keeps "Engine F" (asserted above). Two engines rendering as one name in the HUD
    # would be worse than "Unknown" — it would be wrong and confident.
    # engine-docs / engine-cost / engine-safety: the same miss as engine-fin, found on the
    # docs walk 2026-10-23 (the explain card's HUD read "Unknown engine"). A WORD component
    # is named by its word, so the next engine-<word> is not a fourth instance.
    ("http://invincible-agent-engine-docs.prod-ns.svc.cluster.local:8100/explain", "Engine Docs"),
    ("http://iagent-engine-docs:8100/explain", "Engine Docs"),
    ("http://invincible-agent-engine-cost.prod-ns.svc.cluster.local:8097/x", "Engine Cost"),
    ("http://iagent-engine-safety:8099/x", "Engine Safety"),
    ("http://iagent-engine-lg:8098/graphs/fin_program_brief", "Engine LG"),
    # data-analyst: component name, not engine-<letter> — both releases.
    ("http://invincible-agent-data-analyst.prod-ns.svc.cluster.local:8083/x", "Engine DA"),
    ("http://iagent-data-analyst:8083/x", "Engine DA"),
    # nothing resolvable.
    ("http://some-other-service:9000/x", ""),
    ("", ""),
    (None, ""),
])
def test_engine_name_from_endpoint_is_release_agnostic(endpoint, expected):
    assert engine_name_from_endpoint(endpoint) == expected


@pytest.mark.parametrize("provider,expected", [
    ("engine_a_restate_analyst", "Engine A"),
    ("engine_w_weaviate_expert_work_instruction", "Engine W"),
    ("engine_d", "Engine D"),
    ("engine_da_data_analyst", "Engine DA"),
    ("engine_o_ontology", "Engine O"),
    (None, "Unknown engine"),
    ("", "Unknown engine"),
    ("some_future_engine", "some_future_engine"),  # honest passthrough
])
def test_engine_name_from_provider(provider, expected):
    assert engine_name_from_provider(provider) == expected


# ── THE HANDLER CATEGORY — an orchestration is not an unknown engine ───────────────
#
# The seeding answer is produced by a BFF ORCHESTRATION. Asked for its handler, the HUD
# rendered "Unknown engine" — a captured fact that was not a true one. The handler was
# known; it was not the KIND of thing this module could name.

@pytest.mark.parametrize("endpoint,expected", [
    ("http://iagent-cortex-bff:8090/canvas/seed", "BFF orchestration"),
    # RELEASE-AGNOSTIC, the standing rule of this module and the one it has already been
    # bitten by: `iagent-` in sandbox, `invincible-agent-` at work, bare host or FQDN.
    ("http://invincible-agent-cortex-bff.sandbox.svc.cluster.local:8090/canvas/seed",
     "BFF orchestration"),
    # engines still resolve through the same door
    ("http://iagent-engine-w:8088/query_knowledge", "Engine W"),
    ("http://iagent-data-analyst:8086/analyze", "Engine DA"),
    ("http://some-other-service:9000/x", ""),
    ("", ""),
    (None, ""),
])
def test_handler_name_names_orchestrations_AND_engines(endpoint, expected):
    assert handler_name_from_endpoint(endpoint) == expected


def test_engine_name_from_endpoint_does_NOT_claim_the_orchestration():
    """ONE FUNCTION PER CLAIM, and this is the assertion that keeps them apart.

    Teaching `engine_name_from_endpoint` to answer "BFF orchestration" would have been one
    line fewer. It would also mean a caller reading that function's NAME and receiving that
    value could only conclude the mesh had grown an engine called "BFF orchestration" — the
    same impersonation cortex refused when it declined to invent a placeholder component for
    an archetype that is acted on rather than drawn.
    """
    assert engine_name_from_endpoint("http://iagent-cortex-bff:8090/canvas/seed") == ""


# ── THE CENSUS — every engine a default endpoint names, not the ones somebody listed ───────
#
# engine-fin (09-01) and engine-docs/-cost/-safety (10-23) were each found one at a time, on a
# walk, after the engine shipped. The population is every chart component the fleet's own code
# names as a default endpoint, so a new engine reds here the day its URL is written.

import re
from pathlib import Path

_FLEET = Path(__file__).resolve().parents[1] / "agent_fleet"
_DEFAULT_ENDPOINT = re.compile(r'"http://iagent-((?:engine-[a-z0-9]+)|data-analyst):[0-9]+')


def _engine_components() -> list[str]:
    found = set()
    for path in _FLEET.rglob("*.py"):
        if "__pycache__" in path.parts or any(p.startswith(".venv") for p in path.parts):
            continue
        found.update(_DEFAULT_ENDPOINT.findall(path.read_text(encoding="utf-8", errors="replace")))
    return sorted(found)


def test_the_census_reads_the_engines_it_must():
    # Control: a letter, a word and the named exception are all in the population.
    assert {"engine-a", "engine-docs", "engine-fin", "data-analyst"} <= set(_engine_components())


@pytest.mark.parametrize("component", _engine_components())
def test_every_engine_the_fleet_names_has_a_HUD_name(component):
    for host in (f"http://iagent-{component}:8000/x",
                 f"http://invincible-agent-{component}.prod-ns.svc.cluster.local:8000/x"):
        assert engine_name_from_endpoint(host), (
            f"{component} renders as 'Unknown engine' in the HUD's Handled-by label")
