"""git-asserted PROGRAM membership grants -> Topaz directory sync.

WHY THIS EXISTS. The origin-entitlement ruling (architect, 2026-10-02: "ORIGIN, not
audience") gives an artifact a recorded `origin = {owner_domain, program}`. A viewer
may read it iff their domain role can_consume `origin.owner_domain`
(`policy/domain_consumption.yaml`, evaluated in-process by `src/iagent/origin.py` —
no Topaz object for THAT half) AND they are a `program` `member` of `origin.program`
(THIS half, Topaz-decided, git-asserted, deny-by-default — the SAME model as the
other six namespaces, on a SEVENTH).

SEVEN SYNCS, ONE DIRECTORY, DISJOINT SCOPE (no two prune the same relation):
  - topaz_sync.py                 — persona/cell/group/member/user
  - datahub_topaz_sync.py         — dataset `owner`
  - grant_sync.py                 — dataset `reader`
  - ontology_compartment_sync.py  — ontology_class `viewer` + `restricted`
  - task_grant_sync.py            — task_audience `actor`
  - capability_grant_sync.py      — capability `invoker`
  - program_member_sync.py        — program `member` (THIS)
This tool owns the `program` `member` relations; it ensures grantee `user` objects
exist (never pruned — the ADR-0026 sync owns `user`) and PRUNES program member
relations not asserted in git (removing a grant REVOKES can_view_program — an
artifact whose origin names that program, even one the viewer could otherwise
can_consume, becomes unreadable through this path for the removed grantee).

PROVE-THE-NEGATIVE ON THE GRANT PATH, same discipline as capability_grant_sync.py: a
program is REFUSED (nothing applied, non-zero exit) when MALFORMED — missing
`granted_by` (accountable human), `reason`, or `grant_to`. An unexplained or
targetless program grant is not a grant.

PROGRAM MEMBERSHIP IS DISCLOSURE, NOT AN EFFECT. Unlike capability `invoker`
(gates an INVOKE, a mutation), `program` `member` gates a READ — closer in kind to
`task_audience` `actor` or `ontology_class` `viewer`. ADR-0047 §5.1: a `svc:`
principal must never be a program member (validate_policy.py's
`service_identity_recipients` check covers this file).

TESTED CORE = the pure transforms (`load_programs`, `derive_desired`) — no network.
Readback (each grant resolves can_view_program TRUE) is the positive control.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from topaz_sync import DirObject, DirRelation, DesiredState  # noqa: E402

# Disjoint prune scope: program member relations only.
MANAGED_PROGRAM_RELATIONS = [("program", "member")]


@dataclass(frozen=True)
class ProgramRecord:
    """One git-asserted program: the program key (the Topaz `program` object_id) and
    the entitlement keys (emails) granted MEMBERSHIP. granted_by/reason = the audit
    trail git-blame anchors."""
    key: str
    grant_to: tuple[str, ...]
    granted_by: str
    reason: str = ""


def load_programs(raw: dict) -> tuple[list[ProgramRecord], list[str]]:
    """PURE: parsed program_members.yaml -> (programs, errors). prove-the-negative:
    a program missing granted_by / reason / grant_to is an ERROR (collected, not
    dropped) — a broken overlay refuses whole, never partially applies."""
    errors: list[str] = []
    out: list[ProgramRecord] = []
    for key, entry in ((raw or {}).get("programs") or {}).items():
        entry = entry or {}
        grant_to = [str(g).strip() for g in (entry.get("grant_to") or []) if str(g).strip()]
        granted_by = str(entry.get("granted_by") or "").strip()
        missing = [
            k for k, v in (("granted_by", granted_by), ("reason", entry.get("reason")),
                           ("grant_to", grant_to))
            if not v
        ]
        if missing:
            errors.append(f"program[{key}] MALFORMED: missing {', '.join(missing)}")
            continue
        out.append(ProgramRecord(
            key=str(key), grant_to=tuple(grant_to),
            granted_by=granted_by, reason=str(entry.get("reason") or "")))
    return out, errors


def derive_desired(programs: list[ProgramRecord]) -> DesiredState:
    """PURE: programs -> DesiredState. Per program, per grantee: a `member` relation.
    Plus the program + user objects (ensure-present)."""
    state = DesiredState()
    for p in programs:
        state.objects.add(DirObject("program", p.key))
        for grantee in p.grant_to:
            state.objects.add(DirObject("user", grantee))
            state.relations.add(DirRelation(
                object_type="program", object_id=p.key, relation="member",
                subject_type="user", subject_id=grantee))
    return state


def snapshot(client) -> DesiredState:
    """This sync's managed live state: program member relations only."""
    live = DesiredState()
    for obj_type, rel in MANAGED_PROGRAM_RELATIONS:
        live.relations.update(client.list_relations(object_type=obj_type, relation=rel))
    return live


def sync_programs(client, programs: list[ProgramRecord], *, prune: bool = True):
    """Ensure program/user objects exist, then diff+apply the managed member
    relations. prune=True REVOKES member relations not asserted in git."""
    from topaz_sync import plan_diff, apply_plan
    desired = derive_desired(programs)
    for o in desired.objects:
        client.set_object(o)  # program + user (ensure; not pruned)
    desired_managed = DesiredState(objects=set(), relations=set(desired.relations))
    live = snapshot(client)
    plan = plan_diff(desired_managed, live.objects, live.relations)
    if not prune:
        plan.del_objects = []
        plan.del_relations = []
    apply_plan(client, plan, {})
    return plan


def readback(client, programs: list[ProgramRecord]) -> tuple[int, int]:
    """Positive control: every (program, grantee) must resolve can_view_program
    TRUE. A missing relation FAILS LOUD (verification-must-be-able-to-fail)."""
    checked = failures = 0
    for p in programs:
        for grantee in p.grant_to:
            checked += 1
            if not client.check("program", p.key, "can_view_program", grantee):
                print(f"  [FAIL] {grantee} can_view_program {p.key}")
                failures += 1
    return checked, failures


def main() -> int:
    """CLI: sync program membership grants into Topaz.
    Env: PROGRAM_MEMBERS_FILE (default policy/program_members.yaml),
    TOPAZ_DIRECTORY_URL. Exit: 0 ok · 2 malformed · 4 readback failed."""
    import yaml
    from topaz_sync import TopazClient

    grants_file = os.getenv("PROGRAM_MEMBERS_FILE", "policy/program_members.yaml")
    topaz_url = os.getenv("TOPAZ_DIRECTORY_URL", "http://topaz-svc:9393")

    with open(grants_file) as f:
        raw = yaml.safe_load(f) or {}
    programs, malformed = load_programs(raw)
    if malformed:
        print("REFUSED — malformed overlay (fix program_members.yaml; nothing applied):",
              file=sys.stderr)
        for e in malformed:
            print(f"  {e}", file=sys.stderr)
        return 2
    n_grants = sum(len(p.grant_to) for p in programs)
    print(f"loaded {len(programs)} program(s), {n_grants} member grant(s)")

    with TopazClient(topaz_url) as client:
        plan = sync_programs(client, programs)
        print(f"synced: +{len(plan.add_relations)} relations, -{len(plan.del_relations)} revoked")
        print("===== Readback (positive control — each grant resolves can_view_program) =====")
        checked, failures = readback(client, programs)
        print(f"  checked={checked}  failures={failures}")
        if failures > 0:
            print("FAIL: a git-asserted program grant does not resolve can_view_program — "
                  "apply lied.", file=sys.stderr)
            return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
