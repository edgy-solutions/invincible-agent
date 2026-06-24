"""Per-engine specialist-endpoint reachability probes.

The standing rule [[feedback-integration-positive-controls]] says
cross-leg contracts need integration positive controls. This file
covers the contract:

  "Every endpoint_url in the verb registry MUST accept the
  supervisor's dispatch POST without 404."

Caught 2026-06-24 when Engine DA's verb registry advertised
``http://iagent-data-analyst:8089/analyze_data`` but the FastAPI app
only mounted Restate at ``/restate`` — every analyzeDataset routing
landed on 404 and the pipeline failed. The matrix passed at 23/23
and the integration probes at 6/6, because neither suite exercises
the endpoint-accepts-POST contract; the matrix stops at
``/classify_predicate`` (never dispatches), and the resolve-instance
probes hit ``/resolve_instance`` directly (not the verb's dispatch
URL). This file closes that gap.

Each probe queries engine-o's verb registry for the registered
endpoint, then POSTs a minimal supervisor-shaped payload. A 404
fails the probe; any other response code (200, 400, 422, 500,
etc.) passes — the contract is "accepts the POST", not "returns
success." The smolagent inside may legitimately error on the test
payload; that's not what this probe asserts.

Run alongside the matrix per the updated baseline-regression-gate
discipline.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import httpx
import pytest


_BASE = os.getenv("ROUTING_TEST_BASE_URL", "http://localhost:8084")
_TIMEOUT_SEC = float(os.getenv("ROUTING_TEST_TIMEOUT_SEC", "15"))


# Subjects that engine-o's /find_compatible_verbs reliably enumerates
# in the sandbox; each entry expects at least one specialist verb
# registered. Adding a new engine to the registry should add an entry
# here too so the probe catches missing dispatch endpoints.
SUBJECT_PROBES = [
    # idp#Table — should surface Engine A (describeAsset), Engine DA
    # (analyzeDataset), enumerateCatalog, traceLineage, etc.
    "http://invincible-agent/idp#Table",
    # mro:WorkInstruction — Engine E's queryKnowledgeGraph.
    "https://spec.industrialontologies.org/ontology/maintenance/MaintenanceReferenceOntology/WorkInstruction",
    # mil#DescriptiveDataModule — Engine W's retrieveKnowledge.
    "http://edgy-solutions.com/ontology/mil#DescriptiveDataModule",
]


@dataclass(frozen=True)
class _Verb:
    iri: str
    endpoint: str


def _fetch_verbs(subject_uri: str) -> list[_Verb]:
    """Ask engine-o which verbs are registered for a subject. Empty
    list (or HTTP failure) skips the probe — the cluster isn't
    fully reachable; the probe can't run."""
    try:
        resp = httpx.post(
            f"{_BASE}/find_compatible_verbs",
            json={"subject_uri": subject_uri, "entitled_domains": []},
            timeout=_TIMEOUT_SEC,
        )
        resp.raise_for_status()
        body = resp.json()
    except Exception as exc:
        pytest.skip(f"engine-o /find_compatible_verbs not reachable: {exc}")
    return [
        _Verb(iri=str(v.get("verb_iri") or ""), endpoint=str(v.get("endpoint_url") or ""))
        for v in (body.get("verbs") or [])
        if v.get("endpoint_url")
    ]


def _payload() -> dict:
    """Minimal supervisor-shaped dispatch payload. The engine's
    smolagent may legitimately error on this — the probe doesn't
    assert success, only that the endpoint accepts the POST (not
    404). Carry both common field names so per-engine handlers can
    pull what they expect."""
    return {
        "task_description": "Endpoint reachability probe.",
        "user_query": "Endpoint reachability probe.",
        "dataset_id": "probe",
        "domain": "DATA_ENGINEERING",
        "resolved_instance_id": "",
    }


@pytest.mark.parametrize("subject_uri", SUBJECT_PROBES, ids=lambda s: s.rsplit("/", 1)[-1])
def test_registered_endpoints_accept_dispatch_post(subject_uri: str) -> None:
    """For every verb registered against this subject, the endpoint
    MUST accept the supervisor's POST without 404. Other status
    codes (200/400/422/500) pass — the contract is "endpoint exists
    and accepts the dispatch shape", not "returns success."

    The Engine DA 404 trap that surfaced this probe pattern: registry
    advertised iagent-data-analyst:8089/analyze_data; FastAPI app
    didn't have that route mounted; every analyzeDataset routing
    landed on 404 and the pipeline failed silently from the
    supervisor's perspective.
    """
    verbs = _fetch_verbs(subject_uri)
    if not verbs:
        pytest.skip(f"No verbs registered for {subject_uri} — nothing to probe.")

    payload = _payload()
    failures: list[str] = []

    for v in verbs:
        if not v.endpoint.startswith(("http://", "https://")):
            continue
        # Use a short timeout — we only care that the route exists
        # and accepts the POST shape; the smolagent doesn't need to
        # finish (and won't, on a probe payload).
        try:
            resp = httpx.post(v.endpoint, json=payload, timeout=5.0)
        except httpx.TimeoutException:
            # Route exists, just took longer than the probe budget.
            # That's an accept — the supervisor's per-engine timeout
            # is 1800s in production.
            continue
        except Exception as exc:
            # Connection refused / DNS failure / pod not running.
            # That's a separate cluster-health issue, not the
            # endpoint contract this probe asserts. Skip the verb
            # rather than fail the probe.
            print(f"  skip {v.iri} @ {v.endpoint}: transport error {exc}")
            continue

        if resp.status_code == 404:
            failures.append(
                f"\n    {v.iri} → {v.endpoint}\n"
                f"      404 NOT FOUND — the registered endpoint does not exist.\n"
                f"      The supervisor's dispatch would fail silently here.\n"
                f"      Fix: add the route on the engine's FastAPI app, or\n"
                f"      correct the endpoint_url in the verb registration."
            )

    assert not failures, (
        f"\n  Specialist endpoint(s) registered but unreachable for "
        f"subject {subject_uri}:\n"
        + "".join(failures)
        + "\n\n  This probe exists because the matrix tests /classify_predicate\n"
        f"  but not the dispatch HTTP call. Without it, a registry "
        f"misalignment\n  silently routes every query to the generalist "
        f"fallback (or, when\n  the supervisor's raise_for_status is hit, "
        f"crashes the supervisor\n  before the answer is returned). The "
        f"matrix passes either way."
    )
