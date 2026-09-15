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
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Optional

import httpx
import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)

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
# docs/reference/m3-grouped-review-definition-design.md §"TWO interim per-kind tables".
# ── THE TWO PER-KIND CODE TABLES ARE GONE (M3.3 cutover, 2026-09-15) ────────────────────────
# `_VERBS_BY_KIND`, `_DEFAULT_VERBS` and `_REASON_REQUIRED` lived here. A declared row is now the
# ONLY source of what a species accepts and which of its verbs need a reason.
#
# THEY RETIRED TOGETHER, which was the standing ruling: a served declaration that says how a task
# RENDERS while a code table still decides what it can DO is the worse half surviving.
#
# WHAT REPLACED THE FALLBACK IS A REFUSAL, NOT A DEFAULT. The tables were what made an abstaining
# gate safe — "undeclared kinds keep today's verbs". With nothing behind the declaration,
# "I cannot know the set" must not silently become "this kind accepts nothing": that is a DEAD
# TASK, rendering as an ordinary card with no buttons and no error anywhere. So an unresolvable
# set now RAISES, naming the variable. A refusal is recoverable; a dead task is not visible.


def _seed_rows() -> dict:
    """The SEED rows alone, for when the overlay cannot be resolved.

    The seed ships in the image and is always readable; only the overlay half is ever unset,
    mistyped or unreadable. Keeping them separable is what lets a deployment accident degrade to
    "domain species unanswerable" instead of "every task in the fleet refused".
    """
    global _SEED_ROWS_CACHE
    if _SEED_ROWS_CACHE is not None:
        return _SEED_ROWS_CACHE
    try:
        from iagent_mesh.task_kinds import load_task_kinds  # noqa: PLC0415

        rows = {str(getattr(k, "kind", "")): k for k in load_task_kinds(_DECL_DIR)}
        _SEED_ROWS_CACHE = {k: v for k, v in rows.items() if k}
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not read the seed task kinds from %s (%s) — nothing can be "
                       "answered from the seed either", _DECL_DIR, exc)
        _SEED_ROWS_CACHE = {}
    return _SEED_ROWS_CACHE


_SEED_ROWS_CACHE: Optional[dict] = None


class TaskKindSetUnknown(RuntimeError):
    """The composed task-kind set could not be determined, so no verb question can be answered.

    Before the M3.3 cutover this state fell back to a code table. There is no table now, and the
    honest answer to "what does this species accept" when the set is unknowable is neither a
    verb list nor an empty one — it is a refusal that names what to configure.
    """


class InvalidDecisionForKind(ValueError):
    """The verb is not in this task species' vocabulary (or its reason is missing)."""


#: THE SEED HALF ONLY, AND THAT IS THE WHOLE PROBLEM WITH GATING ON IT ALONE.
#:
#: `policy/task_kinds/` ships STRUCTURAL species. Domain species live in a work-side ADR-0036
#: overlay and MAY NOT enter this repo — `test_no_domain_name_entered_the_platform_seed` fails
#: the build if one does. So a kind's absence from this directory is **required by the design**
#: rather than evidence nobody declared it.
_DECL_DIR = Path(__file__).resolve().parents[2] / "policy" / "task_kinds"

#: Where the deployment's OWN species are declared, colon-separated, from config. Absent in a
#: platform-only deployment — and absent means "this deployment has no domain species", which
#: is a different fact from "I was not told where to look". See `_declared_kinds`.
_OVERLAY_DIRS_ENV = "TASK_KIND_OVERLAY_DIRS"

#: `None` until read once. `frozenset()` would be indistinguishable from "read it and there
#: were none", which is the exact ambiguity the fallback below turns on.
_DECLARED_KINDS_CACHE: "frozenset[str] | None" = None

#: `kind -> the composed TaskKind row`. The DECLARATION is authoritative where it exists; the
#: code tables below are the fallback for kinds no declaration covers. Filled by
#: `_declared_kinds()` on the same pass, so membership and content can never disagree.
_DECLARED_ROWS: "dict[str, object]" = {}


def _declared_kinds() -> "frozenset[str] | None":
    """Every ratified task kind, or **None** if the declarations could not be read.

    NONE IS NOT AN EMPTY SET, AND CONFLATING THEM IS THE DANGEROUS DIRECTION HERE. An empty
    set means "nothing is declared", which makes every kind undeclared and refuses every
    decision in the fleet. A missing directory, an unreadable file or an absent SDK would
    then take the whole task rail down while looking like a security improvement.

    So an unreadable registry falls back to TODAY'S behaviour and says so loudly. That is the
    opposite of the `getenv`-default rule (R-012) on purpose: there, a default silently
    supplied a value nobody chose; here, refusing to default would silently withdraw an
    affordance everyone depends on. The asymmetry is which error is recoverable.

    THE SEED ALONE IS NOT THE SET, AND GATING ON IT REFUSED 18 OF 55 LIVE ROWS. Measured by
    `iagent-mesh-sdk-ca` against sandbox's `human_task_projection` before this reached master::

        grouped_review      25   in the seed        ok
        pcn_disposition     16   NOT in the seed    would have been REFUSED
        extraction_refusal   9   in the seed        ok
        workflow_ack         3   in the seed        ok
        pcn_grouped_review   2   NOT in the seed    would have been REFUSED

    `pcn_disposition` is minted live (`dispatch_plan.py:107`) and is absent from the seed
    **because the design requires it to be** — domain species live in a work-side overlay and
    a test fails the build if one enters this repo. **Refusing on absence from a partial set is
    a searched zero read as a structural zero**, and it is the same mistake as reading "not in
    a code table" as "not declared", one level up.

    SO THE GATE RESOLVES AGAINST THE COMPOSED SET, and **returns None when no overlay path is
    configured** — because then this process genuinely cannot tell "undeclared" from "declared
    somewhere I was not told to look", and in that state refusing is the dangerous direction.
    A deployment with no domain species composes to exactly the seed, so nothing changes for
    it; a deployment WITH them must say where they are before the gate can be trusted to fire.
    """
    global _DECLARED_KINDS_CACHE
    if _DECLARED_KINDS_CACHE is not None:
        return _DECLARED_KINDS_CACHE
    raw = (os.getenv(_OVERLAY_DIRS_ENV) or "").strip()
    if not raw:
        logger.warning(
            "%s is unset, so the task-kind set is the SEED HALF ONLY and cannot be trusted to "
            "be complete. SEEDED species still answer from their own rows; a DOMAIN species the "
            "seed does not carry is REFUSED, naming this variable — the code-table fallback that "
            "used to guess for it was deleted at the M3.3 cutover. Set it to the deployment's "
            "overlay directory (empty string is not the same as 'no domain species'; point it "
            "at an empty dir to assert there are none).",
            _OVERLAY_DIRS_ENV,
        )
        return None
    overlays = [p for p in (s.strip() for s in raw.split(os.pathsep)) if p]

    # A CONFIGURED PATH THAT IS NOT THERE IS UNREADABLE, NOT EMPTY — and `compose` will not
    # tell you. It composes a missing overlay directory to silence, so a TYPO in this variable
    # yields the seed set and the gate fires on it: exactly the 18-row outage, arriving through
    # a mistyped path instead of a missing feature. The difference between "you told me where
    # to look and there was nothing there" and "you told me where to look and the place does
    # not exist" is the whole safety property here, so it is checked rather than inferred.
    missing = [p for p in overlays if not Path(p).is_dir()]
    if missing:
        logger.warning(
            "%s names %s, which %s not exist — the declared set cannot be known, so undeclared "
            "kinds keep today's verbs. A path that is not there is UNREADABLE, not empty; "
            "point the variable at an existing (possibly empty) directory to assert this "
            "deployment has no domain species.",
            _OVERLAY_DIRS_ENV, missing, "does" if len(missing) == 1 else "do",
        )
        return None

    try:
        from iagent_mesh.task_kinds import compose  # noqa: PLC0415
        kinds = compose(_DECL_DIR, overlays)
        names = frozenset(str(getattr(k, "kind", "") or "") for k in kinds) - {""}
        if not names:
            logger.warning(
                "task-kind composition over %s + %s named nothing — treating the registry as "
                "UNREADABLE rather than empty. An empty registry and an unreadable one are "
                "not the same fact.",
                _DECL_DIR, overlays,
            )
            return None
        _DECLARED_ROWS.clear()
        for k in kinds:
            name = str(getattr(k, "kind", "") or "")
            if name:
                _DECLARED_ROWS[name] = k
        _DECLARED_KINDS_CACHE = names
        return names
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "could not compose task-kind declarations from %s + %s (%s: %s) — undeclared "
            "kinds keep today's verbs. This is a FALLBACK, not a decision: an unreadable "
            "registry must not refuse every decision in the fleet.",
            _DECL_DIR, overlays, type(exc).__name__, exc,
        )
        return None


def _ordered(verbs) -> "tuple[str, ...]":
    """A verb sequence, PRESERVING declaration order where the source has any.

    ONE RETURN TYPE FROM BOTH BRANCHES, WHICH IS THE POINT. `verbs_for_kind` reads either a
    declared row or a code table, and if those returned different container types a caller that
    worked in a deployment WITH an overlay would break in one without — a defect that only
    appears where nobody tests.

    ORDER IS PRESERVED WHERE IT EXISTS AND IMPOSED WHERE IT DOES NOT. Today the SDK stores
    `accepts` as a `frozenset`, so there is no declared order to keep and sorting is the only
    deterministic choice. SDK v0.8.0 makes it a `tuple` — at which point this function starts
    carrying the row's own order without another edit, which is why it is written this way
    BEFORE the pin rather than after. A `frozenset(...)` wrap here would have silently thrown
    the ordering fix away and left the bump looking applied.

    An unordered source is SORTED rather than passed through, and the reason is stronger than
    tidiness: **Python randomises string hashing per process**, so a frozenset of verbs iterates
    in a DIFFERENT order in every pod. Measured by `iagent-mesh-sdk-ca` across three interpreters
    on identical input::

        ('returned_for_rework', 'accepted', 'rejected')
        ('accepted', 'rejected', 'returned_for_rework')
        ('accepted', 'returned_for_rework', 'rejected')

    Passing it through would reshuffle a task card's buttons on every restart with nothing in the
    diff to explain it. Sorting is the only deterministic option available, not merely the tidier
    one. (This docstring previously said a frozenset's order was "arbitrary but not random" — the
    decision was right and the mechanism was wrong, which is the more durable kind of error: the
    code cannot fail, so the false premise survives to be reused somewhere the code WOULD fail.)
    """
    from collections.abc import Sequence  # noqa: PLC0415
    items = [str(v) for v in (verbs or ())]
    if isinstance(verbs, Sequence) and not isinstance(verbs, (str, bytes)):
        return tuple(items)          # ordered source: the declaration's own order
    return tuple(sorted(items))      # set-like: no order to keep, so impose a stable one


def verbs_for_kind(kind: str) -> "tuple[str, ...]":
    """The verbs this species accepts. **An UNDECLARED kind accepts nothing.**

    THE DEFECT THIS CLOSED. An unknown kind fell through to a code-table default and was handed
    `approved`/`rejected` — so a caller bypassing the card could dispose a species nobody
    declared. cortex-ui closed the render half (`21b2bae`: the verb block is gated on
    `isRegisteredKind`, which finally has a caller, and the fixture asserts `buttons()` is
    EMPTY). This is the gateway half, and until it lands the state is a UI offering nothing
    over an API that would still take the answer.

    FOR A RISK ACCEPTANCE THAT IS ADR-0051 §7's REFUSAL DEFEATED FROM OUTSIDE THE ENGINE:
    an acceptance reachable through a generic approval verb, with no authority tier and no
    required reason.

    **This makes no task deader than it already is on screen.** The card already offers
    nothing for these kinds; this stops the API accepting what the card refuses.

    THE TABLES ARE GONE (M3.3, 2026-09-15) AND THE DECLARATION IS THE ONLY SOURCE. While they
    stood, "not in `_VERBS_BY_KIND`" was not "not declared" — three of the four ratified kinds
    were absent from it and correctly rode its default. That distinction is what the cutover
    removed the need for.

    **THE DECLARATION IS AUTHORITATIVE WHERE IT EXISTS.** The first cut read the registry for
    MEMBERSHIP and never for CONTENT: a declared kind passed the gate and was then handed the
    generic vocabulary from the code table. Measured on the merged tree —
    `risk_acceptance_high` declares `accepted, rejected, returned_for_rework` and was given
    `approved, rejected`.

    **That is R-004(e)'s inversion, live.** A risk is ACCEPTED by an authority — MIL-STD-882's
    word — and `approved` is the generic seed's verb for generic things. The concurrence kinds
    were worse: `concurred` was refused outright, so §4.3.7's two-act sequence could not be
    performed through the gate at all.

    **BOTH HALVES HAVE LANDED.** The consumer half read the declaration while the tables still
    stood as a fallback; the cutover deleted them once cortex-ui-ba's parity seal was green on
    the pinned state. There is no fallback now, which is why an unresolvable set RAISES rather
    than returning nothing.
    """
    declared = _declared_kinds()
    if declared is None:
        # THE OVERLAY IS UNKNOWABLE — THE SEED IS NOT. Only the overlay half can be missing,
        # mistyped or unreadable; `policy/task_kinds/` ships in the image. So a SEEDED species
        # still answers from its own row, and only a kind the seed does not cover is genuinely
        # unanswerable. Refusing everything here would take every task in the fleet down over a
        # typo in one variable — the exact accident an existing seal was written to prevent, and
        # deleting the code table must not reintroduce it by the back door.
        row = _seed_rows().get(kind)
        if row is not None:
            return _ordered(getattr(row, "accepts", None) or ())
        raise TaskKindSetUnknown(
            f"cannot answer what {kind!r} accepts: it is not in the seed, and the overlay is "
            f"unknown because {_OVERLAY_DIRS_ENV} is unset or unreadable. Before the M3.3 "
            f"cutover this fell back to a code table; there is none now. Point the variable at "
            f"the deployment's overlay directory, or at an empty directory to assert there are "
            f"no domain species."
        )
    if kind not in declared:
        # `()` NOT `frozenset()`. This branch was missed when the others became tuples, and
        # a function returning two container types depending on which branch it takes is the
        # defect iagent-mesh-sdk-ca flagged for the pin — a caller that works in a deployment
        # WITH an overlay breaking in one without. Found by printing the type, not by reading.
        return ()
    row = _DECLARED_ROWS.get(kind)
    if row is not None:
        declared = getattr(row, "accepts", None)
        if declared:
            return _ordered(declared)
        # A row declaring NO verbs is a declaration nobody can act on. Falling back to the
        # table here would hand it the generic pair and call that the row's meaning.
        return ()
    # NO FALLBACK. A kind inside the composed set with no row is a contradiction, not a
    # default: `declared` IS the set of kinds with rows.
    return ()


def reason_required_for(kind: str) -> frozenset[str]:
    """Verbs whose meaning is empty without a stated reason, for THIS species.

    Same precedence as `verbs_for_kind`: the declaration where it exists, the kind-blind global
    set otherwise. R-004(b) makes BOTH `accepted` and `rejected` reason-required on the safety
    rows, which the global set cannot express — it is kind-blind, so adding `rejected` there
    would change three other species' behaviour from the safety lane. That limitation is the
    argument for the cutover, and this is the half of it that needs no parity seal.
    """
    # LOAD THE ROWS BEFORE READING THEM. `_DECLARED_ROWS` is filled as a side effect of
    # `_declared_kinds()`, so calling this function FIRST — before any `verbs_for_kind` — read
    # an empty dict and silently returned the kind-blind global set. An ordering dependency
    # that produces a plausible answer rather than an error, found by this function's own seal.
    if _declared_kinds() is None:
        row = _seed_rows().get(kind)
        if row is not None:
            return frozenset(str(v) for v in (getattr(row, "reason_required", None) or ()))
        raise TaskKindSetUnknown(
            f"cannot answer which of {kind!r}'s verbs need a reason: it is not in the seed, and "
            f"the overlay is unknown because {_OVERLAY_DIRS_ENV} is unset or unreadable"
        )
    row = _DECLARED_ROWS.get(kind)
    if row is None:
        return frozenset()
    return frozenset(str(v) for v in (getattr(row, "reason_required", None) or ()))


def validate_decision(kind: str, decision: str, comment: str = "") -> None:
    """PURE. Raise InvalidDecisionForKind unless `decision` is meaningful for `kind`."""
    allowed = verbs_for_kind(kind)
    if decision not in allowed:
        raise InvalidDecisionForKind(
            f"{decision!r} is not a valid action on a {kind!r} task — allowed: "
            f"{sorted(allowed)}. Recording it would write a decision the task's own "
            f"semantics cannot represent."
        )
    if decision in reason_required_for(kind) and not (comment or "").strip():
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

    # ── THE DECISION IS THE STATUS ──────────────────────────────────────────────────────────
    #
    # ⛔ THIS COERCED EVERY UNLISTED VERB TO "rejected", four lines below a docstring that says
    # it must not: *"a projection that says so is a lie the audit trail keeps."* The rule was
    # WRITTEN and not implemented, and the allowlist happened to cover exactly the verbs that
    # existed when it was typed.
    #
    # MEASURED 2026-09-15 against the composed declaration: THIRTEEN verbs are declared and the
    # allowlist named THREE. So `accepted`, `concurred`, `not_concurred`, `returned_for_rework`,
    # `linked`, `new_hazard`, `dismissed`, `redrafted` and `withdrawn` all stored as REJECTED —
    # and under ADR-0051 a risk ACCEPTANCE recorded as its opposite is the one act whose record
    # IS the evidence.
    #
    # Latent rather than bleeding when found: zero safety verbs had been resolved, so every
    # existing row still agrees. Fixed in that state deliberately — "the walk found it" is a
    # worse morning than "the walk confirmed it was fixed".
    #
    # WHY WIDENING IS SAFE, and it is the docstring's own argument: only `pending` is
    # load-bearing for queue queries; everything else is terminal.
    if decision == "pending":
        # THE ONE VALUE THAT IS NOT TERMINAL. A species declaring `pending` as a verb would
        # make a resolved task indistinguishable from an open one and it would rejoin every
        # queue — so this refuses rather than writing it. Unreachable through `validate_decision`
        # (a declaration would have to name it), which is exactly why it is asserted here: the
        # guard is against a future declaration, not against today's callers.
        raise ValueError(
            "'pending' cannot be a resolution: it is the only status the queue reads as OPEN, "
            "and storing it would return a resolved task to every queue that skips it."
        )
    status = decision
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


def declaration_for(kind: str) -> "dict[str, Any]":
    """The READ PATH for a species' contract: what it accepts, in order, and how to render it.

    WHY THIS EXISTS, and it is a gap I left. The consumer half made the declaration AUTHORITATIVE
    — `verbs_for_kind` returns the composed row's `accepts` — and then exposed it **nowhere**.
    `cortex-ui-60` measured it in the serving pod: `verbs_for_kind` appears exactly ONCE in
    `gateway.py`, inside the body returned when `validate_decision` REFUSES.

    **So the only way a client could learn what a species accepts was to POST A VERB AND BE TOLD
    IT WAS WRONG.** That is discovery-by-failure, and on this surface it is not merely inelegant:
    ADR-0034 archives decision records, so probing to learn a menu **writes attempted decisions
    nobody made.** A read path is the difference between a contract and a trapdoor.

    IT ALSO MAKES A CLAIM OF MINE FALSE, WHICH IS THE PART WORTH KEEPING. I reported *"55 live
    rows across 4 kinds, 0 unactionable"* after the roll. **True of the API and false of the
    surface**: cortex holds a hardcoded `taskKindRegistry` and refuses every `risk_acceptance_*`
    species as unregistered, drawing no buttons at all. Given no read path, **refusing was the
    correct behaviour** — the hardcoded table is only the reason it was also the *only* behaviour.
    An actionability claim measured at the API is not a claim about what a person can do.

    THE SHAPE IS DELIBERATELY THIN: `{kind, archetype, badge, title, accepts, reason_required}`.
    `accepts` is a LIST IN THE DECLARATION'S ORDER — v0.8.0's tuple is what makes that meaningful,
    and a client renders buttons in that order. `reason_required` is a SORTED list because it is a
    membership test and order is meaningless for it; that asymmetry is deliberate in the SDK model
    and is preserved here rather than flattened for symmetry's sake.

    AN UNDECLARED KIND RETURNS `accepts: []` AND `declared: False` — not an error and not a
    fallback menu. A client that renders nothing for it is doing the right thing, and the flag
    lets it say *why* rather than guessing.
    """
    row = _DECLARED_ROWS.get(kind)
    if row is None:
        _declared_kinds()                      # populate, then look again
        row = _DECLARED_ROWS.get(kind)
    verbs = verbs_for_kind(kind)
    renders = getattr(row, "renders_as", None) if row is not None else None

    def _r(field: str) -> "str | None":
        if renders is None:
            return None
        if isinstance(renders, dict):
            return renders.get(field)
        return getattr(renders, field, None)

    return {
        "kind": kind,
        "declared": row is not None,
        "archetype": _r("archetype"),
        "badge": _r("badge"),
        "title": _r("title"),
        # ORDER IS THE CONTRACT. `list(...)` not `sorted(...)` — re-sorting here reproduces the
        # defect v0.8.0 was cut to fix, one surface further out, and it would look like tidiness.
        "accepts": list(verbs),
        # SORTED ON PURPOSE: a membership test has no order to carry.
        #
        # AND INTERSECTED WITH `accepts`, WHICH THE FIRST VERSION OF THIS DID NOT DO. It returned
        # the kind-blind global set for an UNDECLARED kind, so `risk_acceptance` came back with
        # `accepts: []` and `reason_required: ["accepted", "acknowledged"]` -- TWO VERBS REQUIRED
        # TO CARRY A REASON ON A SPECIES THAT ACCEPTS NOTHING. A rule that can never fire, and a
        # client reading it would render a reason field for verbs it can never submit.
        # `test_reason_required_is_a_subset_of_accepts_on_every_safety_row` already asserts this
        # invariant over the declared ROWS; the READ PATH has to honour it too, or the seal is
        # true of the data and false of what is served.
        "reason_required": sorted(reason_required_for(kind) & set(verbs)),
    }


def decorate_with_declarations(tasks: "list[dict[str, Any]]") -> "list[dict[str, Any]]":
    """Attach each row's own declaration under `declaration`, so a client never has to guess.

    Nested rather than flattened onto the row: a task row's columns come from the projection and
    this comes from the composed registry. Merging them would make a later reader unable to tell
    which fields are FACTS ABOUT THIS TASK from which are FACTS ABOUT ITS SPECIES — and only the
    first kind can differ between two rows of the same kind.

    Computed per unique kind, not per row: 55 rows across 4 kinds is 4 lookups.
    """
    cache: "dict[str, dict[str, Any]]" = {}
    for t in tasks:
        k = str(t.get("kind") or "")
        if k not in cache:
            cache[k] = declaration_for(k)
        t["declaration"] = cache[k]
    return tasks
