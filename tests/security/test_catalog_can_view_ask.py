#!/usr/bin/env python3
"""Integration proof for the ADR-0025 hop-2 ASK: query_metadata's
`_topaz_can_view` helper against the LIVE Topaz decider.

WHY THIS EXISTS: hop-2 moves the catalog domain gate from an in-code
predicate to a Topaz ASK (catalog_domain_view.rego, package
invincible_agent.catalog.can_view). This exercises the REAL helper
`datahub_wrapper.main._topaz_can_view` - not a mock, not a reimplementation
- against a running authorizer, so it proves the whole ask end of the seam
at once: the payload shape, the identityContext-plus-resourceContext quirk,
the decisions[].is parsing, AND that the decider DISCRIMINATES.

REFERENCE INDEPENDENCE (per `[[verification-reference-independence]]`): the
expected answers come from policy/users.yaml (human-asserted group grants:
alice+agent are in data-engineers; bob+carol are deliberately NOT), NOT from
a Topaz readback. bob returning False is the RED half - a decider that
returned True for everyone would pass a naive "alice works" check but fail
here.

FAIL-CLOSED: an empty subject (no verified email) must DENY - an auth-service
gap can't open the PII catalog.

Run against a cluster with the REST authorizer reachable (port-forward
`svc/topaz-svc 18383:8383` or in-cluster DNS):

    TOPAZ_AUTHORIZER_URL=http://localhost:18383 \\
    python tests/security/test_catalog_can_view_ask.py

Exit 0 = ask works + discriminates + fail-closes. Non-zero = a mismatch.
"""
from __future__ import annotations

import asyncio
import os
import sys

# Point the helper at the reachable authorizer BEFORE importing the module
# (it reads TOPAZ_AUTHORIZER_URL at import). Default to the conventional
# port-forward so a bare `python …` run works against a forwarded cluster.
os.environ.setdefault("TOPAZ_AUTHORIZER_URL", "http://localhost:18383")

# Import the REAL helper - the whole point is to exercise production code,
# not a copy. (DataHub connects in lifespan, not at import, so this is safe.)
from agent_fleet.datahub_wrapper.main import (  # noqa: E402
    _topaz_can_view,
    _CATALOG_VIEW_POLICY_PATH,
    _ENGINE_D_SERVED_DOMAIN,
)

# Expected truth from policy/users.yaml group grants - the INDEPENDENT
# reference. If a grant changes in users.yaml, update this table in the same
# PR (that discipline is what keeps this probe non-circular).
#   (email, domain, expected_allowed, why)
CASES = [
    ("alice@example.com", _ENGINE_D_SERVED_DOMAIN, True,  "data-engineers (FIXTURE grant)"),
    ("agent@example.com", _ENGINE_D_SERVED_DOMAIN, True,  "data-engineers (ROLE grant)"),
    ("bob@example.com",   _ENGINE_D_SERVED_DOMAIN, False, "aviation-stewards only - RED half"),
    ("carol@example.com", _ENGINE_D_SERVED_DOMAIN, False, "aviation-mechanics only - RED half"),
    # Same user flips across domains -> proves per-domain derivation, not a
    # blanket allow: bob HAS an AVIATION cell (DATA_STEWARD:AVIATION).
    ("bob@example.com",   "AVIATION",              True,  "bob DOES hold AVIATION steward cell"),
    # Fail-closed: no verified subject -> deny.
    ("",                  _ENGINE_D_SERVED_DOMAIN, False, "empty subject -> fail-closed DENY"),
]


async def _run() -> int:
    print(f"=== hop-2 ASK probe - policy={_CATALOG_VIEW_POLICY_PATH} "
          f"authorizer={os.environ['TOPAZ_AUTHORIZER_URL']} ===")
    failures = 0
    for email, domain, expected, why in CASES:
        got = await _topaz_can_view(email, domain)
        ok = got is expected
        print(f"  [{'PASS' if ok else 'FAIL'}] can_view({email or '<empty>'!r}, "
              f"{domain}) = {got}  (expect {expected} - {why})")
        if not ok:
            failures += 1
    print(f"\n=== {len(CASES)} cases, {failures} failures ===")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_run()))
