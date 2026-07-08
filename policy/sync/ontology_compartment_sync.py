"""git-asserted ontology-IRI COMPARTMENTS → Topaz directory sync.

WHY THIS EXISTS. ADR-0025's ontology-IRI namespace (ruling 2026-07-08): which
ontology classes a caller may SEE is deny-by-default, Topaz-decided, and
git-asserted — the SAME model as asset/document grants, on a third namespace.
`policy/ontology_compartments.yaml` is the assertion (git-blame = audit trail);
this sync flows it into Topaz as `ontology_class` `viewer` + `restricted`
relations. Engine O's ontology_can_view rego then DECIDES; the gate only ASKS.

FOUR SYNCS, ONE DIRECTORY, DISJOINT SCOPE (no two prune the same relation):
  - topaz_sync.py                 — persona/cell/group/member/user
  - datahub_topaz_sync.py         — dataset `owner`
  - grant_sync.py                 — dataset `reader`
  - ontology_compartment_sync.py  — ontology_class `viewer` + `restricted` (THIS)
This tool owns the `ontology_class` viewer/restricted relations and the sentinel
`marker:REGISTRY` object; it ensures grantee `user` objects exist (never pruned —
the ADR-0026 sync owns `user`) and PRUNES ontology viewer/restricted relations
not asserted in git (removing a compartment/class REVOKES visibility).

COMPARTMENT MODEL. Each git-asserted compartment assigns class IRIs and names who
may see them. Per assigned IRI the sync writes:
  - `ontology_class:<IRI> restricted marker:REGISTRY` — the presence MARKER that
    lets the rego tell UNASSIGNED (no marker → default_visibility governs) from
    ASSIGNED-BUT-UNGRANTED (marker present, viewer absent → deny). Without it the
    releasable default would leak a compartmented-but-ungranted class.
  - `ontology_class:<IRI> viewer user:<grantee>` per grantee — the compartment grant.

PROVE-THE-NEGATIVE ON THE GRANT PATH. A compartment is REFUSED (nothing applied,
non-zero exit) when MALFORMED — missing `granted_by` (accountable human),
`reason`, `grant_to`, or `classes`. An unexplained or targetless compartment is
not a compartment. A broken overlay does not partially apply.

TESTED CORE = the pure transforms (`load_compartments`, `derive_desired`) — no
network. Readback (each grant resolves can_view TRUE) is the positive control;
the reference-INDEPENDENT proof is Engine O's live discriminating seal.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

from topaz_sync import DirObject, DirRelation, DesiredState  # noqa: E402

# Disjoint prune scope: ontology_class viewer + restricted relations only.
MANAGED_ONTOLOGY_RELATIONS = [("ontology_class", "viewer"), ("ontology_class", "restricted")]
_MARKER_ID = "REGISTRY"


@dataclass(frozen=True)
class CompartmentRecord:
    """One git-asserted compartment: the classes whose existence is sensitive
    together, and the entitlement keys (emails) granted to see them. granted_by/
    reason = the audit trail git-blame anchors."""
    name: str
    grant_to: tuple[str, ...]
    classes: tuple[str, ...]
    granted_by: str
    reason: str = ""


def load_compartments(raw: dict) -> tuple[list[CompartmentRecord], list[str], str]:
    """PURE: parsed ontology_compartments.yaml → (compartments, errors,
    default_visibility). prove-the-negative: a compartment missing granted_by /
    grant_to / classes is an ERROR (collected, not dropped). default_visibility
    defaults to 'releasable' and must be one of releasable|deny."""
    errors: list[str] = []
    default_visibility = str((raw or {}).get("default_visibility") or "releasable").lower()
    if default_visibility not in ("releasable", "deny"):
        errors.append(f"default_visibility MUST be 'releasable' or 'deny', got {default_visibility!r}")
    out: list[CompartmentRecord] = []
    for name, entry in ((raw or {}).get("compartments") or {}).items():
        entry = entry or {}
        grant_to = [str(g).strip() for g in (entry.get("grant_to") or []) if str(g).strip()]
        classes = [str(c).strip() for c in (entry.get("classes") or []) if str(c).strip()]
        granted_by = str(entry.get("granted_by") or "").strip()
        missing = [
            k for k, v in (("granted_by", granted_by), ("reason", entry.get("reason")),
                           ("grant_to", grant_to), ("classes", classes))
            if not v
        ]
        if missing:
            errors.append(f"compartment[{name}] MALFORMED: missing {', '.join(missing)}")
            continue
        out.append(CompartmentRecord(
            name=name, grant_to=tuple(grant_to), classes=tuple(classes),
            granted_by=granted_by, reason=str(entry.get("reason") or "")))
    return out, errors, default_visibility


def derive_desired(compartments: list[CompartmentRecord]) -> DesiredState:
    """PURE: compartments → DesiredState. Per assigned IRI: a `restricted` marker
    relation + a `viewer` relation per grantee. Plus the ontology_class + marker
    + user objects (ensure-present)."""
    state = DesiredState()
    state.objects.add(DirObject("marker", _MARKER_ID))
    for c in compartments:
        for iri in c.classes:
            state.objects.add(DirObject("ontology_class", iri))
            state.relations.add(DirRelation(
                object_type="ontology_class", object_id=iri, relation="restricted",
                subject_type="marker", subject_id=_MARKER_ID))
            for grantee in c.grant_to:
                state.objects.add(DirObject("user", grantee))
                state.relations.add(DirRelation(
                    object_type="ontology_class", object_id=iri, relation="viewer",
                    subject_type="user", subject_id=grantee))
    return state


def snapshot(client) -> DesiredState:
    """This sync's managed live state: ontology_class viewer+restricted only."""
    live = DesiredState()
    for obj_type, rel in MANAGED_ONTOLOGY_RELATIONS:
        live.relations.update(client.list_relations(object_type=obj_type, relation=rel))
    return live


def sync_compartments(client, compartments: list[CompartmentRecord], *, prune: bool = True):
    """Ensure ontology_class/marker/user objects exist, then diff+apply the
    managed viewer+restricted relations. prune=True REVOKES relations not in git."""
    from topaz_sync import plan_diff, apply_plan
    desired = derive_desired(compartments)
    for o in desired.objects:
        client.set_object(o)  # ontology_class + marker + user (ensure; not pruned)
    desired_managed = DesiredState(objects=set(), relations=set(desired.relations))
    live = snapshot(client)
    plan = plan_diff(desired_managed, live.objects, live.relations)
    if not prune:
        plan.del_objects = []
        plan.del_relations = []
    apply_plan(client, plan, {})
    return plan


def readback(client, compartments: list[CompartmentRecord]) -> tuple[int, int]:
    """Positive control: every (class, grantee) must resolve can_view TRUE.
    A missing relation FAILS LOUD (verification-must-be-able-to-fail)."""
    checked = failures = 0
    for c in compartments:
        for iri in c.classes:
            for grantee in c.grant_to:
                checked += 1
                if not client.check("ontology_class", iri, "can_view", grantee):
                    print(f"  [FAIL] {grantee} can_view {iri}")
                    failures += 1
    return checked, failures


def main() -> int:
    """CLI: sync ontology compartments into Topaz.
    Env: ONTOLOGY_COMPARTMENTS_FILE (default policy/ontology_compartments.yaml),
    TOPAZ_DIRECTORY_URL. Exit: 0 ok · 2 malformed · 4 readback failed."""
    import yaml
    from topaz_sync import TopazClient

    comp_file = os.getenv("ONTOLOGY_COMPARTMENTS_FILE", "policy/ontology_compartments.yaml")
    topaz_url = os.getenv("TOPAZ_DIRECTORY_URL", "http://topaz-svc:9393")

    with open(comp_file) as f:
        raw = yaml.safe_load(f) or {}
    compartments, malformed, default_visibility = load_compartments(raw)
    if malformed:
        print("REFUSED — malformed overlay (fix ontology_compartments.yaml; nothing applied):",
              file=sys.stderr)
        for e in malformed:
            print(f"  {e}", file=sys.stderr)
        return 2
    n_classes = sum(len(c.classes) for c in compartments)
    print(f"loaded {len(compartments)} compartment(s), {n_classes} class assignment(s); "
          f"default_visibility={default_visibility}")

    with TopazClient(topaz_url) as client:
        plan = sync_compartments(client, compartments)
        print(f"synced: +{len(plan.add_relations)} relations, -{len(plan.del_relations)} revoked")
        print("===== Readback (positive control — each grant resolves can_view) =====")
        checked, failures = readback(client, compartments)
        print(f"  checked={checked}  failures={failures}")
        if failures > 0:
            print("FAIL: a git-asserted compartment grant does not resolve can_view — apply lied.",
                  file=sys.stderr)
            return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
