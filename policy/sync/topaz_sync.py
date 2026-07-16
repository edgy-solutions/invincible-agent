#!/usr/bin/env python3
"""
Sync `policy/` YAML to a running Topaz directory (ADR-0026 step 2).

Reads:
    policy/personas.yaml
    policy/domains.yaml
    policy/groups.yaml
    policy/users.yaml

Writes to a Topaz Directory over its HTTP gateway (port 9393 by
default). Idempotent — `set object` / `set relation` are upsert.

Discipline:
    * Every entitlement in the YAML files is a named human's asserted
      claim. No auto-derivation from directory/AD data here — see
      policy/README.md.
    * After apply, runs a readback (`[[verification-must-fail]]`
      gate): every asserted (user, cell) grant MUST return TRUE from
      a topaz permission check; any relation asserted in YAML but
      missing from topaz fails the sync loudly.
    * Diff-based deletion — if a group is removed from YAML, the tool
      removes the corresponding topaz objects and relations. Removing a
      USER prunes their `member` relations (revoking every cell and
      everything derived) but leaves the bare `user` object: user
      objects are ENSURE-ONLY family-wide (see ENSURE_ONLY_TYPES) —
      multiple syncs ensure them and none may prune the type, or the
      syncs fight over identities that aren't in users.yaml (DataHub
      owners, grantees). `--dry-run` prints the diff without applying.

Usage:
    # Against a running sandbox via port-forward:
    kubectl port-forward -n sandbox svc/topaz-svc 9393:9393 &
    python policy/sync/topaz_sync.py \\
        --topaz-url http://localhost:9393 \\
        --policy-dir policy/

    # Dry-run (print planned actions, apply nothing):
    python policy/sync/topaz_sync.py \\
        --topaz-url http://localhost:9393 \\
        --policy-dir policy/ \\
        --dry-run

Dependencies: httpx, pydantic, pyyaml. See requirements.txt.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import yaml
from pydantic import BaseModel, Field, ValidationError, model_validator


# ---------------------------------------------------------------------------
# Schema (Pydantic) — validates YAML shape before touching topaz.
# ---------------------------------------------------------------------------


class Grant(BaseModel):
    persona: str
    domain: str


class GroupSpec(BaseModel):
    grants: list[Grant]


class DefaultCell(BaseModel):
    persona: str
    domains: list[str] = Field(min_length=1)


class UserSpec(BaseModel):
    id: str
    display_name: str | None = None
    groups: list[str] = Field(default_factory=list)
    default: DefaultCell | None = None


class PolicyBundle(BaseModel):
    """Everything the sync tool loads from `policy/`."""

    personas: list[str]
    domains: list[str]
    groups: dict[str, GroupSpec]
    users: list[UserSpec]

    @model_validator(mode="after")
    def _cross_validate(self) -> "PolicyBundle":
        """Vocabulary + reference checks — catches typos in YAML
        before topaz would reject them with a less-friendly error.
        """
        personas_set = set(self.personas)
        domains_set = set(self.domains)
        groups_set = set(self.groups.keys())

        for group_name, group_spec in self.groups.items():
            for grant in group_spec.grants:
                if grant.persona not in personas_set:
                    raise ValueError(
                        f"groups.{group_name} grants persona "
                        f"{grant.persona!r} which is not in personas.yaml"
                    )
                if grant.domain not in domains_set:
                    raise ValueError(
                        f"groups.{group_name} grants domain "
                        f"{grant.domain!r} which is not in domains.yaml"
                    )

        for user in self.users:
            for group_name in user.groups:
                if group_name not in groups_set:
                    raise ValueError(
                        f"user {user.id} references group "
                        f"{group_name!r} which is not in groups.yaml"
                    )
            if user.default is not None:
                if user.default.persona not in personas_set:
                    raise ValueError(
                        f"user {user.id} default persona "
                        f"{user.default.persona!r} not in personas.yaml"
                    )
                for domain in user.default.domains:
                    if domain not in domains_set:
                        raise ValueError(
                            f"user {user.id} default domain "
                            f"{domain!r} not in domains.yaml"
                        )
                # Default cell must be one the user's groups actually
                # grant — a default outside the entitlement matrix is
                # a misconfiguration [[verification-must-fail]] catches.
                default_cells = {
                    (grant.persona, domain)
                    for group_name in user.groups
                    for grant in self.groups[group_name].grants
                    for domain in [grant.domain]
                }
                for domain in user.default.domains:
                    if (user.default.persona, domain) not in default_cells:
                        raise ValueError(
                            f"user {user.id} default cell "
                            f"({user.default.persona}, {domain}) is not "
                            f"in their group grants — pick a default the "
                            f"user is actually entitled to."
                        )
        return self


# ---------------------------------------------------------------------------
# YAML loader — one function per file, then merge into PolicyBundle.
# ---------------------------------------------------------------------------


def load_policy(policy_dir: Path) -> PolicyBundle:
    def _read(name: str) -> dict[str, Any]:
        path = policy_dir / name
        if not path.is_file():
            raise FileNotFoundError(f"missing required policy file: {path}")
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            raise ValueError(f"{path}: top-level YAML must be a mapping")
        return data

    personas = _read("personas.yaml").get("personas", [])
    domains = _read("domains.yaml").get("domains", [])
    groups = _read("groups.yaml").get("groups", {})
    users = _read("users.yaml").get("users", [])

    return PolicyBundle(
        personas=personas,
        domains=domains,
        groups=groups,
        users=users,
    )


# ---------------------------------------------------------------------------
# Desired-state derivation — flatten YAML into topaz objects/relations.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DirObject:
    type: str
    id: str

    def __str__(self) -> str:
        return f"{self.type}:{self.id}"


@dataclass(frozen=True)
class DirRelation:
    object_type: str
    object_id: str
    relation: str
    subject_type: str
    subject_id: str
    subject_relation: str = ""

    def __str__(self) -> str:
        sub = f"{self.subject_type}:{self.subject_id}"
        if self.subject_relation:
            sub += f"#{self.subject_relation}"
        return f"{self.object_type}:{self.object_id}#{self.relation}@{sub}"


@dataclass
class DesiredState:
    objects: set[DirObject] = field(default_factory=set)
    relations: set[DirRelation] = field(default_factory=set)


def derive_desired(bundle: PolicyBundle) -> DesiredState:
    """Flatten a PolicyBundle into (objects, relations) for topaz."""
    state = DesiredState()

    # Vocabulary objects — one persona / domain object each.
    for persona in bundle.personas:
        state.objects.add(DirObject("persona", persona))
    for domain in bundle.domains:
        state.objects.add(DirObject("domain", domain))

    # Group objects + cell objects + group→cell assumable_by relations
    # (via group#member userset rewrite).
    for group_name, group_spec in bundle.groups.items():
        state.objects.add(DirObject("group", group_name))
        for grant in group_spec.grants:
            cell_id = f"{grant.persona}:{grant.domain}"
            state.objects.add(DirObject("cell", cell_id))
            state.relations.add(
                DirRelation(
                    object_type="cell",
                    object_id=cell_id,
                    relation="assumable_by",
                    subject_type="group",
                    subject_id=group_name,
                    subject_relation="member",
                )
            )
            # Walkable vocabulary edge (de-hardcode phase 1): reify
            # cell→domain membership so policy can WALK from the domain
            # (manifest: domain.can_view = cell->can_assume) instead of
            # ENUMERATING personas to construct candidate cell IDs —
            # the structural reason catalog_domain_view.rego hardcodes
            # the persona list today. Set semantics keep this correct
            # under multi-group grants: the relation survives as long
            # as ANY group grants the cell, and pruning it when the
            # last grant goes is what revokes the walkable path
            # (prune=revoke covers the new edge from day one).
            state.relations.add(
                DirRelation(
                    object_type="domain",
                    object_id=grant.domain,
                    relation="cell",
                    subject_type="cell",
                    subject_id=cell_id,
                )
            )

    # User objects + user→group member relations.
    for user in bundle.users:
        state.objects.add(DirObject("user", user.id))
        for group_name in user.groups:
            state.relations.add(
                DirRelation(
                    object_type="group",
                    object_id=group_name,
                    relation="member",
                    subject_type="user",
                    subject_id=user.id,
                )
            )

    return state


# ---------------------------------------------------------------------------
# Topaz HTTP client — thin wrapper around Directory v3 REST endpoints.
# ---------------------------------------------------------------------------


class TopazClient:
    """Thin HTTP client for topaz's Directory v3 REST gateway.

    Endpoints are the grpc-gateway HTTP mappings of the aserto
    directory v3 gRPC service. Paths hold across topaz 0.32+.
    """

    def __init__(self, url: str, timeout_seconds: float = 10.0):
        # httpx `base_url` requires trailing slash for relative-path
        # semantics; be forgiving of either input form.
        self._client = httpx.Client(
            base_url=url.rstrip("/"),
            timeout=timeout_seconds,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "TopazClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    # -- objects ----------------------------------------------------------

    @staticmethod
    def _raise_with_context(r: httpx.Response, what: str) -> None:
        """raise_for_status, but the error NAMES the offending item and
        carries topaz's response body. Without this, a per-object 400 in
        a bulk apply surfaces as a bare 'Client error 400 Bad Request'
        with the rejected item lost — a diagnostic dead-end at scale
        (the work seed's 9k-dataset asset sync was exactly that)."""
        try:
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise httpx.HTTPStatusError(
                f"{e.response.status_code} while writing {what} — "
                f"topaz said: {r.text.strip()[:300]}",
                request=e.request,
                response=e.response,
            ) from None

    def set_object(self, obj: DirObject, display_name: str = "") -> None:
        payload = {
            "object": {
                "type": obj.type,
                "id": obj.id,
            }
        }
        if display_name:
            payload["object"]["display_name"] = display_name
        r = self._client.post("/api/v3/directory/object", json=payload)
        self._raise_with_context(r, f"object {obj}")

    def object_exists(self, obj_type: str, obj_id: str) -> bool:
        """Point lookup by EXACT KEY — GET /object/{type}/{id}; 404 => False.

        Unlike list_objects this never touches the store ITERATOR, so it
        stays correct when listing is broken server-side (live E00000
        list-500 at 9k+ stored datasets) AND it's O(1) per key instead of
        paging the whole type. Prefer it wherever the question is "does
        THIS object exist", not "what objects exist"."""
        from urllib.parse import quote

        r = self._client.get(
            f"/api/v3/directory/object/{quote(obj_type, safe='')}/{quote(obj_id, safe='')}"
        )
        if r.status_code == 404:
            return False
        self._raise_with_context(r, f"existence check of object {obj_type}:{obj_id}")
        return True

    def delete_object(self, obj: DirObject, with_relations: bool = True) -> None:
        from urllib.parse import quote

        params: dict[str, str] = {}
        if with_relations:
            params["with_relations"] = "true"
        # quote(id): DataHub URNs can carry '/' (s3 paths) — raw in the
        # path segment it would misroute and no-op the prune as a 404.
        r = self._client.delete(
            f"/api/v3/directory/object/{quote(obj.type, safe='')}/{quote(obj.id, safe='')}",
            params=params,
        )
        if r.status_code == 404:
            return  # already gone
        self._raise_with_context(r, f"delete of object {obj}")

    def list_objects(self, obj_type: str) -> list[DirObject]:
        # Uses pagination; walk until no page_token returned.
        out: list[DirObject] = []
        page_token = ""
        while True:
            params: dict[str, str] = {"object_type": obj_type}
            if page_token:
                params["page.token"] = page_token
            r = self._client.get("/api/v3/directory/objects", params=params)
            # Context matters doubly on LIST failures: the token names the
            # page boundary where iteration broke (bisect from there with
            # page.size=1) and topaz's body names the server-side error.
            self._raise_with_context(
                r, f"list of {obj_type} objects (page.token={page_token!r})"
            )
            body = r.json()
            for o in body.get("results") or body.get("objects") or []:
                out.append(DirObject(type=o["type"], id=o["id"]))
            page_token = (body.get("page") or {}).get("next_token", "")
            if not page_token:
                break
        return out

    # -- relations --------------------------------------------------------

    def set_relation(self, rel: DirRelation) -> None:
        payload = {
            "relation": {
                "object_type": rel.object_type,
                "object_id": rel.object_id,
                "relation": rel.relation,
                "subject_type": rel.subject_type,
                "subject_id": rel.subject_id,
                "subject_relation": rel.subject_relation,
            }
        }
        r = self._client.post("/api/v3/directory/relation", json=payload)
        self._raise_with_context(r, f"relation {rel}")

    def delete_relation(self, rel: DirRelation) -> None:
        params = {
            "object_type": rel.object_type,
            "object_id": rel.object_id,
            "relation": rel.relation,
            "subject_type": rel.subject_type,
            "subject_id": rel.subject_id,
            "subject_relation": rel.subject_relation,
        }
        r = self._client.delete("/api/v3/directory/relation", params=params)
        if r.status_code == 404:
            return
        self._raise_with_context(r, f"delete of relation {rel}")

    def list_relations(
        self,
        object_type: str = "",
        relation: str = "",
    ) -> list[DirRelation]:
        out: list[DirRelation] = []
        page_token = ""
        while True:
            params: dict[str, str] = {}
            if object_type:
                params["object_type"] = object_type
            if relation:
                params["relation"] = relation
            if page_token:
                params["page.token"] = page_token
            r = self._client.get("/api/v3/directory/relations", params=params)
            self._raise_with_context(
                r,
                f"list of relations (object_type={object_type!r}, "
                f"relation={relation!r}, page.token={page_token!r})",
            )
            body = r.json()
            for x in body.get("results") or body.get("relations") or []:
                out.append(
                    DirRelation(
                        object_type=x["object_type"],
                        object_id=x["object_id"],
                        relation=x["relation"],
                        subject_type=x["subject_type"],
                        subject_id=x["subject_id"],
                        subject_relation=x.get("subject_relation", ""),
                    )
                )
            page_token = (body.get("page") or {}).get("next_token", "")
            if not page_token:
                break
        return out

    # -- manifest (schema) ------------------------------------------------

    def set_manifest_from_file(self, path: Path) -> None:
        """Load a Rebac manifest YAML into the Directory.

        One-time-per-cluster operation. Called by the `--load-manifest`
        flag before any object/relation writes; without it the writer
        API rejects `set object` for a type that doesn't exist in
        the Directory schema. Content-Type is text/yaml because the
        gateway rewrite maps that body directly into the model
        service's UploadRequest.
        """
        with path.open("rb") as f:
            body = f.read()
        r = self._client.post(
            "/api/v3/directory/manifest",
            content=body,
            headers={"Content-Type": "text/yaml"},
        )
        r.raise_for_status()

    # -- permission check (readback verification) -------------------------

    def check(
        self,
        object_type: str,
        object_id: str,
        relation: str,
        subject_id: str,
        subject_type: str = "user",
    ) -> bool:
        """General permission/relation check via `/api/v3/directory/check`
        (evaluates relations AND permissions — pass the permission name as
        `relation`). This is the WORKING endpoint; the `/check/permission`
        path 404s on this Topaz version — which had silently broken the
        cell readback below (it RAISED and crashed the sync at readback,
        after apply, so the positive control never ran — a dead
        verification in the authz sync, `[[verification-reference-independence]]`
        4th instance). One general check, both syncs use it (cell
        assume-grants here, dataset can_read in the enforcement sync)."""
        r = self._client.post(
            "/api/v3/directory/check",
            json={
                "object_type": object_type,
                "object_id": object_id,
                "relation": relation,
                "subject_type": subject_type,
                "subject_id": subject_id,
            },
        )
        r.raise_for_status()
        return bool(r.json().get("check", False))

    def check_permission(
        self,
        user_id: str,
        cell_id: str,
        permission: str = "can_assume",
    ) -> bool:
        """ADR-0026 cell readback: does the user hold this persona×domain
        cell? Delegates to the general `check`."""
        return self.check("cell", cell_id, permission, user_id)


# ---------------------------------------------------------------------------
# Live-state fetch — snapshot topaz's current objects+relations so we can
# diff against desired.
# ---------------------------------------------------------------------------

# THIS sync's prune scope (module-level like the other syncs' MANAGED_*
# constants — disjoint from datahub/grant/ontology/task syncs, no two
# prune the same relation). ("domain", "cell") is the walkable
# vocabulary edge (de-hardcode phase 1): it MUST stay in scope or a
# revoked cell keeps granting domain-view through the walk.
MANAGED_TYPES = ["persona", "domain", "group", "cell", "user"]
MANAGED_RELATIONS = [
    ("group", "member"),
    ("cell", "assumable_by"),
    ("domain", "cell"),
]


def snapshot_live(client: TopazClient) -> tuple[set[DirObject], set[DirRelation]]:
    """Fetch every managed object + relation from topaz.

    Managed types (this sync tool asserts ownership over):
        - persona, domain, group, cell objects
        - user objects for ADD-diffing only — snapshotted so upserts
          diff cleanly, but NEVER pruned (ENSURE_ONLY_TYPES, enforced
          in plan_diff): the DataHub asset sync and the grant syncs
          ensure user objects too, and identities outside users.yaml
          (owners, grantees) must survive this sync's ticks
        - relations of type `member` (on group), `assumable_by`
          (on cell), and `cell` (on domain — the walkable vocabulary
          edge, de-hardcode phase 1; it MUST be in prune scope or a
          revoked cell would keep granting domain-view through the
          walk after its assumable_by is gone)

    Anything OUTSIDE those types is left alone (e.g. ADR-0025's
    `dataset` objects + `owner`/`reader` relations are untouched).
    This is the boundary between what ADR-0026 owns and what ADR-0025
    owns in the same topaz store.
    """
    live_objects: set[DirObject] = set()
    for t in MANAGED_TYPES:
        live_objects.update(client.list_objects(t))

    live_relations: set[DirRelation] = set()
    for obj_type, rel in MANAGED_RELATIONS:
        live_relations.update(
            client.list_relations(object_type=obj_type, relation=rel)
        )

    return live_objects, live_relations


# ---------------------------------------------------------------------------
# Sync logic.
# ---------------------------------------------------------------------------


@dataclass
class Plan:
    add_objects: list[DirObject]
    del_objects: list[DirObject]
    add_relations: list[DirRelation]
    del_relations: list[DirRelation]

    @property
    def is_empty(self) -> bool:
        return not any(
            (
                self.add_objects,
                self.del_objects,
                self.add_relations,
                self.del_relations,
            )
        )

    def print(self, file=sys.stdout) -> None:
        for r in self.del_relations:
            print(f"  - relation: {r}", file=file)
        for o in self.del_objects:
            print(f"  - object:   {o}", file=file)
        for o in self.add_objects:
            print(f"  + object:   {o}", file=file)
        for r in self.add_relations:
            print(f"  + relation: {r}", file=file)
        if self.is_empty:
            print("  (no changes)", file=file)


# Object types that are ENSURED by multiple syncs and therefore pruned by
# NONE — enforced HERE, in the one diff engine every sync shares, so no
# individual sync can reintroduce the fight. `user` objects are created by
# the entitlement sync (users.yaml), the DataHub asset sync (owners), and
# every grant sync (grantees). When the identity populations don't
# coincide — work: E-number entitlements vs email-style DataHub owners —
# a sync that prunes the TYPE deletes the other syncs' users every tick
# (cascading their relations: a fail-closed authz gap until re-added) and
# they get re-created minutes later. Revocation does NOT need object
# pruning: removing a user from users.yaml still prunes their `member`
# relations (cells and everything derived go with them), and a bare user
# object is inert under deny-by-default.
ENSURE_ONLY_TYPES = frozenset({"user"})


def plan_diff(desired: DesiredState, live_objects, live_relations) -> Plan:
    return Plan(
        add_objects=sorted(
            desired.objects - live_objects, key=lambda o: (o.type, o.id)
        ),
        del_objects=sorted(
            (o for o in live_objects - desired.objects
             if o.type not in ENSURE_ONLY_TYPES),
            key=lambda o: (o.type, o.id),
        ),
        add_relations=sorted(
            desired.relations - live_relations, key=str
        ),
        del_relations=sorted(
            live_relations - desired.relations, key=str
        ),
    )


def apply_plan(client: TopazClient, plan: Plan, users_by_id: dict[str, UserSpec]) -> None:
    """Apply in a deletion-first, then addition order.

    Delete order matters: relations before objects (deleting an
    object with `with_relations=true` would cascade, but explicit
    is clearer for audit and matches the plan's shape).
    """
    for rel in plan.del_relations:
        client.delete_relation(rel)
    for obj in plan.del_objects:
        client.delete_object(obj)

    for obj in plan.add_objects:
        display = ""
        if obj.type == "user":
            spec = users_by_id.get(obj.id)
            if spec and spec.display_name:
                display = spec.display_name
        client.set_object(obj, display_name=display)
    for rel in plan.add_relations:
        client.set_relation(rel)


def derive_entitled_domains(bundle: PolicyBundle) -> set[tuple[str, str]]:
    """PURE: every (user_id, domain) pair the YAML entitles — the union
    of domains across each user's groups' grants. This is the expected
    allow-set for the domain can_view readback below (the walkable
    vocabulary edge, de-hardcode phase 1)."""
    pairs: set[tuple[str, str]] = set()
    for user in bundle.users:
        for group_name in user.groups:
            for grant in bundle.groups[group_name].grants:
                pairs.add((user.id, grant.domain))
    return pairs


def readback_verify(
    client: TopazClient,
    bundle: PolicyBundle,
) -> tuple[int, int]:
    """Positive control per [[verification-must-fail]].

    For every asserted (user, cell) grant, check that topaz's
    permission-evaluation returns TRUE. Then, for every entitled
    (user, domain) pair, check `can_view` on the DOMAIN — the walkable
    edge (domain→cell→assumable_by) this sync now seeds. Proving the
    NEW edge's allow path here, while catalog_domain_view.rego still
    carries traffic on its hardcoded persona list, is what makes the
    phase-2 rego swap land on verified relations instead of opening a
    fail-closed window. Prints per-check status; returns
    (checked, failures).
    """
    checked = 0
    failures = 0
    for user in bundle.users:
        for group_name in user.groups:
            group_spec = bundle.groups[group_name]
            for grant in group_spec.grants:
                cell_id = f"{grant.persona}:{grant.domain}"
                checked += 1
                ok = client.check_permission(user.id, cell_id)
                mark = "OK  " if ok else "FAIL"
                print(f"  [{mark}] {user.id}  can_assume  cell:{cell_id}")
                if not ok:
                    failures += 1

    # Walkable-edge positive control (de-hardcode phase 1). An HTTP
    # error here (e.g. a directory still running a manifest WITHOUT
    # domain.can_view) is a loud FAILURE, not a crash — a raise
    # mid-readback would skip the remaining checks and bury the report
    # in a traceback, the exact crash-at-readback-after-apply shape
    # that hid the original readback bug.
    for user_id, domain in sorted(derive_entitled_domains(bundle)):
        checked += 1
        try:
            ok = client.check("domain", domain, "can_view", user_id)
        except httpx.HTTPError as e:
            ok = False
            print(
                f"  [ERR ] domain can_view check errored ({e}) — is the "
                f"chart-0.3.11 manifest (domain.can_view) loaded?"
            )
        mark = "OK  " if ok else "FAIL"
        print(f"  [{mark}] {user_id}  can_view  domain:{domain}")
        if not ok:
            failures += 1
    return checked, failures


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync policy/ YAML entitlements to a running Topaz.",
    )
    parser.add_argument(
        "--topaz-url",
        default="http://localhost:9393",
        help="Base URL for topaz's Directory HTTP gateway (default: %(default)s).",
    )
    parser.add_argument(
        "--policy-dir",
        default="policy",
        help="Path to the policy/ directory (default: %(default)s).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the planned diff and exit; apply nothing.",
    )
    parser.add_argument(
        "--load-manifest",
        metavar="FILE",
        default=None,
        help=(
            "Load the Rebac manifest from FILE into topaz BEFORE the "
            "object/relation sync. One-time-per-cluster op (topaz "
            "rejects writes for undeclared types). For sandbox: pass "
            "the chart's manifest.yaml, extractable via "
            "`kubectl get cm <release>-topaz-config -o "
            "jsonpath='{.data.manifest\\.yaml}'`. Idempotent; safe "
            "to re-run."
        ),
    )
    args = parser.parse_args()

    policy_dir = Path(args.policy_dir).resolve()
    print(f"===== Load policy from {policy_dir} =====")
    try:
        bundle = load_policy(policy_dir)
    except (FileNotFoundError, ValueError, ValidationError) as e:
        print(f"ERROR loading policy: {e}", file=sys.stderr)
        return 2

    print(
        f"  personas={len(bundle.personas)}  "
        f"domains={len(bundle.domains)}  "
        f"groups={len(bundle.groups)}  "
        f"users={len(bundle.users)}"
    )

    desired = derive_desired(bundle)
    users_by_id = {u.id: u for u in bundle.users}

    with TopazClient(args.topaz_url) as client:
        if args.load_manifest:
            manifest_path = Path(args.load_manifest).resolve()
            print(f"===== Load manifest from {manifest_path} =====")
            try:
                client.set_manifest_from_file(manifest_path)
                print("  loaded.")
            except (FileNotFoundError, httpx.HTTPError) as e:
                print(f"ERROR loading manifest: {e}", file=sys.stderr)
                return 3

        print(f"===== Snapshot live state at {args.topaz_url} =====")
        try:
            live_objects, live_relations = snapshot_live(client)
        except httpx.HTTPError as e:
            print(f"ERROR contacting topaz: {e}", file=sys.stderr)
            return 3
        print(
            f"  live objects={len(live_objects)}  "
            f"live relations={len(live_relations)}"
        )

        plan = plan_diff(desired, live_objects, live_relations)
        print("===== Plan =====")
        plan.print()

        if args.dry_run:
            print("===== DRY-RUN — no changes applied =====")
            return 0

        if not plan.is_empty:
            print("===== Apply =====")
            apply_plan(client, plan, users_by_id)
            print("  applied.")
        else:
            print("===== Apply: nothing to do =====")

        print("===== Readback (positive control) =====")
        checked, failures = readback_verify(client, bundle)
        print(f"  checked={checked}  failures={failures}")
        if failures > 0:
            print(
                "FAIL: readback found asserted grants that don't "
                "resolve TRUE in topaz. The apply lied — investigate.",
                file=sys.stderr,
            )
            return 4

    print("===== SYNC OK =====")
    return 0


if __name__ == "__main__":
    sys.exit(main())
