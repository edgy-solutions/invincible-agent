#!/usr/bin/env python3
"""Network-free validation of ALL SIX git-asserted policy files.

WHY THIS EXISTS. The six syncs each validate their own file — but only
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

ENUMS SPLIT (`--enums-from` / `--overlay-enums`). personas.yaml /
domains.yaml come from the product image by default, but a deployment
may ASSERT ownership of either (mirrors the chart's
`topazSeed.policySource.overlayEnums`): domains.yaml is a deployment's
classification vocabulary (labels must match its data tagging at
ingest); personas.yaml is fully assertable since chart 0.3.12 — the
catalog rego walks the directory (domain.can_view) instead of
enumerating a hardcoded persona list, so ADDING personas via overlay
works too. An enum file present in --policy-dir but NOT asserted is an
ERROR — an ignored-but-authoritative-looking file is the two-truths
trap.

    # inside the product image (work policy repo mounted at /overlay):
    python policy/sync/validate_policy.py \\
        --policy-dir /overlay --enums-from /app/policy \\
        --overlay-enums domains.yaml

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
from capability_grant_sync import load_capabilities

# The six DATA files a deployment asserts (enums excluded — product-owned).
DATA_FILES = (
    "users.yaml",
    "groups.yaml",
    "asset_grants.yaml",
    "task_grants.yaml",
    "ontology_compartments.yaml",
    "capability_grants.yaml",
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


def unknown_user_subjects(file_label: str, pairs, known_users: set[str]) -> list[str]:
    """AUTHOR-BUG GATE (validators catch author bugs; readbacks catch sync bugs —
    neither substitutes for the other). EVERY grant sync (asset/task/ontology/
    capability) writes ``user`` subjects UNCONDITIONALLY, so a grantee that isn't a
    KNOWN user seeds a phantom ``user:<name>`` object — a grant that PASSES readback
    (the relation exists) while granting nothing to any real principal (silent-wrong-
    grant, the grant-side of broken-closed). This refuses it LOUD at validation, the
    same posture as the overlay-enum guards. Group grants are a DEFERRED design
    decision (they split "who has access" across git + group membership, which drifts
    without a grant-file change — a real weakening of the git-blame audit story that
    needs its own ruling; plus ``user | group#member`` in the manifest + sync support).
    Until then, USERS ONLY family-wide.

    PURE — no filesystem. ``pairs`` = ``[(context, grantee), ...]``. Returns one
    ``<file_label>: ...`` error per grantee not in ``known_users`` (empty when all
    resolve)."""
    out: list[str] = []
    for context, grantee in pairs:
        if grantee not in known_users:
            out.append(
                f"{file_label}: grant subject {grantee!r} (for {context!r}) is NOT a "
                f"known user (not in users.yaml) — group grants are not supported (the "
                f"sync writes `user` subjects; a group name seeds a phantom "
                f"user:{grantee} that passes readback while granting nothing to the "
                f"group's members). Add the user to users.yaml or fix the entry."
            )
    return out


def validate(
    policy_dir: Path,
    enums_dir: Path,
    overlay_enums: list[str] | None = None,
) -> list[str]:
    """PURE (filesystem-only): validate all six data files against the
    enums. `overlay_enums` names the enum files the OVERLAY asserts
    (read from policy_dir instead of enums_dir). Returns the full error
    list — empty means valid."""
    errors: list[str] = []
    overlay_enums = overlay_enums or []

    def _enum_source(name: str) -> Path:
        return policy_dir if name in overlay_enums else enums_dir

    # Two-truths guard (only meaningful when the dirs differ): an enum
    # file sitting in the overlay WITHOUT being asserted would look
    # authoritative while being ignored — refuse it.
    if policy_dir != enums_dir:
        for name in ("personas.yaml", "domains.yaml"):
            if name not in overlay_enums and (policy_dir / name).is_file():
                errors.append(
                    f"{name}: present in the overlay but NOT asserted via "
                    f"--overlay-enums — an ignored-but-authoritative-looking "
                    f"enum is the two-truths trap; assert it or delete it"
                )

    personas = _read_yaml(_enum_source("personas.yaml") / "personas.yaml", errors).get("personas", [])
    domains = _read_yaml(_enum_source("domains.yaml") / "domains.yaml", errors).get("domains", [])

    users_raw = _read_yaml(policy_dir / "users.yaml", errors)
    groups_raw = _read_yaml(policy_dir / "groups.yaml", errors)
    grants_raw = _read_yaml(policy_dir / "asset_grants.yaml", errors)
    tasks_raw = _read_yaml(policy_dir / "task_grants.yaml", errors)
    comps_raw = _read_yaml(policy_dir / "ontology_compartments.yaml", errors)
    caps_raw = _read_yaml(policy_dir / "capability_grants.yaml", errors)

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

    caps, cap_errors = load_capabilities(caps_raw)
    errors.extend(f"capability_grants.yaml: {e}" for e in cap_errors)
    print(f"  capability_grants.yaml: {len(caps)} capability(ies)")

    # ADMISSION POSTURE (ADR-0034). Validated through the SAME parser the runtime loads with, so
    # there is ONE definition of a well-formed table and this gate cannot drift from the loader.
    # Added when the table acquired a production reader (phase 1.3) — before that it was a git
    # artifact nothing consumed, and a validator for it would have guarded nothing.
    #
    # OPTIONAL BY DESIGN: a deployment with no trust table expresses no admission policy and
    # supervises everything, which is the born-default, not an error.
    trust_path = policy_dir / "trust_table.yaml"
    if trust_path.exists():
        trust_raw = _read_yaml(trust_path, errors)
        try:
            import sys as _sys
            _root = Path(__file__).resolve().parents[2]
            if str(_root) not in _sys.path:
                _sys.path.insert(0, str(_root))
            from agent_fleet.utils.trust_table import parse_trust_table  # noqa: PLC0415
            parse_trust_table(trust_raw, ref="validate")
            fmts = trust_raw.get("formats") or {}
            n_promoted = sum(1 for e in fmts.values()
                             if isinstance(e, dict) and e.get("rung") not in (None, "supervised"))
            print(f"  trust_table.yaml: {len(fmts)} format(s), {n_promoted} above supervised")
        except Exception as exc:  # noqa: BLE001 — a malformed table REFUSES, never warns
            errors.append(f"trust_table.yaml: {exc}")

    # AUTHOR-BUG GATE, family-wide. ALL FOUR grant syncs write `user` subjects
    # UNCONDITIONALLY, so a grantee that isn't a known user seeds a phantom
    # `user:<name>` that PASSES readback while granting nothing (silent-wrong-grant).
    # On task_grants this is the sharpest: an approval task routed to NOBODY while the
    # file says it's covered — a workflow suspends awaiting an approver who cannot
    # exist. Refuse it LOUD here. Group grants are a DEFERRED design decision (needs a
    # membership-drift audit ruling + manifest `user | group#member` + sync support);
    # until then, USERS ONLY across the family.
    known_users = {
        str(u.get("id", "")).strip()
        for u in users_raw.get("users", []) if isinstance(u, dict)
    }
    known_users.discard("")
    if known_users:  # skip if users.yaml didn't parse (that's already an error above)
        errors.extend(unknown_user_subjects("asset_grants.yaml",
            [(g.asset, g.subject) for g in grants], known_users))
        errors.extend(unknown_user_subjects("task_grants.yaml",
            [(a.key, gt) for a in audiences for gt in a.grant_to], known_users))
        errors.extend(unknown_user_subjects("ontology_compartments.yaml",
            [(comp.name, gt) for comp in comps for gt in comp.grant_to], known_users))
        errors.extend(unknown_user_subjects("capability_grants.yaml",
            [(c.key, gt) for c in caps for gt in c.grant_to], known_users))

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate all six policy data files (no network).",
    )
    parser.add_argument(
        "--policy-dir",
        default="policy",
        help="Directory holding the six DATA files (default: %(default)s).",
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
    parser.add_argument(
        "--overlay-enums",
        action="append",
        default=[],
        choices=["personas.yaml", "domains.yaml"],
        metavar="FILE",
        help=(
            "Enum file the OVERLAY asserts (repeatable) — read from "
            "--policy-dir instead of --enums-from. Mirrors the chart's "
            "topazSeed.policySource.overlayEnums. Both enums are fully "
            "assertable (personas since chart 0.3.12 — the catalog rego "
            "walks the directory, no hardcoded list)."
        ),
    )
    args = parser.parse_args()

    policy_dir = Path(args.policy_dir).resolve()
    enums_dir = Path(args.enums_from).resolve() if args.enums_from else policy_dir
    print(f"===== Validate policy data from {policy_dir} "
          f"(enums from {enums_dir}"
          f"{'; overlay-asserted: ' + ', '.join(args.overlay_enums) if args.overlay_enums else ''}) =====")

    errors = validate(policy_dir, enums_dir, args.overlay_enums)
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
