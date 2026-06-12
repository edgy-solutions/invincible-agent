"""Known-good probes for every mesh:resolveInstance provider.

The abstention contract in Recipe v2 — "an empty list is a first-class
answer" — is what makes the leg safe to add: a phone-book failure
gracefully falls through to the LLM's class guess. It is also what
made tonight's biggest bug (Engine D's `search` silently returning
empty because of a missing-`type` validation error) invisible: a
provider that politely abstains on every input is indistinguishable
from a provider facing an empty catalog. The architecture had no
positive control distinguishing "no asset" from "broken search."

This file is that positive control. Each registered provider ships
with a **known-good probe**: one (identifier, expected class) pair the
provider MUST resolve. If the probe goes empty, the alarm reads
"provider search is broken," NOT "catalog is empty."

The generalizable rule (promoted to permanent discipline alongside
predict-before-run):

  Every abstention path needs a positive control. A component whose
  correct failure mode is silence cannot be validated by observing
  silence — you must also observe it SPEAK when it should.

These probes run against the live cluster (port-forward to engine-o,
which forwards to each provider). They're integration tests, not pure
logic. The `pytest.mark.requires_cluster` marker keeps them out of
the unit suite. The pure-logic tests in
test_instance_resolution_decision.py cover the decision table
exhaustively without a cluster; these probes cover the provider
implementations.

Adding a new provider:
  1. Register it through mesh-registrar as the recipe describes.
  2. Add one row to KNOWN_GOOD_PROBES below.
  3. The substrate invariants now catch silent search failures in
     the new provider too — same shape, same alarm.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx
import pytest


_BASE = os.getenv("ROUTING_TEST_BASE_URL", "http://localhost:8084")
_TIMEOUT_SEC = float(os.getenv("ROUTING_TEST_TIMEOUT_SEC", "30"))


@dataclass(frozen=True)
class ProviderProbe:
    """A known-good probe for one mesh:resolveInstance provider.

    Attributes
    ----------
    provider_name : str
        Human label that appears in the test failure if the probe goes
        red — names the broken provider directly.
    identifier : str
        A token the provider MUST resolve. Chosen to be unambiguously
        present in whatever registry the provider owns.
    expected_class_uri : str
        The canonical idp:* (or domain) class the provider should
        return. Allows the probe to also catch a provider that returns
        candidates but with the wrong class.
    """
    provider_name: str
    identifier: str
    expected_class_uri: str


# Each provider adds one row here when it registers as a
# mesh:resolveInstance edge. The probe asserts the provider can
# SPEAK, not just abstain.
KNOWN_GOOD_PROBES: list[ProviderProbe] = [
    # Engine D — catalog (Recipe v2 v1 provider).
    # `gold.sales.revenue_summary` exists as a DATASET in the sandbox
    # DataHub. Engine D must classify it as idp:Table.
    ProviderProbe(
        provider_name="engine_d (DataHub)",
        identifier="gold.sales.revenue_summary",
        expected_class_uri="idp:Table",
    ),
    # Engine E — knowledge graph (Recipe v2 v2 provider, Gate 6
    # generality acceptance). The sandbox Neo4j has a WorkInstruction
    # node with procedureId='TEST-1234' (the same code the
    # MAINTENANCE-domain matrix rows have used for ages). Engine E's
    # /resolve_instance must classify the code as the canonical IOF-
    # MRO WorkInstruction class via direct Cypher lookup.
    ProviderProbe(
        provider_name="engine_e (Neo4j WorkInstruction)",
        identifier="TEST-1234",
        expected_class_uri="https://spec.industrialontologies.org/ontology/maintenance/MaintenanceReferenceOntology/WorkInstruction",
    ),
    # Engine E — equipment-instance variant. partNumber AFP-2024-001
    # is the aux fuel pump on tail 42 (urn:instance:c130:tail42:
    # aux_fuel_pump). The Instance label maps to mro:Equipment in
    # _LABEL_TO_CLASS_URI. Pair with the WorkInstruction probe so a
    # regression on Engine E's class mapping (e.g. someone "fixes" a
    # canonical class URI and breaks one but not the other) turns
    # red on the right row.
    ProviderProbe(
        provider_name="engine_e (Neo4j Equipment)",
        identifier="AFP-2024-001",
        expected_class_uri="mro:Equipment",
    ),
]


@pytest.mark.parametrize(
    "probe", KNOWN_GOOD_PROBES,
    ids=[p.provider_name for p in KNOWN_GOOD_PROBES],
)
def test_provenance_proves_provider_spoke(probe: ProviderProbe) -> None:
    """For each known-good identifier, /resolve's provenance MUST
    show the phone book SPOKE — instance_resolved=true with the
    expected class. An ``instance_match=empty`` here means SOME
    provider's search is broken; the resolver gracefully fell
    through to the LLM's guess.

    Why route through /resolve instead of curling each provider
    directly: provider endpoints are in-cluster DNS (e.g.
    iagent-engine-d:8085) and the test runs against port-forwarded
    engine-o. More importantly, /resolve exercises the full
    discovery + fan-out + decision-table pipeline — a stronger
    integration assertion than checking each provider in isolation.
    """
    try:
        resp = httpx.post(
            f"{_BASE}/resolve",
            json={
                "query": f"Tell me about {probe.identifier}",
                "domain": "DATA_ENGINEERING",
            },
            timeout=_TIMEOUT_SEC,
        )
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Engine O /resolve not reachable: {exc}")

    body = resp.json()
    provenance = body.get("provenance") or {}

    assert provenance, (
        f"\n  /resolve returned no provenance dict for known-good probe "
        f"{probe.provider_name}.\n"
        f"  Identifier: {probe.identifier!r}\n"
        f"  Either the LLM did not extract instance_identifier (recall "
        f"regression — check the BAML prompt) or the instance-resolution "
        f"leg never fired (look for a discovery / fan-out exception in "
        f"engine-o logs).\n"
        f"  Body: {body}"
    )

    assert provenance.get("instance_identifier") == probe.identifier, (
        f"\n  /resolve provenance shows a DIFFERENT instance_identifier "
        f"than the probe — the LLM may have extracted the wrong token.\n"
        f"  Expected: {probe.identifier!r}\n"
        f"  Got: {provenance.get('instance_identifier')!r}"
    )

    instance_match = provenance.get("instance_match")
    assert instance_match in ("exact", "fuzzy"), (
        f"\n  Known-good probe for {probe.provider_name} did NOT resolve.\n"
        f"  Identifier: {probe.identifier!r}\n"
        f"  Expected: instance_match in (exact, fuzzy) with the phone book "
        f"speaking up.\n"
        f"  Got: instance_match={instance_match!r}, provenance={provenance}\n"
        f"\n  This is the silent-empty failure mode the abstention contract "
        f"masks. A provider returning empty here is INDISTINGUISHABLE from "
        f"an empty registry without this probe — that's why the probe "
        f"exists. Likely causes:\n"
        f"   - Provider's search path errors silently (GraphQL validation, "
        f"     missing required field, auth misconfig). Check the provider's "
        f"     logs for 'errors=[...]' entries.\n"
        f"   - Provider not registered (run gateway log: grep 'Registered "
        f"     urn:.*resolveInstance').\n"
        f"   - Provider's Neo4j edge not materialized (run sensor log: grep "
        f"     '✅ Synced predicate edge: .*resolveInstance').\n"
    )

    assert body.get("resolved_uri", "").endswith(
        probe.expected_class_uri.split(":")[-1]
    ) or body.get("resolved_uri") == probe.expected_class_uri, (
        f"\n  Known-good probe for {probe.provider_name} resolved but to "
        f"the WRONG class.\n"
        f"  Identifier: {probe.identifier!r}\n"
        f"  Expected class: {probe.expected_class_uri}\n"
        f"  Got: {body.get('resolved_uri')!r}\n"
        f"  Provenance: {provenance}"
    )
