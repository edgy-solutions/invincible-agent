#!/usr/bin/env python3
"""Network-free validation of ALL FIVE git-asserted policy files.

WHY THIS EXISTS. The five syncs each validate their own file — but only
at apply time, one sync at a time. topaz_sync failing stops the seed
chain, yet a malformed task_grants.yaml would only surface AFTER four
other syncs had already applied. This tool front-loads every pure
(no-network) validation so a broken overlay is refused BEFORE any write
— in the seed job as a fail-fast gate, and in a private policy repo's
PR CI where no cluster is reachable at all.

WHAT IT CHECKS (all of it reusing the syncs' own loaders — one
definition of "valid", never a parallel re-implementation):
  - personas/domains/groups/users → topaz_sync's PolicyBundle
    (Pydantic + cross-reference validation)
  - asset_grants.yaml             → grant_sync.load_grants
  - task_grants.yaml              → task_grant_sync.load_audiences
  - ontology_compartments.yaml    → ontology_compartment_sync.load_compartments
  - every DATA file must EXIST — explicit-empty (`grants: []`) is a
    valid assertion; an absent file is not. In overlay deployments a
    missing file must never fall back to the image's sandbox copy.

WHAT IT CANNOT CHECK (stays with the live syncs): dangling-asset grants
(needs the directory's dataset objects — grant_sync's deny-on-dangling)
and every readback. This gate is necessary, not sufficient.

ENUMS SPLIT (`--enums-from`). personas.yaml / domains.yaml are canonical
product vocabulary (ADR-0009) — they version with the product image, not
with a deployment's policy repo. An overlay repo holds only the five
data files and validates against the product's enums:

    # inside the product image (work policy repo mounted at /overlay):
    python policy/sync/validate_policy.py \\
        --policy-dir /overlay --enums-from /app/policy

Exit: 0 valid · 2 any error (all errors listed, none silently dropped).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml
from pydantic import ValidationError

from topaz_sync import PolicyBundle
from grant_sync import load_grants
from task_grant_sync import load_audiences
from ontology_compartment_sync import load_compartments

# The five DATA files a deployment asserts (enums excluded — product-owned).
DATA_FILES = (
    "users.yaml",
    "groups.yaml",
    "asset_grants.yaml",
    "task_grants.yaml",
    "ontology_compartments.yaml",
)


def _read_yaml(path: Path, errors: list[str]) -> dict:
    """Parse one YAML file to a top-level mapping; any failure is an
    ERROR (collected, not raised) so the caller reports everything at
    once instead of dying on the first bad file."""
    if not path.is_file():
        errors.append(f"{path.name}: MISSING — every data file must exist "
                      f"(explicit-empty is fine; absent is not)")
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        errors.append(f"{path.name}: YAML parse error — {e}")
        return {}
    if not isinstance(data, dict):
        errors.append(f"{path.name}: top-level YAML must be a mapping")
        return {}
    return data


def validate(policy_dir: Path, enums_dir: Path) -> list[str]:
    """PURE (filesystem-only): validate all five data files against the
    enums. Returns the full error list — empty means valid."""
    errors: list[str] = []

    personas = _read_yaml(enums_dir / "personas.yaml", errors).get("personas", [])
    domains = _read_yaml(enums_dir / "domains.yaml", errors).get("domains", [])

    users_raw = _read_yaml(policy_dir / "users.yaml", errors)
    groups_raw = _read_yaml(policy_dir / "groups.yaml", errors)
    grants_raw = _read_yaml(policy_dir / "asset_grants.yaml", errors)
    tasks_raw = _read_yaml(policy_dir / "task_grants.yaml", errors)
    comps_raw = _read_yaml(policy_dir / "ontology_compartments.yaml", errors)

    # Entitlement matrix — the PolicyBundle cross-validation is the
    # same one topaz_sync runs before any write.
    try:
        bundle = PolicyBundle(
            personas=personas,
            domains=domains,
            groups=groups_raw.get("groups", {}),
            users=users_raw.get("users", []),
        )
        print(f"  users.yaml/groups.yaml: personas={len(bundle.personas)} "
              f"domains={len(bundle.domains)} groups={len(bundle.groups)} "
              f"users={len(bundle.users)}")
    except (ValidationError, ValueError) as e:
        errors.append(f"users.yaml/groups.yaml: {e}")

    grants, grant_errors = load_grants(grants_raw)
    errors.extend(f"asset_grants.yaml: {e}" for e in grant_errors)
    print(f"  asset_grants.yaml: {len(grants)} grant(s)")

    audiences, audience_errors = load_audiences(tasks_raw)
    errors.extend(f"task_grants.yaml: {e}" for e in audience_errors)
    print(f"  task_grants.yaml: {len(audiences)} audience(s)")

    comps, comp_errors, default_visibility = load_compartments(comps_raw)
    errors.extend(f"ontology_compartments.yaml: {e}" for e in comp_errors)
    print(f"  ontology_compartments.yaml: {len(comps)} compartment(s), "
          f"default_visibility={default_visibility}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate all five policy data files (no network).",
    )
    parser.add_argument(
        "--policy-dir",
        default="policy",
        help="Directory holding the five DATA files (default: %(default)s).",
    )
    parser.add_argument(
        "--enums-from",
        default=None,
        help=(
            "Directory holding personas.yaml/domains.yaml (default: same "
            "as --policy-dir). Overlay repos validate their data files "
            "against the PRODUCT's enums: --enums-from /app/policy."
        ),
    )
    args = parser.parse_args()

    policy_dir = Path(args.policy_dir).resolve()
    enums_dir = Path(args.enums_from).resolve() if args.enums_from else policy_dir
    print(f"===== Validate policy data from {policy_dir} "
          f"(enums from {enums_dir}) =====")

    errors = validate(policy_dir, enums_dir)
    if errors:
        print(f"REFUSED — {len(errors)} error(s); nothing should be applied:",
              file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        return 2

    print("===== VALIDATION OK =====")
    return 0


if __name__ == "__main__":
    sys.exit(main())
