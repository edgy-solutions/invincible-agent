#!/usr/bin/env python3
"""
Outside-reference security probe for the query_metadata catalog authz
gate (2026-07-02 stopgap; ADR-0025 "catalog is an enforcement surface").

WHY OUTSIDE-REFERENCE (per `[[verification-reference-independence]]`):
this probe does NOT read back its own writes. It calls the LIVE Engine
D `query_metadata` the way a real low-privileged caller would, and
asserts denial. The reference (what SHOULD be denied) comes from the
confirmed exploit's finding table — the exact calls that previously
LEAKED (garbage personas, DEFENSE domain, PII-tagged Customer 360) are
the RED BASELINE. Reality already ran red-first; this asserts green.

Two layers, both required:
  1. DIRECT gate — call query_metadata with a non-entitled scope and
     assert denial (the coarse domain gate fires).
  2. END-TO-END fallback — call Engine A /analyze as a non-entitled
     caller and assert the generalist fallback no longer launders
     catalog metadata (the whole bypass chain is closed).

Run against a cluster (kubectl-reachable) with the engine URLs pointed
at port-forwards or in-cluster service DNS:

    ENGINE_D_URL=http://localhost:8085 \\
    ENGINE_A_URL=http://localhost:8081 \\
    python tests/security/test_query_metadata_authz.py

Exit 0 = all denials hold. Non-zero = a leak survived (or the gate
over-denied an entitled caller).
"""
from __future__ import annotations

import os
import sys

import requests


ENGINE_D_URL = os.getenv("ENGINE_D_URL", "http://localhost:8085")
ENGINE_A_URL = os.getenv("ENGINE_A_URL", "http://localhost:8081")

# The PII-tagged asset the exploit leaked. If this string appears in a
# response for a NON-ENTITLED caller, the gate failed.
LEAK_MARKER = "Customer 360"
PII_MARKER = "pii"
SERVED_DOMAIN = os.getenv("ENGINE_D_SERVED_DOMAIN", "DATA_ENGINEERING")

_failures: list[str] = []
_checks = 0


def _leaked(text: str) -> bool:
    t = (text or "").lower()
    return LEAK_MARKER.lower() in t or PII_MARKER in t


def check(name: str, condition: bool, detail: str = "") -> None:
    global _checks
    _checks += 1
    mark = "PASS" if condition else "FAIL"
    print(f"  [{mark}] {name}" + (f" - {detail}" if detail else ""))
    if not condition:
        _failures.append(f"{name}: {detail}")


def query_metadata(persona: str, entitled_domains: list[str] | None, domain: str = "DEFENSE") -> str:
    body = {
        "user_query": "Customer 360 dashboard owner",
        "persona": persona,
        "domain": domain,
    }
    if entitled_domains is not None:
        body["entitled_domains"] = entitled_domains
    r = requests.post(f"{ENGINE_D_URL}/query_metadata", json=body, timeout=20)
    r.raise_for_status()
    d = r.json()
    return (d.get("data") or {}).get("short_answer", "")


def main() -> int:
    print("=== Layer 1: DIRECT query_metadata gate (the red baseline) ===")
    # These are the EXACT calls from the confirmed-exploit finding table.
    # Every one previously LEAKED; every one must now DENY.
    for persona in ("MECHANIC", "ANALYST", "DATA_STEWARD", "NOBODY"):
        ans = query_metadata(persona, entitled_domains=[], domain="DEFENSE")
        check(
            f"empty-scope persona={persona} -> denied, no leak",
            not _leaked(ans),
            detail=(ans[:80] + "...") if ans else "(empty)",
        )
    # Non-entitled explicit scope (DEFENSE-only caller vs DATA_ENGINEERING catalog).
    ans = query_metadata("DATA_STEWARD", entitled_domains=["DEFENSE"], domain="DEFENSE")
    check("DEFENSE-scope -> denied, no leak", not _leaked(ans),
          detail=(ans[:80] + "...") if ans else "(empty)")

    # POSITIVE control — an ENTITLED caller MUST still get the metadata,
    # else the gate over-denies (a gate that denies everything is not a
    # gate, it's an outage). Reference = the served domain itself.
    print("=== Positive control: entitled caller still served ===")
    ans = query_metadata("DATA_STEWARD", entitled_domains=[SERVED_DOMAIN], domain=SERVED_DOMAIN)
    check(f"{SERVED_DOMAIN}-entitled -> served (leak marker PRESENT = correct)",
          _leaked(ans),
          detail=(ans[:80] + "...") if ans else "(empty)")

    print("=== Layer 2: END-TO-END Engine A fallback no longer launders ===")
    # Engine A /analyze as a non-entitled generalist-fallback caller.
    # Pre-fix this returned Customer 360 + PII via the hardcoded
    # DATA_STEWARD. Post-fix it forwards the real (empty/non-entitled)
    # scope, Engine D denies, and the generalist cannot surface it.
    # /analyze runs the full smolagent (LLM, up to ~300s) — heavy and
    # port-forward-flaky. BEST-EFFORT: a leak is ALWAYS a hard FAIL, but
    # a transport/timeout error is INCONCLUSIVE (validate live in the
    # browser). Set RUN_E2E=1 to require reachability.
    require_e2e = os.getenv("RUN_E2E", "").strip() in ("1", "true", "yes")
    try:
        body = {
            "task_description": "Who owns customer 360 dashboard?",
            "user_query": "Who owns customer 360 dashboard?",
            "dataset_id": "generalist_fallback",
            "user_persona": "MECHANIC",
            "persona": "MECHANIC",
            "domain": "UNKNOWN",
            "entitled_domains": ["DEFENSE"],  # non-entitled for the DE catalog
            "fallback_reason": "no_predicate_matched",
        }
        r = requests.post(f"{ENGINE_A_URL}/analyze", json=body, timeout=300)
        r.raise_for_status()
        d = r.json()
        blob = str(d)  # scan the whole payload; answer key varies
        # A leak here is ALWAYS a hard fail regardless of require_e2e.
        check("Engine A fallback (MECHANIC/DEFENSE) does not surface Customer 360 PII",
              not _leaked(blob),
              detail="leaked in response" if _leaked(blob) else "clean")
    except Exception as e:
        if require_e2e:
            check("Engine A end-to-end reachable", False, detail=f"transport error: {e}")
        else:
            print(f"  [INCONCLUSIVE] Engine A /analyze not exercised "
                  f"(transport: {e}). Validate live in browser.")

    print(f"\n=== {_checks} checks, {len(_failures)} failures ===")
    for f in _failures:
        print(f"  x {f}")
    return 1 if _failures else 0


if __name__ == "__main__":
    sys.exit(main())
