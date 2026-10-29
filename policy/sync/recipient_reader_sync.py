"""git-asserted RECIPIENT READER grants -> Topaz directory sync.

WHY THIS EXISTS. Two engines hold a code table of who may download a recipient's disclosure
package (finance_agent/export.py and cost_agent/seed.py, each `RECIPIENT_READERS`). Architect,
2026-10-27 ruling 4 (refined 2026-10-28): the tables move onto the policy rail as the
`recipient_readers` family; each owning lane moves its own rows. Every consumer is a membership
check ("is this caller a reader of this scope?"), which is exactly a Topaz `reader` relation
(deny-by-default, git-asserted) on a `recipient_scope` object.

THE OBJECT ID IS `<owner>:<scope>`. The OWNER (a closed set, `finance` | `cost`) is part of the
id because the two engines' disclosures are entitled independently: a reader of one engine's
scope is never a reader of the other's, even when the scope string collides.

EIGHT SYNCS, ONE DIRECTORY, DISJOINT SCOPE (no two prune the same relation):
  - topaz_sync.py                 -- persona/cell/group/member/user
  - datahub_topaz_sync.py         -- dataset `owner`
  - grant_sync.py                 -- dataset `reader`
  - ontology_compartment_sync.py  -- ontology_class `viewer` + `restricted`
  - task_grant_sync.py            -- task_audience `actor`
  - capability_grant_sync.py      -- capability `invoker`
  - program_member_sync.py        -- program `member`
  - recipient_reader_sync.py      -- recipient_scope `reader` (THIS)
(`recipient_scope` `reader` is a different object type from dataset `reader`, so the scopes
are disjoint.) This tool owns the `recipient_scope` `reader` relations; it ensures grantee
`user` objects exist (never pruned -- the ADR-0026 sync owns `user`) and PRUNES reader
relations not asserted in git (removing a row REVOKES can_read_recipient).

PROVE-THE-NEGATIVE ON THE GRANT PATH, same discipline as program_member_sync.py: a row is
REFUSED (nothing applied, non-zero exit) when MALFORMED -- missing `granted_by` (accountable
human), `reason`, or `grant_to`; an owner outside {finance, cost}; an owner block or row that
is not a mapping; or a `svc:` grantee (ADR-0047 section 5.1: a disclosure to a service identity
entitles every caller it serves).

TESTED CORE = the pure transforms (`load_readers`, `derive_desired`) -- no network.
Readback (each grant resolves can_read_recipient TRUE) is the positive control.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from topaz_sync import DirObject, DirRelation, DesiredState  # noqa: E402

# The Topaz manifest names these (helm/.../topaz-configmap.yaml `recipient_scope`) and the
# engine-side check (agent_fleet/utils/recipient_readers.py) asks the permission; the seal
# joins all three on these constants.
OBJECT_TYPE = "recipient_scope"
RELATION = "reader"
PERMISSION = "can_read_recipient"

# Disjoint prune scope: recipient_scope reader relations only.
MANAGED_RECIPIENT_RELATIONS = [(OBJECT_TYPE, RELATION)]

# CLOSED set: the engines that own a recipient scope.
OWNERS = frozenset({"finance", "cost"})


@dataclass(frozen=True)
class ReaderRecord:
    """One git-asserted recipient scope: its owner, the scope string, and the entitlement keys
    (emails) granted READ. granted_by/reason = the audit trail git-blame anchors."""
    owner: str
    scope: str
    grant_to: tuple[str, ...]
    granted_by: str
    reason: str = ""

    @property
    def object_id(self) -> str:
        return f"{self.owner}:{self.scope}"


def load_readers(raw: dict) -> tuple[list[ReaderRecord], list[str]]:
    """PURE: parsed recipient_readers.yaml -> (rows, errors). prove-the-negative: a row that is
    malformed is DROPPED and an error naming the field is collected -- a broken overlay refuses
    whole, never partially applies."""
    errors: list[str] = []
    out: list[ReaderRecord] = []
    top = (raw or {}).get("recipient_readers") or {}
    if not isinstance(top, dict):
        return out, ["recipient_readers MALFORMED: top level is not a mapping of owner -> scopes"]
    for owner, block in top.items():
        if owner not in OWNERS:
            errors.append(f"recipient_readers[{owner}] MALFORMED: owner is not one of "
                          f"{sorted(OWNERS)}")
            continue
        if block is None:
            block = {}
        if not isinstance(block, dict):
            errors.append(f"recipient_readers[{owner}] MALFORMED: owner block is not a mapping")
            continue
        for scope, entry in block.items():
            label = f"recipient_readers[{owner}][{scope}]"
            if not isinstance(entry, dict):
                errors.append(f"{label} MALFORMED: row is not a mapping")
                continue
            gt_raw = entry.get("grant_to")
            if not isinstance(gt_raw, list):
                errors.append(f"{label} MALFORMED: grant_to is missing or not a list")
                continue
            grant_to = [str(g).strip() for g in gt_raw if str(g).strip()]
            granted_by = str(entry.get("granted_by") or "").strip()
            reason = str(entry.get("reason") or "").strip()
            missing = [k for k, v in (("granted_by", granted_by), ("reason", reason),
                                      ("grant_to", grant_to)) if not v]
            if missing:
                errors.append(f"{label} MALFORMED: missing {', '.join(missing)}")
                continue
            svc = [g for g in grant_to if g.lower().startswith("svc:")]
            if svc:
                errors.append(f"{label} MALFORMED: grant_to names a service identity "
                              f"({', '.join(svc)}) -- ADR-0047 section 5.1: a disclosure to a "
                              f"service identity entitles every caller it serves")
                continue
            out.append(ReaderRecord(owner=str(owner), scope=str(scope),
                                    grant_to=tuple(grant_to), granted_by=granted_by,
                                    reason=reason))
    return out, errors


def derive_desired(rows: list[ReaderRecord]) -> DesiredState:
    """PURE: rows -> DesiredState. Per row, per grantee: a `reader` relation on the
    `<owner>:<scope>` object. Plus the recipient_scope + user objects (ensure-present)."""
    state = DesiredState()
    for r in rows:
        state.objects.add(DirObject(OBJECT_TYPE, r.object_id))
        for grantee in r.grant_to:
            state.objects.add(DirObject("user", grantee))
            state.relations.add(DirRelation(
                object_type=OBJECT_TYPE, object_id=r.object_id, relation=RELATION,
                subject_type="user", subject_id=grantee))
    return state


def snapshot(client) -> DesiredState:
    """This sync's managed live state: recipient_scope reader relations only."""
    live = DesiredState()
    for obj_type, rel in MANAGED_RECIPIENT_RELATIONS:
        live.relations.update(client.list_relations(object_type=obj_type, relation=rel))
    return live


def sync_readers(client, rows: list[ReaderRecord], *, prune: bool = True):
    """Ensure recipient_scope/user objects exist, then diff+apply the managed reader
    relations. prune=True REVOKES reader relations not asserted in git."""
    from topaz_sync import plan_diff, apply_plan
    desired = derive_desired(rows)
    for o in desired.objects:
        client.set_object(o)  # recipient_scope + user (ensure; not pruned)
    desired_managed = DesiredState(objects=set(), relations=set(desired.relations))
    live = snapshot(client)
    plan = plan_diff(desired_managed, live.objects, live.relations)
    if not prune:
        plan.del_objects = []
        plan.del_relations = []
    apply_plan(client, plan, {})
    return plan


def readback(client, rows: list[ReaderRecord]) -> tuple[int, int]:
    """Positive control: every (owner:scope, grantee) must resolve can_read_recipient TRUE.
    A missing relation FAILS LOUD (verification-must-be-able-to-fail)."""
    checked = failures = 0
    for r in rows:
        for grantee in r.grant_to:
            checked += 1
            if not client.check(OBJECT_TYPE, r.object_id, PERMISSION, grantee):
                print(f"  [FAIL] {grantee} {PERMISSION} {r.object_id}")
                failures += 1
    return checked, failures


def main() -> int:
    """CLI: sync recipient reader grants into Topaz.
    Env: RECIPIENT_READERS_FILE (default policy/recipient_readers.yaml),
    TOPAZ_DIRECTORY_URL. Exit: 0 ok · 2 malformed · 4 readback failed."""
    import yaml
    from topaz_sync import TopazClient

    grants_file = os.getenv("RECIPIENT_READERS_FILE", "policy/recipient_readers.yaml")
    topaz_url = os.getenv("TOPAZ_DIRECTORY_URL", "http://topaz-svc:9393")

    with open(grants_file) as f:
        raw = yaml.safe_load(f) or {}
    rows, malformed = load_readers(raw)
    if malformed:
        print("REFUSED -- malformed overlay (fix recipient_readers.yaml; nothing applied):",
              file=sys.stderr)
        for e in malformed:
            print(f"  {e}", file=sys.stderr)
        return 2
    n_grants = sum(len(r.grant_to) for r in rows)
    print(f"loaded {len(rows)} recipient scope(s), {n_grants} reader grant(s)")

    with TopazClient(topaz_url) as client:
        plan = sync_readers(client, rows)
        print(f"synced: +{len(plan.add_relations)} relations, -{len(plan.del_relations)} revoked")
        print("===== Readback (positive control -- each grant resolves can_read_recipient) =====")
        checked, failures = readback(client, rows)
        print(f"  checked={checked}  failures={failures}")
        if failures > 0:
            print("FAIL: a git-asserted recipient reader grant does not resolve "
                  "can_read_recipient -- apply lied.", file=sys.stderr)
            return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
