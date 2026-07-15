"""git-asserted CAPABILITY invoker grants → Topaz directory sync.

WHY THIS EXISTS. A workflow `direct_call` step (ADR-0029 Slice 1, RULING Q3) is a
TRANSITIONAL action not (yet) a mesh verb. It escapes the verb ONTOLOGY but NOT the
GATE: WHO may INVOKE a capability is deny-by-default, Topaz-decided, and git-asserted
— the SAME model as asset/document/ontology/task grants, on a SIXTH namespace
(capabilities). `policy/capability_grants.yaml` is the assertion (git-blame = audit
trail); this sync flows it into Topaz as `capability` `invoker` relations. The
runner's `execute_direct_call` then re-checks `can_invoke` BEFORE the POST; both
derive from THIS sync's relations, so the schema gate (capability required) and the
runtime gate (can_invoke checked) cannot diverge.

SIX SYNCS, ONE DIRECTORY, DISJOINT SCOPE (no two prune the same relation):
  - topaz_sync.py                 — persona/cell/group/member/user
  - datahub_topaz_sync.py         — dataset `owner`
  - grant_sync.py                 — dataset `reader`
  - ontology_compartment_sync.py  — ontology_class `viewer` + `restricted`
  - task_grant_sync.py            — task_audience `actor`
  - capability_grant_sync.py      — capability `invoker` (THIS)
This tool owns the `capability` `invoker` relations; it ensures grantee `user`
objects exist (never pruned — the ADR-0026 sync owns `user`) and PRUNES capability
invoker relations not asserted in git (removing a grant REVOKES the ability to
invoke — and, since a direct_call fails-and-releases on an ungranted capability, to
even complete the workflow step).

PROVE-THE-NEGATIVE ON THE GRANT PATH. A capability is REFUSED (nothing applied,
non-zero exit) when MALFORMED — missing `granted_by` (accountable human), `reason`,
or `grant_to`. An unexplained or targetless capability grant is not a grant. An
INVOKE is an EFFECT (a mutation), so the audit trail here is load-bearing.

TESTED CORE = the pure transforms (`load_capabilities`, `derive_desired`) — no
network. Readback (each grant resolves can_invoke TRUE) is the positive control; the
reference-INDEPENDENT proof is the live workflow seal (authorized initiator's
direct_call invokes; unauthorized fails-and-releases, TerminalError, no held state).
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from topaz_sync import DirObject, DirRelation, DesiredState  # noqa: E402

# Disjoint prune scope: capability invoker relations only.
MANAGED_CAPABILITY_RELATIONS = [("capability", "invoker")]


@dataclass(frozen=True)
class CapabilityRecord:
    """One git-asserted capability: the capability IRI (the Topaz `capability`
    object_id) and the entitlement keys (emails) granted to INVOKE it. granted_by/
    reason = the audit trail git-blame anchors."""
    key: str
    grant_to: tuple[str, ...]
    granted_by: str
    reason: str = ""


def load_capabilities(raw: dict) -> tuple[list[CapabilityRecord], list[str]]:
    """PURE: parsed capability_grants.yaml → (capabilities, errors). prove-the-
    negative: a capability missing granted_by / reason / grant_to is an ERROR
    (collected, not dropped) — a broken overlay refuses whole, never partially
    applies."""
    errors: list[str] = []
    out: list[CapabilityRecord] = []
    for key, entry in ((raw or {}).get("capabilities") or {}).items():
        entry = entry or {}
        grant_to = [str(g).strip() for g in (entry.get("grant_to") or []) if str(g).strip()]
        granted_by = str(entry.get("granted_by") or "").strip()
        missing = [
            k for k, v in (("granted_by", granted_by), ("reason", entry.get("reason")),
                           ("grant_to", grant_to))
            if not v
        ]
        if missing:
            errors.append(f"capability[{key}] MALFORMED: missing {', '.join(missing)}")
            continue
        out.append(CapabilityRecord(
            key=str(key), grant_to=tuple(grant_to),
            granted_by=granted_by, reason=str(entry.get("reason") or "")))
    return out, errors


def derive_desired(capabilities: list[CapabilityRecord]) -> DesiredState:
    """PURE: capabilities → DesiredState. Per capability, per grantee: an `invoker`
    relation. Plus the capability + user objects (ensure-present)."""
    state = DesiredState()
    for c in capabilities:
        state.objects.add(DirObject("capability", c.key))
        for grantee in c.grant_to:
            state.objects.add(DirObject("user", grantee))
            state.relations.add(DirRelation(
                object_type="capability", object_id=c.key, relation="invoker",
                subject_type="user", subject_id=grantee))
    return state


def snapshot(client) -> DesiredState:
    """This sync's managed live state: capability invoker relations only."""
    live = DesiredState()
    for obj_type, rel in MANAGED_CAPABILITY_RELATIONS:
        live.relations.update(client.list_relations(object_type=obj_type, relation=rel))
    return live


def sync_capabilities(client, capabilities: list[CapabilityRecord], *, prune: bool = True):
    """Ensure capability/user objects exist, then diff+apply the managed invoker
    relations. prune=True REVOKES invoker relations not asserted in git."""
    from topaz_sync import plan_diff, apply_plan
    desired = derive_desired(capabilities)
    for o in desired.objects:
        client.set_object(o)  # capability + user (ensure; not pruned)
    desired_managed = DesiredState(objects=set(), relations=set(desired.relations))
    live = snapshot(client)
    plan = plan_diff(desired_managed, live.objects, live.relations)
    if not prune:
        plan.del_objects = []
        plan.del_relations = []
    apply_plan(client, plan, {})
    return plan


def readback(client, capabilities: list[CapabilityRecord]) -> tuple[int, int]:
    """Positive control: every (capability, grantee) must resolve can_invoke TRUE.
    A missing relation FAILS LOUD (verification-must-be-able-to-fail)."""
    checked = failures = 0
    for c in capabilities:
        for grantee in c.grant_to:
            checked += 1
            if not client.check("capability", c.key, "can_invoke", grantee):
                print(f"  [FAIL] {grantee} can_invoke {c.key}")
                failures += 1
    return checked, failures


def main() -> int:
    """CLI: sync capability invoker grants into Topaz.
    Env: CAPABILITY_GRANTS_FILE (default policy/capability_grants.yaml),
    TOPAZ_DIRECTORY_URL. Exit: 0 ok · 2 malformed · 4 readback failed."""
    import yaml
    from topaz_sync import TopazClient

    grants_file = os.getenv("CAPABILITY_GRANTS_FILE", "policy/capability_grants.yaml")
    topaz_url = os.getenv("TOPAZ_DIRECTORY_URL", "http://topaz-svc:9393")

    with open(grants_file) as f:
        raw = yaml.safe_load(f) or {}
    capabilities, malformed = load_capabilities(raw)
    if malformed:
        print("REFUSED — malformed overlay (fix capability_grants.yaml; nothing applied):",
              file=sys.stderr)
        for e in malformed:
            print(f"  {e}", file=sys.stderr)
        return 2
    n_grants = sum(len(c.grant_to) for c in capabilities)
    print(f"loaded {len(capabilities)} capability(ies), {n_grants} invoker grant(s)")

    with TopazClient(topaz_url) as client:
        plan = sync_capabilities(client, capabilities)
        print(f"synced: +{len(plan.add_relations)} relations, -{len(plan.del_relations)} revoked")
        print("===== Readback (positive control — each grant resolves can_invoke) =====")
        checked, failures = readback(client, capabilities)
        print(f"  checked={checked}  failures={failures}")
        if failures > 0:
            print("FAIL: a git-asserted capability grant does not resolve can_invoke — apply lied.",
                  file=sys.stderr)
            return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
