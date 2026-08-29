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
