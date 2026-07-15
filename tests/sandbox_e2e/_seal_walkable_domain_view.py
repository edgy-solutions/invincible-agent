"""Walkable domain-view seal (persona de-hardcode, phase 2 discriminator).

Proves catalog_domain_view's decision on the WALKABLE derivation with the
three cases that matter — the third is the reason the work exists:

  1. ENTITLED allows    — alice / DATA_ENGINEERING → authorizer TRUE
                          (the walk carries the allow path).
  2. UNENTITLED denies  — bob + carol / DATA_ENGINEERING → authorizer FALSE
                          (the walk correctly finds nothing — the
                          discriminating pair on the SAME derivation,
                          defeating broken-closed).
  3. NOVEL PERSONA      — FIELD_AUDITOR, a persona the product never
                          shipped, granted through a simulated work
                          overlay. Under the HARDCODED rego this
                          half-works: directory can_assume + can_view
                          (the walk) are TRUE, but the authorizer says
                          FALSE because the enumeration can't construct
                          a cell ID it never heard of. After the phase-2
                          swap the authorizer follows the walk → TRUE.

The SAME script proves both worlds — run it twice around the swap:

    # pre-swap (old rego, hardcoded list): proves the half-works bug
    python tests/sandbox_e2e/_seal_walkable_domain_view.py --expect-novel denied
    # post-swap (walk rego): proves the fix
    python tests/sandbox_e2e/_seal_walkable_domain_view.py --expect-novel allowed

If the pre-swap run can't FAIL-style-demonstrate the denial (or the
post-swap run can't show the allow), the seal exits non-zero — the
verification can fail, per [[verification-must-fail]].

The novel overlay is seeded via the REAL sync (topaz_sync.py on a
composed scratch policy dir — the same code path a work overlay uses)
and reverted the same way (diff-based prune = the rollback). --keep
skips the revert for manual poking.

Requires: kubectl port-forward -n sandbox svc/topaz-svc 9393:9393 8383:8383
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[2]
POLICY = REPO / "policy"
SYNC = POLICY / "sync" / "topaz_sync.py"

DIR_URL = os.getenv("TOPAZ_DIR_URL", "http://localhost:9393")
AUTHZ_URL = os.getenv("TOPAZ_AUTHZ_URL", "http://localhost:8383")

NOVEL_PERSONA = "FIELD_AUDITOR"
NOVEL_USER = "novel@example.com"
NOVEL_GROUP = "novel-auditors"
DOMAIN = "DATA_ENGINEERING"

_failures: list[str] = []


def expect(label: str, actual: bool, expected: bool) -> None:
    ok = actual is expected
    print(f"  [{'OK  ' if ok else 'FAIL'}] {label}: got {actual}, expected {expected}")
    if not ok:
        _failures.append(label)


def authz_can_view(user: str, domain: str) -> bool:
    """The single-decider ASK, byte-compatible with datahub_wrapper's
    _topaz_can_view (IDENTITY_TYPE_MANUAL; subject in resourceContext)."""
    r = httpx.post(
        f"{AUTHZ_URL}/api/v2/authz/is",
        json={
            "identityContext": {"identity": user, "type": "IDENTITY_TYPE_MANUAL"},
            "resourceContext": {"user_id": user, "domain": domain},
            "policyContext": {
                "path": "invincible_agent.catalog.can_view",
                "decisions": ["allowed"],
            },
        },
        timeout=10.0,
    )
    r.raise_for_status()
    for d in r.json().get("decisions", []):
        if d.get("decision") == "allowed":
            return bool(d.get("is", False))
    return False


def dir_check(object_type: str, object_id: str, relation: str, subject_id: str) -> bool:
    r = httpx.post(
        f"{DIR_URL}/api/v3/directory/check",
        json={
            "object_type": object_type,
            "object_id": object_id,
            "relation": relation,
            "subject_type": "user",
            "subject_id": subject_id,
        },
        timeout=10.0,
    )
    r.raise_for_status()
    return bool(r.json().get("check", False))


def run_sync(policy_dir: Path) -> None:
    """Seed via the REAL sync (readback-gated) — the same path an
    overlay uses in production. Non-zero exit aborts the seal."""
    subprocess.run(
        [sys.executable, str(SYNC), "--topaz-url", DIR_URL,
         "--policy-dir", str(policy_dir)],
        check=True,
        stdout=subprocess.DEVNULL,
    )


def compose_novel_overlay(dst: Path) -> None:
    """Simulate a work overlay asserting personas.yaml: the sandbox
    policy + one persona the product never shipped, a group granting
    its (persona, DOMAIN) cell, and a user holding it."""
    shutil.copytree(POLICY, dst, ignore=shutil.ignore_patterns("sync", "workflows", "__pycache__", "README.md"))
    with (dst / "personas.yaml").open("a", encoding="utf-8") as f:
        f.write(f"  - {NOVEL_PERSONA}\n")
    with (dst / "groups.yaml").open("a", encoding="utf-8") as f:
        f.write(
            f"  {NOVEL_GROUP}:\n"
            f"    grants:\n"
            f"      - {{persona: {NOVEL_PERSONA}, domain: {DOMAIN}}}\n"
        )
    with (dst / "users.yaml").open("a", encoding="utf-8") as f:
        f.write(
            f"  - id: {NOVEL_USER}\n"
            f"    display_name: Novel Persona Seal Probe\n"
            f"    groups: [{NOVEL_GROUP}]\n"
        )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--expect-novel",
        choices=["allowed", "denied"],
        required=True,
        help="authorizer verdict expected for the novel persona: "
        "'denied' pre-swap (hardcoded rego — proves the half-works bug), "
        "'allowed' post-swap (walk rego — proves the fix).",
    )
    ap.add_argument("--keep", action="store_true",
                    help="skip the revert (leave the novel overlay seeded)")
    args = ap.parse_args()
    novel_expected = args.expect_novel == "allowed"

    print("=== LEG 1+2: discriminating pair on the standing sandbox grants ===")
    expect(f"ENTITLED   alice can_view {DOMAIN} (authorizer)",
           authz_can_view("alice@example.com", DOMAIN), True)
    expect(f"UNENTITLED bob   can_view {DOMAIN} (authorizer)",
           authz_can_view("bob@example.com", DOMAIN), False)
    expect(f"UNENTITLED carol can_view {DOMAIN} (authorizer)",
           authz_can_view("carol@example.com", DOMAIN), False)

    print(f"\n=== LEG 3: novel persona {NOVEL_PERSONA} via simulated work overlay ===")
    tmp = Path(tempfile.mkdtemp(prefix="novel-overlay-"))
    overlay = tmp / "policy"
    try:
        compose_novel_overlay(overlay)
        run_sync(overlay)
        print(f"  seeded: {NOVEL_USER} -> {NOVEL_GROUP} -> cell:{NOVEL_PERSONA}:{DOMAIN}")

        # Data layer: grant + walk are ALREADY correct regardless of rego.
        expect("  novel can_assume its cell (directory)",
               dir_check("cell", f"{NOVEL_PERSONA}:{DOMAIN}", "can_assume", NOVEL_USER), True)
        expect(f"  novel can_view domain (directory WALK)",
               dir_check("domain", DOMAIN, "can_view", NOVEL_USER), True)

        # Policy layer: THE discriminator between the two worlds.
        expect(f"  novel can_view {DOMAIN} (AUTHORIZER) -- the phase-2 discriminator",
               authz_can_view(NOVEL_USER, DOMAIN), novel_expected)

        if not args.keep:
            print("\n=== REVERT: re-sync the asserted policy (diff-prune = rollback) ===")
            run_sync(POLICY)
            expect("  novel grant pruned (can_assume now false)",
                   dir_check("cell", f"{NOVEL_PERSONA}:{DOMAIN}", "can_assume", NOVEL_USER), False)
            expect("  no collateral: alice still allowed (authorizer)",
                   authz_can_view("alice@example.com", DOMAIN), True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{'SEAL FAILED: ' + ', '.join(_failures) if _failures else 'SEAL OK'}")
    return 1 if _failures else 0


if __name__ == "__main__":
    sys.exit(main())
