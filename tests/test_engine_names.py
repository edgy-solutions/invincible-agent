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
