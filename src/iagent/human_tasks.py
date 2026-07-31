"""HITL HumanTask substrate — registration, viewability, and resolution.

The queue is the enforcement model's FIFTH namespace (see policy/task_grants.yaml
+ the `task_audience` Topaz type). This module owns the WRITE path into the
Electric-replicated `human_task_projection` table and the Topaz interactions that
make the two viewability layers derive from ONE truth:

  register_task(audience, ...)
    -> ask Topaz for the audience's authorized ACTORS (directory relations)
    -> materialize ONE projection row per actor (recipient_id = that actor)
  the cortex-bff /electric/shape proxy then filters this table by
    recipient_id = <server-verified caller authz_id>
  and resolve_task(...) RE-CHECKS Topaz can_act before acting.

Because the rows exist BECAUSE Topaz authorized them, the Electric replication
filter (what a subscription receives) and the Topaz can_act gate cannot diverge.
recipient_id holds the AUTHZ IDENTITY (authz_id = the USER_ENTITLEMENT_CLAIM key
Topaz is seeded by — email in sandbox, employee-ID at work-deploy) used end-to-end,
which ELIMINATES the recurring sub<->email bridge (no mapping to mis-route) and
keeps the schema identity-key-agnostic (switching the key is a config change).

Postgres = the SAME Electric-replicated DB the projector writes (PROJECTOR_POSTGRES_DSN).
psycopg2 (sync) is the projector's dependency; the async gateway wraps these calls
in starlette.run_in_threadpool.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, Optional

import httpx
import psycopg2
import psycopg2.extras

# The Electric-replicated Postgres — same DSN the projector uses.
_PG_DSN = os.getenv("PROJECTOR_POSTGRES_DSN", "").strip()
# Topaz Directory (relations + check). Same URL cortex-bff uses for entitlements.
_TOPAZ_DIRECTORY_URL = os.getenv("TOPAZ_DIRECTORY_URL", "").strip()

# Authoritative migration (cortex-bff applies at startup; mirrors
# sql/create_human_task_projection.sql, kept in-module so the container has no
# file-path dependency). Idempotent.
_MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS human_task_projection (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    task_id TEXT NOT NULL,
    workflow_id TEXT,
    audience TEXT NOT NULL,
    recipient_id TEXT NOT NULL,
    status TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    subject_ref TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    acted_by TEXT,
    acted_at BIGINT,
    decision TEXT,
    comment TEXT,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_htp_recipient_id ON human_task_projection (recipient_id);
CREATE INDEX IF NOT EXISTS idx_htp_task_id ON human_task_projection (task_id);
CREATE INDEX IF NOT EXISTS idx_htp_status ON human_task_projection (status);
"""


class HumanTaskConfigError(RuntimeError):
    """Raised when the substrate is asked to operate without its backing config
    (PG DSN / Topaz URL). Fail LOUD — never silently no-op a security surface."""


class NoEntitledRecipients(RuntimeError):
    """Raised when a task is registered to an audience with ZERO Topaz-authorized actors.
    A task no one can act on can never complete — it would suspend the caller's workflow
    FOREVER, UNSEEN (the join-that-can-never-complete). Fail LOUD (a TERMINAL 4xx at the BFF,
    so the workflow releases rather than parks or retries). This is the misconfiguration class
    the initiator-plane NO_ENTITLED_ACTION used to catch when approver==reviewer; once initiate
    and review split (svc:review-starter initiates, humans review), it must be caught HERE, on
    the reviewer plane, uniformly for every task kind. Cure: grant the audience (task_grants.yaml)
    then re-drive."""


def _pg_connect():
    if not _PG_DSN:
        raise HumanTaskConfigError("PROJECTOR_POSTGRES_DSN is unset")
    return psycopg2.connect(_PG_DSN)


def apply_migration() -> None:
    """Create human_task_projection if absent. Called at cortex-bff startup.
    No-op (logged by caller) when PG DSN unset so local/dev boot doesn't crash."""
    with _pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(_MIGRATION_SQL)
        conn.commit()


# ── Topaz: the ONE authorization truth the two layers derive from ────────────

def _resolve_audience_actors(audience: str) -> list[str]:
    """Ask the Topaz Directory for the authz_ids granted `actor` on this audience —
    the authorized recipient set. Direct user grants only for v1 (group expansion
    deferred; the manifest allows group#member). Returns [] if none (deny-by-
    default: an ungranted audience yields NO rows -> invisible to everyone)."""
    if not _TOPAZ_DIRECTORY_URL:
        raise HumanTaskConfigError("TOPAZ_DIRECTORY_URL is unset")
    params = {
        "object_type": "task_audience",
        "object_id": audience,
        "relation": "actor",
    }
    with httpx.Client(base_url=_TOPAZ_DIRECTORY_URL, timeout=5.0) as c:
        r = c.get("/api/v3/directory/relations", params=params)
        r.raise_for_status()
        body = r.json()
    actors: list[str] = []
    for rel in body.get("results") or body.get("relations") or []:
        # subject is a user object; its id is the AUTHORIZATION identity (authz_id
        # — the USER_ENTITLEMENT_CLAIM key Topaz is seeded by: email in sandbox,
        # employee-ID at work-deploy). NOT necessarily an email.
        if (rel.get("subject_type") == "user") and rel.get("subject_id"):
            actors.append(rel["subject_id"])
    return actors


def check_can_act(audience: str, caller_id: str) -> bool:
    """Application-layer gate: re-check Topaz `can_act` for this caller on this
    audience at resolve time (defense in depth over the replication filter).
    `caller_id` is the authz_id (Topaz's key). Deny-by-default: any error or empty
    identity -> False."""
    if not caller_id or not _TOPAZ_DIRECTORY_URL:
        return False
    payload = {
        "object_type": "task_audience",
        "object_id": audience,
        "relation": "can_act",
        "subject_type": "user",
        "subject_id": caller_id,
    }
    try:
        with httpx.Client(base_url=_TOPAZ_DIRECTORY_URL, timeout=5.0) as c:
            r = c.post("/api/v3/directory/check", json=payload)
            r.raise_for_status()
            return bool(r.json().get("check"))
    except Exception:
        return False  # fail-closed


def check_can_invoke(capability: str, caller_id: str) -> bool:
    """Application-layer gate for an EFFECT: Topaz ``can_invoke(caller, capability)``
    on the ``capability`` namespace (the sixth; git-asserted in
    ``policy/capability_grants.yaml``). Same single decider and the same fail-closed
    posture as :func:`check_can_act` above — only the namespace differs, because
    INVOKING an effect is not ACTING on a task.

    Deny-by-default: an ungranted capability is "object not found" -> False, and any
    error -> False. Callers must treat a False as a REFUSAL THEY REPORT LOUDLY, never
    as a reason to skip quietly — a gate that silently swallows the thing it was
    guarding is the broken-closed failure, not a safety property.
    """
    if not capability or not caller_id or not _TOPAZ_DIRECTORY_URL:
        return False
    payload = {
        "object_type": "capability",
        "object_id": capability,
        "relation": "can_invoke",
        "subject_type": "user",
        "subject_id": caller_id,
    }
    try:
        with httpx.Client(base_url=_TOPAZ_DIRECTORY_URL, timeout=5.0) as c:
            r = c.post("/api/v3/directory/check", json=payload)
            r.raise_for_status()
            return bool(r.json().get("check"))
    except Exception:
        return False  # fail-closed


def task_exists(task_id: str) -> bool:
    """Has a logical task with this id already been registered (any recipient, any
    status)?

    Registration is NOT idempotent — :func:`register_task` inserts one row per actor
    unconditionally — so a caller that can fire twice for the same real-world event
    needs this check to stay at one task. Deliberately NOT scoped to a caller (unlike
    :func:`get_task_resolution`, which is existence-oracle-safe by scoping): this is
    asked by a SERVICE identity about a task id IT constructs from an artifact it can
    already read, so there is no queue to leak. Do not reuse it on a human path.
    """
    if not task_id:
        return False
    with _pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM human_task_projection WHERE task_id = %s LIMIT 1",
                (task_id,),
            )
            return cur.fetchone() is not None


# ── Registration (materialize rows from the Topaz decision) ──────────────────

def register_task(
    *,
    kind: str,
    task_id: str,
    audience: str,
    title: str,
    summary: str,
    requested_by: str,
    workflow_id: Optional[str] = None,
    subject_ref: Optional[str] = None,
    payload: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Register a HumanTask: resolve the audience's authorized actors from Topaz
    and materialize ONE projection row per actor. Returns {task_id, recipients}.

    CLEARANCE-BOUNDED: `title`/`summary`/`subject_ref`/`payload` must be
    clearance-SAFE (reference + summary, never compartmented content) — the
    projection row is visible to every authorized actor and must not leak content
    an actor authorized for the TASK is not cleared for.
    """
    actors = _resolve_audience_actors(audience)
    if not actors:
        # Zero entitled recipients: refuse LOUD, never materialize a task no one can act on (it would
        # park the caller's workflow forever, unseen). Raised BEFORE any DB touch so it is cheap and
        # test-verifiable without a database. The BFF maps this to a TERMINAL 4xx so the workflow
        # fails-and-releases; deny-by-default already routes an unreadable/empty audience here.
        raise NoEntitledRecipients(
            f"task {task_id!r} (kind={kind}) has ZERO entitled recipients for audience {audience!r} — "
            f"refusing to register a task no one can act on (grant the audience in task_grants.yaml, "
            f"then re-drive)"
        )
    now = int(time.time() * 1000)
    payload_json = json.dumps(payload or {})
    rows = []
    for actor_id in actors:
        rows.append((
            str(uuid.uuid4()), kind, task_id, workflow_id, audience, actor_id,
            "pending", title, summary, requested_by, subject_ref, payload_json,
            None, None, None, None, now, now,
        ))
    if rows:
        with _pg_connect() as conn:
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(
                    cur,
                    """INSERT INTO human_task_projection
                       (id, kind, task_id, workflow_id, audience, recipient_id,
                        status, title, summary, requested_by, subject_ref, payload,
                        acted_by, acted_at, decision, comment, created_at, updated_at)
                       VALUES %s""",
                    rows,
                )
            conn.commit()
    return {"task_id": task_id, "audience": audience, "recipients": actors}


def list_tasks_for(caller_id: str, *, status: str = "pending") -> list[dict[str, Any]]:
    """REST fallback / initial-load for the caller's queue (the live path is the
    Electric subscription). `caller_id` is the authz_id. Filters by recipient_id =
    caller — the SAME key the Electric proxy injects, so REST and streaming agree."""
    if not caller_id:
        return []
    with _pg_connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT id, kind, task_id, workflow_id, audience, status, title,
                          summary, requested_by, subject_ref, payload, created_at
                     FROM human_task_projection
                    WHERE recipient_id = %s AND status = %s
                    ORDER BY created_at DESC""",
                (caller_id, status),
            )
            return [dict(r) for r in cur.fetchall()]


# ── Case-1 fulfillment: write an asset_grants.yaml assertion + grant_sync ─────

_ASSET_GRANTS_FILE = os.getenv("ASSET_GRANTS_FILE", "/app/policy/asset_grants.yaml")
_GRANT_SYNC = os.getenv("GRANT_SYNC_PY", "/app/policy/sync/grant_sync.py")


def write_grant_and_sync(*, subject: str, asset: str, granted_by: str,
                         reason: str) -> dict[str, Any]:
    """Case-1 fulfillment: append a git-asserted reader grant to asset_grants.yaml
    (subject may READ asset, granted_by a named human) and flow it to Topaz via
    the SEALED grant_sync (reused VERBATIM — same validate/prove-the-negative/
    readback). Returns {ok, exit_code, output}.

    AUDIT NOTE (load-bearing, not hardening): the git-blame audit the grant core
    guarantees requires this asset_grants.yaml change to be COMMITTED TO GIT with
    the APPROVER as the author. This sandbox path writes the file + syncs to prove
    the deny->grant->allow loop; a grant that enforces WITHOUT a git commit is not
    git-blame-auditable = the unauditable grant the core forbids at classification.
    Committing (approver-attributed) is an AUDIT-COMPLETING REQUIREMENT before
    classification use, filed with real-grant-seeding-before-the-flip."""
    import yaml as _yaml
    import subprocess

    with open(_ASSET_GRANTS_FILE) as f:
        data = _yaml.safe_load(f) or {}
    grants = data.get("grants") or []
    # Idempotent: a duplicate (subject, asset) is a no-op, not a second grant.
    if not any(g.get("subject") == subject and g.get("asset") == asset for g in grants):
        grants.append({
            "subject": subject, "asset": asset,
            "granted_by": granted_by, "reason": reason,
        })
        data["grants"] = grants
        with open(_ASSET_GRANTS_FILE, "w") as f:
            # block style, no default_style — avoids the safe_dump block-scalar
            # flattening gotcha; the single-line reason needs no block scalar.
            _yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)

    env = dict(os.environ)
    env["ASSET_GRANTS_FILE"] = _ASSET_GRANTS_FILE
    env["PYTHONPATH"] = "/app/policy/sync:" + env.get("PYTHONPATH", "")
    if _TOPAZ_DIRECTORY_URL:
        env["TOPAZ_DIRECTORY_URL"] = _TOPAZ_DIRECTORY_URL
    proc = subprocess.run(
        ["python", _GRANT_SYNC], env=env, capture_output=True, text=True, timeout=60,
    )
    return {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,  # 0 ok · 2 malformed · 3 dangling · 4 readback
        "output": (proc.stdout or "")[-800:] + (proc.stderr or "")[-400:],
    }


def get_task_resolution(task_id: str, *, caller_id: str) -> Optional[dict[str, Any]]:
    """The resolution story of a task THIS caller was a recipient of, or None.

    Answers "did a TEAMMATE already resolve this?" so the caller gets an honest
    409-with-provenance instead of a misleading 404. Any-one-of-the-audience acts
    for the team (`mark_task_resolved` flips EVERY recipient row), so a teammate's
    action leaves the caller's own row non-pending — that row carries acted_by /
    acted_at / decision, which is the settled-provenance the reviewer must see.

    EXISTENCE-ORACLE SAFE BY SCOPING: filtered on `recipient_id = caller`, so it
    only ever speaks about a task the caller genuinely held. A caller who was never
    a recipient gets None — indistinguishable from "no such task", preserving the
    deny-by-default 404 and never revealing another audience's queue.
    """
    if not task_id or not caller_id:
        return None
    with _pg_connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT task_id, kind, status, decision, acted_by, acted_at, audience
                     FROM human_task_projection
                    WHERE task_id = %s AND recipient_id = %s
                    ORDER BY updated_at DESC
                    LIMIT 1""",
                (task_id, caller_id),
            )
            row = cur.fetchone()
    return dict(row) if row else None


# WHICH VERBS EACH TASK SPECIES ACCEPTS. A task kind's verbs are part of its meaning, not
# a UI choice: "approve" on *"this notice could not be prepared for review"* is not merely an
# awkward label, it records a decision the data cannot represent — and ADR-0034's decision
# records would then archive that nonsense IMMUTABLY, as evidence, into the corpus that governs
# promotion. So the vocabulary is declared HERE, next to the write, and a verb that does not
# belong to the kind is REFUSED rather than stored.
#
# Undeclared kinds keep the approve/reject default — that is the honest default for a task that
# IS a decision. The lesson from the triage bug is narrower and sharper than "register your
# kind": the old default was honest about LABELS ("TASK") and dishonest about AFFORDANCES
# (APPROVAL_TASK), because a label that says nothing is harmless and an affordance that says
# nothing still offers buttons.
#
# INTERIM — RETIRES AT M3.3, TOGETHER WITH cortex-ui's `taskKindRegistry`. This is the SECOND
# hardcoded per-kind table awaiting a served declaration, and the two must retire in one change:
# a `rendersAs` declaration that says how a task RENDERS while a code table still decides what it
# can DO is the worse half surviving. A step's verbs are the same kind of fact as its quorum and
# claiming — part of what the step MEANS — so they belong on `HumanAwaitStep`, inside the
# milestone's own north star ("quorum and claiming change by editing the YAML — zero code").
# They are here rather than there because the provenance bug could not wait for M3; see
# docs/plans/m3-grouped-review-definition-design.md §"TWO interim per-kind tables".
_VERBS_BY_KIND: dict[str, frozenset[str]] = {
    "extraction_refusal": frozenset({"acknowledged", "redriven"}),
}
_DEFAULT_VERBS = frozenset({"approved", "rejected"})

# Verbs whose meaning is empty without a stated reason. "Parts entered in the legacy system"
# and "notice withdrawn by the vendor" are entirely different facts about the pipeline, and a
# bare acknowledgement erases the difference — which is precisely the evidence ADR-0034 needs.
_REASON_REQUIRED = frozenset({"acknowledged"})


class InvalidDecisionForKind(ValueError):
    """The verb is not in this task species' vocabulary (or its reason is missing)."""


def verbs_for_kind(kind: str) -> frozenset[str]:
    return _VERBS_BY_KIND.get(kind, _DEFAULT_VERBS)


def validate_decision(kind: str, decision: str, comment: str = "") -> None:
    """PURE. Raise InvalidDecisionForKind unless `decision` is meaningful for `kind`."""
    allowed = verbs_for_kind(kind)
    if decision not in allowed:
        raise InvalidDecisionForKind(
            f"{decision!r} is not a valid action on a {kind!r} task — allowed: "
            f"{sorted(allowed)}. Recording it would write a decision the task's own "
            f"semantics cannot represent."
        )
    if decision in _REASON_REQUIRED and not (comment or "").strip():
        raise InvalidDecisionForKind(
            f"{decision!r} on a {kind!r} task REQUIRES a reason — an unexplained "
            f"acknowledgement erases the difference between the outcomes it covers."
        )


def mark_task_resolved(task_id: str, *, caller_id: str, decision: str,
                       comment: str = "") -> int:
    """Mark ALL recipient rows of a logical task resolved (one human acted for the
    audience). `caller_id` (authz_id) recorded as acted_by. Returns rows updated.
    Caller MUST have passed check_can_act first (and validate_decision).

    `status` carries the DECISION's own vocabulary rather than being coerced into
    approved/rejected: an acknowledged triage task was not "rejected", and a projection that
    says so is a lie the audit trail keeps. Only `pending` is load-bearing for queue queries;
    everything else is terminal, so widening the terminal vocabulary is safe."""
    now = int(time.time() * 1000)
    status = decision if decision in ("approved", "acknowledged", "redriven") else "rejected"
    with _pg_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE human_task_projection
                      SET status = %s, decision = %s, acted_by = %s, acted_at = %s,
                          comment = %s, updated_at = %s
                    WHERE task_id = %s AND status = 'pending'""",
                (status, decision, caller_id, now, comment, now, task_id),
            )
            n = cur.rowcount
        conn.commit()
    return n
