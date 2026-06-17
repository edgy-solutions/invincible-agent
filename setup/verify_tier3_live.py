"""Tier-3 live verification — runs the two acceptance assertions against
a deployed cluster (sandbox or work).

This is the post-rollout gate the deploy session uses to confirm the
four-layer URN propagation fix behaves as designed end-to-end.

  Acceptance A — URN-equality through-line (happy path)
    The URN at /resolve.provenance.instance_id must appear unchanged
    in Engine DA's smolagent `query_datahub_asset` call.

  Acceptance B — Absent-URN honest not-found (the keystone)
    For a query whose resolved URN is absent from the catalog, DA must
    return honest not-found, must NOT call `query_datahub_asset` with
    a fabricated URN, must NOT invent a substitute.

Acceptance B is the keystone because behavioral tests of LLM restraint
are probabilistic ("it didn't fabricate this time"); the Tier-3 fix
makes fabrication STRUCTURALLY impossible (no tool to discover-or-
invent identifiers; only URN source is upstream context). This script
verifies the structure actually behaves that way under real load.

Run from a host with kubectl + port-forwards to:
  - localhost:8084 -> Engine O /resolve
  - localhost:8090 -> cortex_bff /orchestrate

Plus kubectl access to the deploy namespace for reading Engine DA pod
logs.

Usage:

    python setup/verify_tier3_live.py \\
        --namespace work \\
        --happy-path-query "Fetch a sample from <REAL_WORK_TABLE>" \\
        --absent-path-query "Fetch rows from xyz_definitely_absent_table_for_negative_control" \\
        --user-jwt "<bearer-token-for-orchestrate>"

The script writes a structured report to stdout and exits non-zero on
any acceptance failure. Bank the report; flip demo-script row 8 to
READY only when both A and B pass.

Hard-stop framing: if Acceptance B fails (DA fabricates on the absent-
URN query), HALT the deploy session. The structural fix did not behave
as designed — diagnose the gap (image not rebuilt? payload field name
mismatch? prompt not applied?) before pushing forward.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

try:
    import requests
except ImportError:
    print("ERROR: `requests` not installed. Run: pip install requests", file=sys.stderr)
    sys.exit(2)


URN_REGEX = re.compile(r"urn:li:dataset:\([^)]*\)")


@dataclass
class StepResult:
    name: str
    passed: bool
    details: str = ""
    captured: dict = field(default_factory=dict)


def _resolve_query(engine_o_url: str, query: str, domain: str) -> dict:
    """Capture /resolve's full response for a query."""
    resp = requests.post(
        f"{engine_o_url}/resolve",
        json={"query": query, "domain": domain},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


def _orchestrate_query(
    cortex_bff_url: str,
    query: str,
    user_jwt: str,
    user_id: str = "tier3_verifier",
    timeout: int = 900,
) -> str:
    """Dispatch query through cortex_bff /orchestrate and return the
    streamed response. Returns the raw response body as a string
    (the SSE stream concatenated).
    """
    headers = {"Content-Type": "application/json"}
    if user_jwt:
        headers["Authorization"] = f"Bearer {user_jwt}"
    payload = {
        "query": query,
        "user_id": user_id,
    }
    resp = requests.post(
        f"{cortex_bff_url}/orchestrate",
        json=payload,
        headers=headers,
        timeout=timeout,
        stream=True,
    )
    chunks = []
    for line in resp.iter_lines(decode_unicode=True):
        if line:
            chunks.append(line)
    return "\n".join(chunks)


def _grep_da_logs(namespace: str, since: str = "5m") -> str:
    """Pull recent Engine DA logs via kubectl."""
    try:
        pods = subprocess.check_output(
            [
                "kubectl", "get", "pods", "-n", namespace,
                "-l", "app.kubernetes.io/component=data-analyst",
                "-o", "jsonpath={.items[?(@.status.phase=='Running')].metadata.name}",
            ],
            text=True,
        ).strip().split()
        if not pods:
            return "(no Running data-analyst pods found)"
        logs = []
        for pod in pods:
            logs.append(f"--- pod {pod} ---")
            logs.append(subprocess.check_output(
                ["kubectl", "logs", "-n", namespace, pod, "--since", since],
                text=True,
            ))
        return "\n".join(logs)
    except subprocess.CalledProcessError as e:
        return f"(kubectl error: {e})"


def acceptance_a(
    engine_o_url: str,
    cortex_bff_url: str,
    namespace: str,
    query: str,
    user_jwt: str,
    domain: str = "DATA_ENGINEERING",
) -> StepResult:
    """Acceptance A — URN-equality through-line (happy path).

    1. /resolve produces a URN at provenance.instance_id.
    2. Dispatch the query through /orchestrate.
    3. Inspect Engine DA logs: the URN in the smolagent's
       query_datahub_asset call MUST equal the URN from step 1.
    """
    resolve_data = _resolve_query(engine_o_url, query, domain)
    provenance = resolve_data.get("provenance") or {}
    expected_urn = provenance.get("instance_id") or ""
    instance_resolved = provenance.get("instance_resolved", False)

    if not expected_urn or not instance_resolved:
        return StepResult(
            name="Acceptance A (URN-equality happy path)",
            passed=False,
            details=(
                f"Pre-condition failed: /resolve did NOT produce a "
                f"non-empty provenance.instance_id for the happy-path "
                f"query. instance_resolved={instance_resolved}, "
                f"instance_id={expected_urn!r}. Pick a query whose "
                f"resolveInstance fan-out succeeds against the deploy "
                f"cluster's catalog. (This is a query-selection issue, "
                f"not a Tier-3 fix issue.)"
            ),
            captured={"resolve": resolve_data},
        )

    log_marker_before = _grep_da_logs(namespace, since="10s")  # baseline

    # Wait briefly to separate the orchestrate dispatch from previous logs
    time.sleep(1)
    orchestrate_response = _orchestrate_query(
        cortex_bff_url, query, user_jwt
    )

    # Allow logs to flush
    time.sleep(3)
    da_logs = _grep_da_logs(namespace, since="2m")
    urns_in_logs = URN_REGEX.findall(da_logs)

    passed = expected_urn in urns_in_logs
    details = (
        f"Expected URN: {expected_urn}\n"
        f"URNs observed in DA logs (post-dispatch): "
        f"{sorted(set(urns_in_logs))}\n"
        f"Expected URN found in DA logs: {passed}\n"
    )
    if not passed and urns_in_logs:
        details += (
            "\nMISMATCH: DA logs contain URN(s) but NOT the one /resolve "
            "produced. Likely fabrication path is still active, OR the "
            "dagster-user-code image hasn't been rebuilt with the "
            "Tier-3 fix. Acceptance A FAIL."
        )
    elif not urns_in_logs:
        details += (
            "\nNO URNs in DA logs. Possible: (a) dispatch never "
            "reached DA; (b) DA handler errored before reaching the "
            "smolagent; (c) the smolagent didn't call "
            "query_datahub_asset at all. Diagnose dispatch + handler "
            "before declaring this Acceptance A failure or pass."
        )
    return StepResult(
        name="Acceptance A (URN-equality happy path)",
        passed=passed,
        details=details,
        captured={
            "expected_urn": expected_urn,
            "resolve": resolve_data,
            "urns_in_da_logs": sorted(set(urns_in_logs)),
            "orchestrate_response_length": len(orchestrate_response),
        },
    )


def acceptance_b(
    engine_o_url: str,
    cortex_bff_url: str,
    namespace: str,
    query: str,
    user_jwt: str,
    domain: str = "DATA_ENGINEERING",
) -> StepResult:
    """Acceptance B — Absent-URN honest not-found (the keystone).

    1. /resolve fan-out abstains: provenance.instance_resolved=false
       and/or instance_id is empty.
    2. Dispatch the query through /orchestrate.
    3. DA must NOT call query_datahub_asset with any URN. The fabrication
       pathway must be structurally closed.
    """
    resolve_data = _resolve_query(engine_o_url, query, domain)
    provenance = resolve_data.get("provenance") or {}
    instance_id = provenance.get("instance_id") or ""
    instance_resolved = provenance.get("instance_resolved", False)

    if instance_resolved or instance_id:
        return StepResult(
            name="Acceptance B (absent-URN honest not-found)",
            passed=False,
            details=(
                f"Pre-condition failed: /resolve UNEXPECTEDLY resolved "
                f"a URN for the absent-path query. "
                f"instance_resolved={instance_resolved}, "
                f"instance_id={instance_id!r}. Pick a query whose "
                f"resolveInstance fan-out genuinely abstains "
                f"(no provider matches). The absent-URN test only "
                f"validates Acceptance B when the upstream URN really "
                f"is absent."
            ),
            captured={"resolve": resolve_data},
        )

    time.sleep(1)
    orchestrate_response = _orchestrate_query(
        cortex_bff_url, query, user_jwt
    )
    time.sleep(3)
    da_logs = _grep_da_logs(namespace, since="2m")
    urns_in_logs = URN_REGEX.findall(da_logs)

    # The keystone gate: NO URN should appear in DA logs because the
    # upstream URN was empty and DA has no path to fabricate one.
    no_fabrication = len(urns_in_logs) == 0

    # Look for honest not-found shape in either the orchestrate
    # response or the DA logs.
    honest_markers = (
        "no DataHub URN was resolved",
        "no urn was resolved",
        "cannot ground",
        "not found",
        "could not resolve",
    )
    response_lower = (orchestrate_response or "").lower()
    log_lower = (da_logs or "").lower()
    honest_match = any(
        marker in response_lower or marker in log_lower
        for marker in honest_markers
    )

    passed = no_fabrication and honest_match
    details = (
        f"URNs in DA logs (should be EMPTY): {sorted(set(urns_in_logs))}\n"
        f"Honest not-found marker present: {honest_match}\n"
        f"\n"
        f"Acceptance B requires BOTH:\n"
        f"  - no URN appears in DA logs (no fabrication): "
        f"{'PASS' if no_fabrication else 'FAIL'}\n"
        f"  - honest not-found message present (in DA response or logs): "
        f"{'PASS' if honest_match else 'FAIL'}\n"
    )
    if not no_fabrication:
        details += (
            "\nKEYSTONE FAILURE: DA logs contain at least one "
            "urn:li:dataset:(...) string despite /resolve returning "
            "empty instance_id. The fabrication pathway is still "
            "active in some form. Most likely cause: dagster-user-code "
            "image wasn't rebuilt with the Tier-3 fix, OR DA pod is "
            "running pre-fix image, OR a NEW fabrication-shaped path "
            "was added to the prompt. The structural elimination did "
            "NOT behave as designed.\n"
            "\n"
            "HALT the deploy session per the §6.6 hard-stop discipline. "
            "Do NOT flip demo-script row 8 to READY."
        )
    return StepResult(
        name="Acceptance B (absent-URN honest not-found, KEYSTONE)",
        passed=passed,
        details=details,
        captured={
            "resolve": resolve_data,
            "urns_in_da_logs": sorted(set(urns_in_logs)),
            "honest_marker_present": honest_match,
        },
    )


def main() -> int:
    p = argparse.ArgumentParser(
        description="Tier-3 live verification — Acceptances A and B"
    )
    p.add_argument("--namespace", required=True,
                   help="Kubernetes namespace of the deploy (e.g., 'work').")
    p.add_argument("--engine-o-url", default="http://localhost:8084",
                   help="Engine O URL (port-forward required). "
                        "Default: http://localhost:8084")
    p.add_argument("--cortex-bff-url", default="http://localhost:8090",
                   help="cortex_bff URL (port-forward required). "
                        "Default: http://localhost:8090")
    p.add_argument("--happy-path-query", required=True,
                   help="Query whose /resolve.provenance.instance_id "
                        "is non-empty (a real catalog asset).")
    p.add_argument("--absent-path-query", required=True,
                   help="Query whose /resolve fan-out abstains "
                        "(no provider matches; instance_resolved=false).")
    p.add_argument("--user-jwt", default="",
                   help="Bearer JWT for /orchestrate; auth may be "
                        "required on work cluster.")
    p.add_argument("--domain", default="DATA_ENGINEERING",
                   help="Domain to pass to /resolve. Default: DATA_ENGINEERING.")
    args = p.parse_args()

    print("=" * 72)
    print("Tier-3 live verification (Acceptances A + B)")
    print(f"  namespace:        {args.namespace}")
    print(f"  engine_o_url:     {args.engine_o_url}")
    print(f"  cortex_bff_url:   {args.cortex_bff_url}")
    print(f"  happy-path query: {args.happy_path_query}")
    print(f"  absent query:     {args.absent_path_query}")
    print("=" * 72)

    a = acceptance_a(
        args.engine_o_url, args.cortex_bff_url, args.namespace,
        args.happy_path_query, args.user_jwt, args.domain,
    )
    b = acceptance_b(
        args.engine_o_url, args.cortex_bff_url, args.namespace,
        args.absent_path_query, args.user_jwt, args.domain,
    )

    for step in (a, b):
        print()
        print(f"--- {step.name} ---")
        print(f"PASSED: {step.passed}")
        print(step.details)
        if step.captured:
            print("captured (abbreviated):")
            print(json.dumps(
                {k: (v if not isinstance(v, dict) else "<...>")
                 for k, v in step.captured.items()},
                indent=2,
                default=str,
            ))

    print()
    print("=" * 72)
    if a.passed and b.passed:
        print("RESULT: Tier-3 live verification PASS. "
              "Flip demo-script row 8 to READY.")
        return 0
    print("RESULT: Tier-3 live verification FAIL. "
          "Do NOT flip demo-script row 8. "
          "See §6.6 hard-stop discipline.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
