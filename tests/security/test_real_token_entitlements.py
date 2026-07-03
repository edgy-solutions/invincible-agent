#!/usr/bin/env python3
"""
Real-token entitlement integration probe (ADR-0026 step-6 companion).

WHY THIS EXISTS — the circular-verification class bit THREE times in one
week (`[[verification-reference-independence]]`):
  1. alice keyed by @edgy-solutions.com vs the real @example.com
  2. agent-user keyed by agent-user@example.com vs the real agent@example.com
  3. (adjacent) entitled_domains dropped on one dispatch path
Every identity-keying bug was caught the SAME way: only a real browser
login surfaced it, because the sync readback verified its OWN WRITE
(same id in, same id out — structurally blind to a mismatch with the
REAL JWT's claim). Three instances is past the banking threshold, so
this promotes the manual browser check into a CI guard.

WHAT IT DOES (the outside-reference the lesson demanded): mint a REAL
Keycloak token via the direct-access-grant flow for each seeded user,
call cortex-bff's /me/entitlements with it, and assert the response
carries the caller's SPECIFIC expected cells — NOT merely "non-empty"
(non-empty would pass if the user got SOMEONE ELSE's cells; the whole
bug class is identity keyed wrong, so the reference must be the exact
set). The reference (the token's real email claim → topaz lookup)
originates entirely OUTSIDE anything the seed/sync wrote.

Run (port-forward or in-cluster DNS):
    kubectl port-forward -n sandbox svc/iagent-keycloak 8080:8080 &
    kubectl port-forward -n sandbox svc/iagent-cortex-bff 8000:8000 &
    KEYCLOAK_URL=http://localhost:8080 \\
    CORTEX_BFF_URL=http://localhost:8000 \\
    python tests/security/test_real_token_entitlements.py

Exit 0 = every seeded user's /me/entitlements returns EXACTLY its
expected cells. Non-zero = an identity-keying or entitlement drift.
"""
from __future__ import annotations

import os
import sys

import requests


KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "http://localhost:8080")
CORTEX_BFF_URL = os.getenv("CORTEX_BFF_URL", "http://localhost:8000")
REALM = os.getenv("KEYCLOAK_REALM", "invincible-agent")
CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "cortex-ui")

# Sandbox realm seeds each demo user with a per-user password (the
# username itself; agent-user is "password"). CI supplies real
# passwords via env/secret; this map is the sandbox default.
PASSWORDS: dict[str, str] = {
    "alice": os.getenv("ALICE_PASSWORD", "alice"),
    "bob": os.getenv("BOB_PASSWORD", "bob"),
    "carol": os.getenv("CAROL_PASSWORD", "carol"),
    "agent-user": os.getenv("AGENT_USER_PASSWORD", "password"),
}


# The reference: the EXACT (persona, domain) cells each seeded user
# should hold, derived from policy/{groups,users}.yaml — NOT read back
# from topaz (that would be circular). This is the human-asserted truth
# the probe checks the real token against. If a grant is added/removed
# in policy/, update this table in the same PR (the table IS the test's
# independent reference).
EXPECTED: dict[str, set[tuple[str, str]]] = {
    "alice": {
        ("DATA_ENGINEER", "AVIATION"),
        ("DATA_ENGINEER", "DEFENSE"),
        ("ARCHITECT", "AVIATION"),
        ("ARCHITECT", "DEFENSE"),
        ("ARCHITECT", "ENTERPRISE"),
        ("DATA_ENGINEER", "DATA_ENGINEERING"),   # data-engineers (fixture grant)
        ("DATA_STEWARD", "DATA_ENGINEERING"),
    },
    "bob": {
        ("DATA_STEWARD", "AVIATION"),
    },
    "carol": {
        ("MECHANIC", "AVIATION"),
    },
    "agent-user": {
        ("DATA_ENGINEER", "DATA_ENGINEERING"),   # data-engineers (role grant)
        ("DATA_STEWARD", "DATA_ENGINEERING"),
    },
}

_failures: list[str] = []


def _fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")
    _failures.append(msg)


def _ok(msg: str) -> None:
    print(f"  [PASS] {msg}")


def get_token(username: str) -> str:
    r = requests.post(
        f"{KEYCLOAK_URL}/realms/{REALM}/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": CLIENT_ID,
            "username": username,
            "password": PASSWORDS.get(username, ""),
        },
        timeout=15,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def me_entitlements(token: str) -> dict:
    r = requests.get(
        f"{CORTEX_BFF_URL}/me/entitlements",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def main() -> int:
    print("=== Real-token /me/entitlements integration probe ===")
    for username, expected in EXPECTED.items():
        try:
            token = get_token(username)
        except Exception as e:
            _fail(f"{username}: could not mint token: {e}")
            continue
        try:
            body = me_entitlements(token)
        except Exception as e:
            _fail(f"{username}: /me/entitlements failed: {e}")
            continue

        got = {
            (c.get("persona"), c.get("domain"))
            for c in (body.get("cells") or [])
        }
        # SPECIFIC-set assertion, not non-empty: an identity-keying bug
        # (wrong email) yields an EMPTY set → caught; a cross-wired
        # identity yields the WRONG set → also caught.
        if got == expected:
            _ok(f"{username}: {len(got)} cells match exactly "
                f"(email={body.get('email')}, source={body.get('source')})")
        else:
            missing = expected - got
            extra = got - expected
            _fail(
                f"{username}: cell mismatch. "
                f"email={body.get('email')} source={body.get('source')} "
                f"missing={sorted(missing)} extra={sorted(extra)}"
            )

    print(f"\n=== {len(EXPECTED)} users checked, {len(_failures)} failures ===")
    if _failures:
        print("An identity-keying or entitlement drift is present. "
              "This is the guard that catches the @example.com-vs-@edgy "
              "class of bug at CI time instead of at browser-login time.")
    return 1 if _failures else 0


if __name__ == "__main__":
    sys.exit(main())
