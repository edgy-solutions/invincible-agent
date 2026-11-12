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
or BOTH `grant_to` and `grant_to_groups` (at least one must be non-empty). An unexplained or
targetless capability grant is not a grant. An INVOKE is an EFFECT (a mutation), so the audit
trail here is load-bearing.

GROUPS (2026-10-28, mirroring task_grant_sync.py exactly). `grant_to_groups` is written as
`invoker` relations with subject `group:<G>#member`; membership lives in users.yaml / topaz_sync,
never here. A group object is never created here (an empty group would pass readback while
granting nobody): one absent from live Topaz is REFUSED BEFORE ANY WRITE, exit 5.

THE `can_drop:<content_kind>` CONVENTION AND THE SCOPED OBJECT PRUNE. A capability keyed
`can_drop:<K>` gates DROPS of content kind K (the 2026-10-28 ruling: pcn and pdn droppable by
alert-processors only). The gated set is not a field on the content kind (the SDK registration
forbids extra fields); instead a kind K is gated iff the Topaz OBJECT `capability:can_drop:K`
EXISTS. So object existence must mirror the rows exactly: under prune=True this sync deletes every
live `capability` object whose id starts with `can_drop:` and that no row names -- deleting a row
REOPENS the kind to every caller. Every other capability object stays ensure-not-pruned (the
object prune is scoped to the `can_drop:` prefix and to prune=True; prune=False deletes nothing).

`can_export:<P>` IS DENY-BY-DEFAULT, the opposite of `can_drop:`. The door asks can_invoke on
`can_export:<P>` and False refuses, so a profile with no row is exportable by nobody and object
existence decides nothing. What revokes it is the invoker-relation prune above (delete the row, the
relation goes); the `can_drop:` OBJECT prune deliberately does not cover `can_export:` objects.

A `can_export:<P>` ROW NAMING A PROFILE THIS DEPLOYMENT DOES NOT KNOW is refused ON ITS OWN, with a
report, and the rest of the sync applies (architect 2026-11-11). "Known" is per deployment: the
image's base profiles plus the overlay directories the deployment loads (the same variables the
engines read, composed by validate_policy.known_export_profiles through each kind's own loader
rule). The sample profiles are known only where the sample overlay is loaded. The refused row is
absent from the desired state, so any relation an earlier run wrote for it is pruned. The refusal
is a report, never an exit code: the Job stays green. A profile with NO row is not an error: the
door refuses it and the listing omits it.

SAMPLE OVERLAY (add-only). `CAPABILITY_GRANT_OVERLAY_DIRS` (os.pathsep-separated, as
CONTENT_KIND_OVERLAY_DIRS is) names directories each holding a `capability_grants.yaml`. It is
merged into the seed IN MEMORY, before the sync (the sync prunes, so a grant applied afterwards would
be pruned). An overlay can add grantees to a capability the seed already declares and nothing else:
it cannot create a capability, remove or replace a grantee, or change granted_by / reason, and a row
carrying any field beyond granted_by, reason, grant_to, grant_to_groups is refused. A listed
directory without the file is refused (fail closed). Unset or empty: no overlay, nothing changes.

Exit codes: 0 ok (a refused can_export row included: see its report) - 2 malformed (the seed or an
overlay) - 4 readback failed - 5 a granted group object is absent from live Topaz.

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

# Disjoint prune scope: capability invoker relations, plus orphan `can_drop:` capability OBJECTS.
MANAGED_CAPABILITY_RELATIONS = [("capability", "invoker")]
# A capability object with this id prefix gates drops of the named content kind by EXISTING.
DROP_PREFIX = "can_drop:"


@dataclass(frozen=True)
class CapabilityRecord:
    """One git-asserted capability: the capability IRI (the Topaz `capability`
    object_id) and the entitlement keys (emails) granted to INVOKE it. granted_by/
    reason = the audit trail git-blame anchors."""
    key: str
    grant_to: tuple[str, ...]
    granted_by: str
    reason: str = ""
    #: groups (policy/groups.yaml) granted to INVOKE; written as `group:<G>#member` subjects.
    #: Membership lives in users.yaml / topaz_sync, never here.
    grant_to_groups: tuple[str, ...] = ()


class GroupObjectMissing(RuntimeError):
    """A `grant_to_groups` entry names a group that does not exist in live Topaz. Refused rather
    than created: membership is topaz_sync's job, and an empty group object would pass readback
    while granting NOBODY."""


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
        grant_to_groups = [str(g).strip() for g in (entry.get("grant_to_groups") or [])
                           if str(g).strip()]
        granted_by = str(entry.get("granted_by") or "").strip()
        missing = [
            k for k, v in (("granted_by", granted_by), ("reason", entry.get("reason")))
            if not v
        ]
        if not grant_to and not grant_to_groups:
            missing.append("grant_to or grant_to_groups")
        if missing:
            errors.append(f"capability[{key}] MALFORMED: missing {', '.join(missing)}")
            continue
        out.append(CapabilityRecord(
            key=str(key), grant_to=tuple(grant_to),
            granted_by=granted_by, reason=str(entry.get("reason") or ""),
            grant_to_groups=tuple(grant_to_groups)))
    return out, errors


OVERLAY_ENV = "CAPABILITY_GRANT_OVERLAY_DIRS"
OVERLAY_FILE = "capability_grants.yaml"
OVERLAY_FIELDS = frozenset({"granted_by", "reason", "grant_to", "grant_to_groups"})


def overlay_dirs() -> list[str]:
    """The overlay directories named by CAPABILITY_GRANT_OVERLAY_DIRS, split the way
    validate_policy splits CONTENT_KIND_OVERLAY_DIRS. Unset or empty: none."""
    raw = (os.getenv(OVERLAY_ENV) or "").strip()
    return [p.strip() for p in raw.split(os.pathsep) if p.strip()]


def load_overlay_files(dirs: list[str]) -> tuple[list[tuple[str, dict]], list[str]]:
    """Read `<dir>/capability_grants.yaml` for each dir. A missing dir or file is an error."""
    import yaml
    out: list[tuple[str, dict]] = []
    errors: list[str] = []
    for d in dirs:
        path = os.path.join(d, OVERLAY_FILE)
        if not os.path.isfile(path):
            errors.append(f"overlay dir {d!r} is listed in {OVERLAY_ENV} but {path!r} does not exist")
            continue
        try:
            with open(path, encoding="utf-8") as f:
                doc = yaml.safe_load(f) or {}
        except (OSError, yaml.YAMLError) as exc:
            errors.append(f"overlay {path!r} could not be read ({type(exc).__name__}: {exc})")
            continue
        if not isinstance(doc, dict):
            errors.append(f"overlay {path!r} is not a mapping")
            continue
        out.append((path, doc))
    return out, errors


def apply_capability_overlays(
    seed: list[CapabilityRecord], overlays: list[tuple[str, dict]],
) -> tuple[list[CapabilityRecord], list[str]]:
    """PURE: (merged, errors). ADD, AND NOTHING ELSE: an overlay row adds grantees (union of
    grant_to and grant_to_groups, seed order kept, new ones appended) to a capability the seed
    already declares. Refused (collected as errors): a key not in the seed, a field beyond
    OVERLAY_FIELDS, and any row `load_capabilities` refuses. The seed's granted_by / reason are
    unchanged and no seed grantee is removed."""
    errors: list[str] = []
    by_key = {c.key: c for c in seed}
    order = [c.key for c in seed]
    for source, raw in overlays:
        caps = (raw or {}).get("capabilities") or {}
        if not isinstance(caps, dict):
            errors.append(f"overlay {source}: `capabilities` is not a mapping")
            continue
        for key, entry in caps.items():
            entry = entry or {}
            if not isinstance(entry, dict):
                errors.append(f"overlay {source}: capability[{key}] is not a mapping")
                continue
            extra = sorted(str(k) for k in entry if k not in OVERLAY_FIELDS)
            if extra:
                errors.append(f"overlay {source}: capability[{key}] carries field(s) an overlay may "
                              f"not: {', '.join(extra)} (add-only: {', '.join(sorted(OVERLAY_FIELDS))})")
            if str(key) not in by_key:
                errors.append(f"overlay {source}: capability[{key}] is not in the seed "
                              f"(an overlay cannot create a capability)")
            rows, row_errors = load_capabilities({"capabilities": {key: entry}})
            errors.extend(f"overlay {source}: {e}" for e in row_errors)
            if extra or row_errors or str(key) not in by_key:
                continue
            row = rows[0]
            cur = by_key[str(key)]
            by_key[str(key)] = CapabilityRecord(
                key=cur.key,
                grant_to=cur.grant_to + tuple(g for g in dict.fromkeys(row.grant_to)
                                              if g not in cur.grant_to),
                granted_by=cur.granted_by, reason=cur.reason,
                grant_to_groups=cur.grant_to_groups + tuple(
                    g for g in dict.fromkeys(row.grant_to_groups) if g not in cur.grant_to_groups))
    return [by_key[k] for k in order], errors


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
        # A group is NOT added to state.objects: the group object is topaz_sync's, and
        # creating it here would make an empty group that passes readback.
        for group in c.grant_to_groups:
            state.relations.add(DirRelation(
                object_type="capability", object_id=c.key, relation="invoker",
                subject_type="group", subject_id=group, subject_relation="member"))
    return state


def snapshot(client) -> DesiredState:
    """This sync's managed live state: capability invoker relations only."""
    live = DesiredState()
    for obj_type, rel in MANAGED_CAPABILITY_RELATIONS:
        live.relations.update(client.list_relations(object_type=obj_type, relation=rel))
    return live


def sync_capabilities(client, capabilities: list[CapabilityRecord], *, prune: bool = True):
    """Ensure capability/user objects exist, then diff+apply the managed invoker
    relations. prune=True REVOKES invoker relations not asserted in git, and deletes every live
    `capability` object named `can_drop:*` that no row names (REOPENING that kind); no other
    capability object is ever deleted. Raises GroupObjectMissing before any write."""
    from topaz_sync import plan_diff, apply_plan
    # Refuse BEFORE any write: every named group object must already exist live.
    groups = sorted({g for c in capabilities for g in c.grant_to_groups})
    absent = [g for g in groups if not client.object_exists("group", g)]
    if absent:
        raise GroupObjectMissing(
            "group object(s) absent from live Topaz: " + ", ".join(f"group:{g}" for g in absent)
            + " (membership is topaz_sync's job; nothing written)")
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
    if prune:
        named = {c.key for c in capabilities}
        for o in client.list_objects("capability"):
            if o.id.startswith(DROP_PREFIX) and o.id not in named:
                client.delete_object(o)
    return plan


def readback(client, capabilities: list[CapabilityRecord]) -> tuple[int, int]:
    """Positive control: every (capability, grantee) must resolve can_invoke TRUE; a group
    grantee is checked by the PRESENCE of its `group:<G>#member` invoker relation (a group is
    not a caller, so can_invoke cannot be asked of it). A missing relation FAILS LOUD
    (verification-must-be-able-to-fail)."""
    checked = failures = 0
    live_rels = None
    for c in capabilities:
        for group in c.grant_to_groups:
            checked += 1
            if live_rels is None:
                live_rels = set(client.list_relations(object_type="capability",
                                                      relation="invoker"))
            if DirRelation("capability", c.key, "invoker", "group", group,
                           "member") not in live_rels:
                print(f"  [FAIL] group:{group}#member invoker {c.key}")
                failures += 1
        for grantee in c.grant_to:
            checked += 1
            if not client.check("capability", c.key, "can_invoke", grantee):
                print(f"  [FAIL] {grantee} can_invoke {c.key}")
                failures += 1
    return checked, failures


EXPORT_PREFIX = "can_export:"


def split_export_rows(
    capabilities: list[CapabilityRecord], known: set[str] | None,
) -> tuple[list[CapabilityRecord], list[CapabilityRecord]]:
    """PURE: (kept, refused). A `can_export:<P>` row whose P is not in `known` is refused; every
    other row, and every can_export row naming a known profile, is kept in order. `known=None`
    means the known set could not be composed: nothing is refused (the caller says so)."""
    if known is None:
        return list(capabilities), []
    kept: list[CapabilityRecord] = []
    refused: list[CapabilityRecord] = []
    for c in capabilities:
        if c.key.startswith(EXPORT_PREFIX) and c.key[len(EXPORT_PREFIX):] not in known:
            refused.append(c)
        else:
            kept.append(c)
    return kept, refused


def known_export_names() -> tuple[set[str] | None, list[str]]:
    """The export profiles this deployment knows, and the lines to print about how that went.
    `None` when the set cannot be trusted (a source refused, two kinds collide, or the composition
    could not run): the refusal pass is then skipped and the lines say so loudly."""
    try:
        from validate_policy import known_export_profiles
        profiles, notes = known_export_profiles()
    except Exception as exc:  # noqa: BLE001 -- a composition fault must not take the sync down
        return None, [f"WARN: the known export profiles could not be composed ({type(exc).__name__}: "
                      f"{exc}); no can_export row is refused by name this run"]
    bad = [n for n in notes if n.startswith(("REFUSED:", "COLLISION:"))]
    if bad:
        return None, [f"WARN: the known export profile set is not trustworthy ({n}); no can_export "
                      f"row is refused by name this run" for n in bad]
    return set(profiles), [f"known export profiles: {n}" for n in notes]


def export_row_report(refused: list[CapabilityRecord], kept: list[CapabilityRecord],
                      known: set[str] | None) -> tuple[list[str], list[str]]:
    """PURE: (refusal lines for stderr, a summary line for stdout)."""
    lines = [f"REFUSED ROW capability[{c.key}]: {c.key[len(EXPORT_PREFIX):]!r} is not an export "
             f"profile this deployment knows (known: {', '.join(sorted(known or ())) or 'none'}); "
             f"this row is not applied, every other row is" for c in refused]
    n_kept = sum(1 for c in kept if c.key.startswith(EXPORT_PREFIX))
    return lines, f"can_export rows: {n_kept} applied, {len(refused)} refused"


def main() -> int:
    """CLI: sync capability invoker grants into Topaz.
    Env: CAPABILITY_GRANTS_FILE (default policy/capability_grants.yaml),
    CAPABILITY_GRANT_OVERLAY_DIRS (add-only grantee overlay; malformed or missing file: exit 2),
    TOPAZ_DIRECTORY_URL, and the deployment's *_OVERLAY_DIRS (which decide the known export profiles).
    A `can_export:<name>` row naming an unknown profile is refused alone: a stderr line per row,
    a stdout summary, exit unchanged. Exit: 0 ok · 2 malformed · 4 readback failed · 5 a granted group
    object is absent from live Topaz."""
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
    overlays, overlay_errors = load_overlay_files(overlay_dirs())
    merged: list[CapabilityRecord] = capabilities
    if not overlay_errors:
        merged, overlay_errors = apply_capability_overlays(capabilities, overlays)
    if overlay_errors:
        print("REFUSED — malformed capability overlay (nothing applied):", file=sys.stderr)
        for e in overlay_errors:
            print(f"  {e}", file=sys.stderr)
        return 2
    for source, raw_overlay in overlays:
        one, _ = apply_capability_overlays(capabilities, [(source, raw_overlay)])
        before = {c.key: set(c.grant_to) | set(c.grant_to_groups) for c in capabilities}
        after = {c.key: set(c.grant_to) | set(c.grant_to_groups) for c in one}
        added = sum(len(after[k] - before[k]) for k in before)
        touched = sum(1 for k in before if after[k] != before[k])
        print(f"capability overlay {source}: +{added} grantee(s) on {touched} capability(ies)")
    capabilities = merged
    known, known_lines = known_export_names()
    for line in known_lines:
        print(line, file=sys.stderr if line.startswith("WARN") else sys.stdout)
    capabilities, refused = split_export_rows(capabilities, known)
    refusal_lines, summary = export_row_report(refused, capabilities, known)
    for line in refusal_lines:
        print(line, file=sys.stderr)
    print(summary)
    n_grants = sum(len(c.grant_to) + len(c.grant_to_groups) for c in capabilities)
    print(f"loaded {len(capabilities)} capability(ies), {n_grants} invoker grant(s)")

    with TopazClient(topaz_url) as client:
        try:
            plan = sync_capabilities(client, capabilities)
        except GroupObjectMissing as e:
            print(f"REFUSED — {e}", file=sys.stderr)
            return 5
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
