"""git-asserted per-asset READ grants → Topaz directory sync.

WHY THIS EXISTS. Deny-by-default (the classification governing invariant:
`[[access-regulates-persona-domain]]`) means a subject reads an asset ONLY via
an EXPLICIT, AUDITABLE, per-asset grant. The DA-read gate (`data_broker.rego`)
is sealed and grants `can_read = reader | owner`. Owner relations come from
DataHub (`datahub_topaz_sync.py`). READER grants are the *human decision* —
"this subject may read this asset" — and at TS/SCI/proprietary/PII an
UNAUDITABLE grant is a grant that shouldn't exist. A manual `ds` directory
write has no git-blame, no PR, no named human on record. This module makes the
grant auditable: `policy/asset_grants.yaml` is the assertion, git-blame is the
audit trail, and this sync flows it into Topaz. It is the durable successor to
the manual-directory-write rehearsal (alice→reader→customers_gold).

THREE SYNCS, ONE DIRECTORY, DISJOINT SCOPE (no two prune the same relation):
  - topaz_sync.py         — persona/cell/group/member/user (git entitlements)
  - datahub_topaz_sync.py — dataset `owner` (DataHub resource facts)
  - grant_sync.py (THIS)  — dataset `reader` (git-asserted human grants)
Reader is this tool's alone; it ensures grantee `user` objects exist
(idempotent, never pruned — the ADR-0026 sync owns `user`) and it PRUNES reader
relations not asserted in git (removing a grant from the file REVOKES it — the
deny-by-default direction).

PROVE-THE-NEGATIVE ON THE GRANT PATH (the grant mechanism CREATES access, so a
bug that grants too broadly is a spill-generator — it gets the same fail-closed
discipline as the gate). A grant is REFUSED, not silently applied, when it is:
  - MALFORMED (missing subject / asset / granted_by) — the accountable-human
    field is REQUIRED; an anonymous grant is not a grant.
  - DANGLING (asset not present in the directory) — you cannot grant read on an
    asset that isn't there (deny-on-dangling, ADR-0025's orphan-scrub seam).
Any error → the sync applies NOTHING and exits non-zero, naming the offenders.
A malformed/dangling grant file does not partially apply.

TESTED CORE = the pure transforms (`load_grants`, `derive_grant_desired`) — no
network. The driver (validate-against-live, diff, apply, readback) is the I/O
shell; the allow-side-through-the-sealed-gate proof is an integration probe.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass

# Reuse the directory primitives verbatim (same object/relation/desired-state
# vocabulary as the other two syncs — one definition).
from topaz_sync import DirObject, DirRelation, DesiredState  # noqa: E402


# THIS sync's prune scope: dataset `reader` relations only. Excludes `user`
# (ensured-present, never pruned — ADR-0026 sync owns it) and `owner` (DataHub
# sync owns it). Disjoint from the other two tools' managed sets.
MANAGED_GRANT_OBJECT_TYPES: list[str] = []          # owns no object type outright
MANAGED_GRANT_RELATIONS = [("dataset", "reader")]


@dataclass(frozen=True)
class GrantRecord:
    """One git-asserted read grant: <subject> may READ <asset>, asserted by a
    named human with a reason. subject = entitlement key (email); asset =
    dataset URN (the Topaz object id); granted_by/reason = the audit trail
    that git-blame anchors."""
    subject: str
    asset: str
    granted_by: str
    reason: str = ""


def load_grants(raw: dict) -> tuple[list[GrantRecord], list[str]]:
    """PURE: a parsed asset_grants.yaml dict → (valid grants, errors).

    prove-the-negative: an entry missing subject / asset / granted_by is an
    ERROR (collected, not silently dropped) — the accountable-human field is
    required, so an anonymous or targetless grant is refused. Returns errors so
    the caller can refuse the whole apply if any exist (fail-closed: a broken
    grant file does not partially apply)."""
    grants: list[GrantRecord] = []
    errors: list[str] = []
    for i, entry in enumerate((raw or {}).get("grants") or []):
        subject = (entry or {}).get("subject") or ""
        asset = (entry or {}).get("asset") or ""
        granted_by = (entry or {}).get("granted_by") or ""
        missing = [
            k for k, v in (("subject", subject), ("asset", asset), ("granted_by", granted_by))
            if not str(v).strip()
        ]
        if missing:
            errors.append(f"grant[{i}] MALFORMED: missing {', '.join(missing)} — {entry!r}")
            continue
        grants.append(GrantRecord(subject=subject, asset=asset, granted_by=granted_by,
                                  reason=(entry or {}).get("reason") or ""))
    return grants, errors


def derive_grant_desired(grants: list[GrantRecord]) -> DesiredState:
    """PURE: valid grants → the DesiredState this sync seeds. One `reader`
    relation `dataset:<asset>#reader@user:<subject>` per grant, plus the
    grantee `user` object (ENSURE-present, never pruned here). Mirrors
    derive_asset_desired; the relation is `reader` (human grant) not `owner`
    (DataHub fact)."""
    state = DesiredState()
    for g in grants:
        state.objects.add(DirObject("user", g.subject))
        state.relations.add(
            DirRelation(
                object_type="dataset",
                object_id=g.asset,
                relation="reader",
                subject_type="user",
                subject_id=g.subject,
            )
        )
    return state


def find_dangling(client, grants: list[GrantRecord]) -> list[str]:
    """prove-the-negative (deny-on-dangling): a grant whose ASSET is not a
    `dataset` object in the directory is REFUSED — you cannot grant read on an
    asset that isn't there. Returns the offending grant descriptions. The live
    dataset object set is the reference (seeded by datahub_topaz_sync)."""
    live_datasets = {o.id for o in client.list_objects("dataset")}
    dangling: list[str] = []
    for g in grants:
        if g.asset not in live_datasets:
            dangling.append(
                f"DANGLING: {g.subject} → reader on {g.asset} (asset not in directory; "
                f"granted_by={g.granted_by})"
            )
    return dangling


def snapshot_grants(client) -> DesiredState:
    """This sync's managed live state: dataset `reader` relations ONLY.
    Excludes `user` (ensure-not-prune) and `owner` (other sync's). The
    exclusion is what makes plan_diff never emit a user or owner deletion."""
    live = DesiredState()
    for obj_type, rel in MANAGED_GRANT_RELATIONS:
        live.relations.update(client.list_relations(object_type=obj_type, relation=rel))
    return live


def sync_grants(client, grants: list[GrantRecord], *, prune: bool = True):
    """Apply git-asserted reader grants. Ensures grantee `user` objects exist
    (idempotent, NEVER pruned), then diffs+applies the managed `reader`
    relations. With prune=True, reader relations NOT in git are REVOKED (git is
    the source of truth for grants). Returns the applied Plan."""
    from topaz_sync import plan_diff, apply_plan

    desired = derive_grant_desired(grants)

    # Ensure grantee users exist (the reader relation's subject). Never pruned.
    for u in {o for o in desired.objects if o.type == "user"}:
        client.set_object(u)

    # Managed diff over reader relations only (no objects managed here — the
    # dataset objects belong to the DataHub sync; users to the ADR-0026 sync).
    desired_managed = DesiredState(objects=set(), relations=set(desired.relations))
    live = snapshot_grants(client)
    plan = plan_diff(desired_managed, live.objects, live.relations)
    if not prune:
        plan.del_objects = []
        plan.del_relations = []
    apply_plan(client, plan, {})
    return plan


def readback_grants(client, grants: list[GrantRecord]) -> tuple[int, int]:
    """Positive control: every git-asserted grant must resolve `can_read` TRUE
    through the sealed gate's permission (`reader | owner`). A missing relation
    FAILS LOUD (`[[verification-must-fail]]`). This is the sync's OWN reference
    (the relations it wrote resolve — catches an inert apply); the reference-
    INDEPENDENT proof (a real token through central_gateway → data_broker) is
    the composed-path seal (`[[composed-path-seal]]`)."""
    checked = failures = 0
    for g in grants:
        checked += 1
        if not client.check("dataset", g.asset, "can_read", g.subject):
            print(f"  [FAIL] {g.subject} can_read {g.asset}")
            failures += 1
    return checked, failures


def main() -> int:
    """CLI: sync git-asserted reader grants into Topaz.
    Env: ASSET_GRANTS_FILE (default policy/asset_grants.yaml), TOPAZ_DIRECTORY_URL.
    Exit: 0 ok · 2 malformed grants · 3 dangling grants · 4 readback failed.
    Malformed/dangling → apply NOTHING (fail-closed: a broken grant file does
    not partially apply)."""
    import yaml
    from topaz_sync import TopazClient

    grants_file = os.getenv("ASSET_GRANTS_FILE", "policy/asset_grants.yaml")
    topaz_url = os.getenv("TOPAZ_DIRECTORY_URL", "http://topaz-svc:9393")

    with open(grants_file) as f:
        raw = yaml.safe_load(f) or {}
    grants, malformed = load_grants(raw)
    if malformed:
        print("REFUSED — malformed grants (fix policy/asset_grants.yaml; nothing applied):",
              file=sys.stderr)
        for e in malformed:
            print(f"  {e}", file=sys.stderr)
        return 2
    print(f"loaded {len(grants)} well-formed grant(s)")

    with TopazClient(topaz_url) as client:
        dangling = find_dangling(client, grants)
        if dangling:
            print("REFUSED — dangling grants (asset not in directory; nothing applied):",
                  file=sys.stderr)
            for d in dangling:
                print(f"  {d}", file=sys.stderr)
            return 3

        plan = sync_grants(client, grants)
        print(f"synced: +{len(plan.add_relations)} reader grants, "
              f"-{len(plan.del_relations)} revoked")

        print("===== Readback (positive control — each grant resolves can_read) =====")
        checked, failures = readback_grants(client, grants)
        print(f"  checked={checked}  failures={failures}")
        if failures > 0:
            print("FAIL: a git-asserted grant does not resolve can_read — the apply lied.",
                  file=sys.stderr)
            return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
