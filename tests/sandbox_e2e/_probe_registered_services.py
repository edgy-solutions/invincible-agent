"""REGISTRY INVARIANT, service half — every expected Restate service is actually REGISTERED.

THE EXHIBIT THIS EXISTS FOR (witnessed 2026-08-05). `AutonomousReview` shipped in the engine-a image
and was ABSENT from `restate deployments list`, because a new service requires DISCOVERY and a pod
roll does not perform one. Every `workflow_send` to it would have failed as service-not-found — and
the phase-1.3 routing witness would have **measured a registration gap while looking like a routing
failure.** A witness that misattributes is worse than one that fails: it produces a confident wrong
conclusion about the code under test.

The class, in one line: **shipped is not registered — an artifact arriving in the pod proves nothing
about the runtime knowing it exists.**

WHY A DEPLOY STEP AND NOT A STARTUP ASSERTION. The definition half IS asserted at engine-a boot
(`main._assert_definitions_registered`), because it is a local file read. This half needs Restate's
admin API, and asserting it at startup would make the engine's boot depend on Restate being up —
converting a deploy check into a liveness coupling, which trades one silent failure for a noisier
one. Run this AFTER a roll that adds or renames a service.

Run:  kubectl exec -n <ns> <restate-pod> -- restate --yes deployments list   # what this parses
      python tests/sandbox_e2e/_probe_registered_services.py                 # RESTATE_ADMIN_URL
Exit: 0 all present · 1 something expected is missing · 2 could not tell (see POSITIVE CONTROL)
Fix:  restate deployments register <endpoint> --force
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

ADMIN = os.getenv("RESTATE_ADMIN_URL", "http://localhost:19070")

# Every service this deployment's engines register. A name here that Restate does not know is the
# defect; a name Restate knows that is NOT here is fine (other engines register their own).
EXPECTED = (
    "ReviewStarter",
    "GroupedReview",
    "AutonomousReview",     # the exhibit — added 1.3, needs `deployments register --force`
    "DispatchItem",
    "BPMNWorkflowRunner",
    "AnalystService",
)


def main() -> int:
    try:
        req = urllib.request.Request(f"{ADMIN.rstrip('/')}/services")
        with urllib.request.urlopen(req, timeout=20) as r:
            body = json.loads(r.read())
    except Exception as exc:  # noqa: BLE001
        print(f"INCONCLUSIVE: Restate admin API unreachable at {ADMIN} ({exc}).")
        print("  An unreachable registry is NOT an empty one — this exits 2, never 1, because "
              "'could not tell' must not read as 'nothing is registered'.")
        return 2

    services = {s.get("name") for s in (body.get("services") or []) if s.get("name")}
    if not services:
        # POSITIVE CONTROL. Restate answering with zero services is far more likely a parse/shape
        # problem than a directory that lost every registration at once. A probe that has never been
        # observed reporting GREEN has not earned having its RED acted on.
        print("INCONCLUSIVE: the admin API answered with NO services at all — far more likely a "
              "response-shape change than a registry that lost everything. Fix the probe's read "
              "before believing its RED.")
        return 2

    missing = [s for s in EXPECTED if s not in services]
    print(f"registered services: {len(services)}")
    for s in EXPECTED:
        print(f"  {s:<24} {'OK' if s in services else 'MISSING'}")
    if missing:
        print(f"\nREGISTRY INVARIANT FAILED — {len(missing)} expected service(s) not registered: "
              f"{', '.join(missing)}")
        print("  The image may well contain them. Registration is a SEPARATE act, and a pod roll "
              "does not perform it.")
        print("  Fix: restate deployments register <endpoint> --force")
        return 1

    print(f"\nCLEAN: all {len(EXPECTED)} expected services are registered.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
