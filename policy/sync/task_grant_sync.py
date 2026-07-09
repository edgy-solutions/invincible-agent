"""git-asserted HumanTask AUDIENCES → Topaz directory sync.

WHY THIS EXISTS. The HITL substrate's FIFTH namespace: WHO may ACT on
(approve/reject) a class of human-in-the-loop tasks is deny-by-default,
Topaz-decided, and git-asserted — the SAME model as asset/document/ontology
grants, on a fifth namespace (task audiences). `policy/task_grants.yaml` is the
assertion (git-blame = audit trail); this sync flows it into Topaz as
`task_audience` `actor` relations. The queue's registration then RESOLVES an
audience's actors from Topaz and materializes one queue row per actor, and the
`/act` endpoint re-checks `can_act`; both derive from THIS sync's relations, so
the Electric replication filter and the Topaz gate cannot diverge.

FIVE SYNCS, ONE DIRECTORY, DISJOINT SCOPE (no two prune the same relation):
  - topaz_sync.py                 — persona/cell/group/member/user
  - datahub_topaz_sync.py         — dataset `owner`
  - grant_sync.py                 — dataset `reader`
  - ontology_compartment_sync.py  — ontology_class `viewer` + `restricted`
  - task_grant_sync.py            — task_audience `actor` (THIS)
This tool owns the `task_audience` actor relations; it ensures grantee `user`
objects exist (never pruned — the ADR-0026 sync owns `user`) and PRUNES
task_audience actor relations not asserted in git (removing a grant REVOKES the
ability to act, and — since existence-of-task is deny-by-default — to even SEE it).

PROVE-THE-NEGATIVE ON THE GRANT PATH. An audience is REFUSED (nothing applied,
non-zero exit) when MALFORMED — missing `granted_by` (accountable human),
`reason`, or `grant_to`. An unexplained or targetless audience is not an audience.
A broken overlay does not partially apply.

TESTED CORE = the pure transforms (`load_audiences`, `derive_desired`) — no
network. Readback (each grant resolves can_act TRUE) is the positive control; the
reference-INDEPENDENT proof is the live queue seal (authorized actor receives the
task via Electric + can /act; unauthorized neither).
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from topaz_sync import DirObject, DirRelation, DesiredState  # noqa: E402

# Disjoint prune scope: task_audience actor relations only.
MANAGED_TASK_RELATIONS = [("task_audience", "actor")]


@dataclass(frozen=True)
class AudienceRecord:
    """One git-asserted task audience: the audience key (task_kind:compartment)
    and the entitlement keys (emails) granted to ACT on its tasks. granted_by/
    reason = the audit trail git-blame anchors."""
    key: str
    grant_to: tuple[str, ...]
    granted_by: str
    reason: str = ""


def load_audiences(raw: dict) -> tuple[list[AudienceRecord], list[str]]:
    """PURE: parsed task_grants.yaml → (audiences, errors). prove-the-negative:
    an audience missing granted_by / reason / grant_to is an ERROR (collected,
    not dropped) — a broken overlay refuses whole, never partially applies."""
    errors: list[str] = []
    out: list[AudienceRecord] = []
    for key, entry in ((raw or {}).get("audiences") or {}).items():
        entry = entry or {}
        grant_to = [str(g).strip() for g in (entry.get("grant_to") or []) if str(g).strip()]
        granted_by = str(entry.get("granted_by") or "").strip()
        missing = [
            k for k, v in (("granted_by", granted_by), ("reason", entry.get("reason")),
                           ("grant_to", grant_to))
            if not v
        ]
        if missing:
            errors.append(f"audience[{key}] MALFORMED: missing {', '.join(missing)}")
            continue
        out.append(AudienceRecord(
            key=str(key), grant_to=tuple(grant_to),
            granted_by=granted_by, reason=str(entry.get("reason") or "")))
    return out, errors


def derive_desired(audiences: list[AudienceRecord]) -> DesiredState:
    """PURE: audiences → DesiredState. Per audience, per grantee: a `actor`
    relation. Plus the task_audience + user objects (ensure-present)."""
    state = DesiredState()
    for a in audiences:
        state.objects.add(DirObject("task_audience", a.key))
        for grantee in a.grant_to:
            state.objects.add(DirObject("user", grantee))
            state.relations.add(DirRelation(
                object_type="task_audience", object_id=a.key, relation="actor",
                subject_type="user", subject_id=grantee))
    return state


def snapshot(client) -> DesiredState:
    """This sync's managed live state: task_audience actor relations only."""
    live = DesiredState()
    for obj_type, rel in MANAGED_TASK_RELATIONS:
        live.relations.update(client.list_relations(object_type=obj_type, relation=rel))
    return live


def sync_audiences(client, audiences: list[AudienceRecord], *, prune: bool = True):
    """Ensure task_audience/user objects exist, then diff+apply the managed actor
    relations. prune=True REVOKES actor relations not asserted in git."""
    from topaz_sync import plan_diff, apply_plan
    desired = derive_desired(audiences)
    for o in desired.objects:
        client.set_object(o)  # task_audience + user (ensure; not pruned)
    desired_managed = DesiredState(objects=set(), relations=set(desired.relations))
    live = snapshot(client)
    plan = plan_diff(desired_managed, live.objects, live.relations)
    if not prune:
        plan.del_objects = []
        plan.del_relations = []
    apply_plan(client, plan, {})
    return plan


def readback(client, audiences: list[AudienceRecord]) -> tuple[int, int]:
    """Positive control: every (audience, grantee) must resolve can_act TRUE.
    A missing relation FAILS LOUD (verification-must-be-able-to-fail)."""
    checked = failures = 0
    for a in audiences:
        for grantee in a.grant_to:
            checked += 1
            if not client.check("task_audience", a.key, "can_act", grantee):
                print(f"  [FAIL] {grantee} can_act {a.key}")
                failures += 1
    return checked, failures


def main() -> int:
    """CLI: sync task audiences into Topaz.
    Env: TASK_GRANTS_FILE (default policy/task_grants.yaml), TOPAZ_DIRECTORY_URL.
    Exit: 0 ok · 2 malformed · 4 readback failed."""
    import yaml
    from topaz_sync import TopazClient

    grants_file = os.getenv("TASK_GRANTS_FILE", "policy/task_grants.yaml")
    topaz_url = os.getenv("TOPAZ_DIRECTORY_URL", "http://topaz-svc:9393")

    with open(grants_file) as f:
        raw = yaml.safe_load(f) or {}
    audiences, malformed = load_audiences(raw)
    if malformed:
        print("REFUSED — malformed overlay (fix task_grants.yaml; nothing applied):",
              file=sys.stderr)
        for e in malformed:
            print(f"  {e}", file=sys.stderr)
        return 2
    n_grants = sum(len(a.grant_to) for a in audiences)
    print(f"loaded {len(audiences)} audience(s), {n_grants} actor grant(s)")

    with TopazClient(topaz_url) as client:
        plan = sync_audiences(client, audiences)
        print(f"synced: +{len(plan.add_relations)} relations, -{len(plan.del_relations)} revoked")
        print("===== Readback (positive control — each grant resolves can_act) =====")
        checked, failures = readback(client, audiences)
        print(f"  checked={checked}  failures={failures}")
        if failures > 0:
            print("FAIL: a git-asserted audience grant does not resolve can_act — apply lied.",
                  file=sys.stderr)
            return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
