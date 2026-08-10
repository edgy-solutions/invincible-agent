"""PCN/PDN review STARTER — the explicit entry that composes a notice into a running grouped review.

Wiring by construction over the sealed cores: fetch the ruleset (from the graph — source-authority),
compose the server-authored batch ([[review_composer]]), and start the [[grouped_review_workflow]]
``GroupedReview`` workflow. Triggered by an EXPLICIT invocation carrying the notice reference — no
watcher, no trigger mechanism (M1 ends at "durable task exists"; the demo drives one notice,
``IPCN25300X``, by hand).

The composition is pure given three injected seams; ``build_review_from_request`` seals against the
same real-shaped fixture as the seam-diff seal. The seams swap to live adapters at deploy — and both
were RESOLVED GENERIC per the generic-at-birth rule (AGENTS.md): new surface never carries a domain
name, so neither seam mints pcn-named surface:

  * ``resolve_subject`` -> ``resolve_subject_via_engine_o`` (LIVE; exists).
  * ``load_policy_rules`` -> BUILT, born generic. The generic ``[[policy_rules_client]]`` fetches
    engine-o ``POST /policy_rules {graph, ruleset_label}`` (which serves the rule subgraph as Turtle —
    engine-o interprets nothing) and loads + validates it. ``start_review`` surfaces the four failure
    modes honestly: ``not_found`` -> RULES_NOT_FOUND, ``invalid`` -> RULESET_INVALID (report-don't-
    reject: no dispatch under a corrupt ruleset), ``empty`` -> abstains -> NO_RESIDUE, ``ok`` -> build.
    NOT a pcn-named route — the domain is the ``graph`` argument.
  * ``can_act``         -> WIRED onto WORK'S EXISTING ``task_audience`` HITL mechanism (single-decider):
    a grouped review is a HITL task; "who may act on a class of HITL tasks in a compartment" IS
    ``task_audience`` (key ``disposition_review:<domain>``, permission ``can_act``, grantable direct or via
    group). Direct Topaz DIRECTORY check, deny-by-default; grants arrive by the git-rails seed CronJob
    (`task_grants.yaml`), never hand-surgery. Reading work's rails RETIRED the bespoke ``disposition_item``
    type + rego (they were reinventing this). Still deploy-gated (needs the seed + the grants).

The notice's affected parts + needs_review flags are the doc-tools EXTRACTION, passed in the request
(the upstream producer); the starter does not re-extract. Scope (BOM/AVL ``in_scope_mpns``) is an input.
"""
from __future__ import annotations

import hashlib
import os
from typing import Callable, Optional

import restate
from restate import Context, Service

try:  # lazy-import dance (container flattens the dir)
    from review_composer import build_review_batch, resolve_subject_via_engine_o  # type: ignore[no-redef]
    from grouped_review_workflow import batch_items_to_state  # type: ignore[no-redef]
    from grouped_review_workflow import run as grouped_review_run  # type: ignore[no-redef]
    from autonomous_review_workflow import run as autonomous_review_run  # type: ignore[no-redef]
    from policy_rules_client import fetch_policy_rules  # type: ignore[no-redef]
    from orchestrator.auth import current_trace_id  # type: ignore[no-redef]
except ImportError:  # pragma: no cover - import path differs by runtime
    from agent_fleet.restate_analyst.review_composer import build_review_batch, resolve_subject_via_engine_o
    from agent_fleet.restate_analyst.grouped_review_workflow import batch_items_to_state
    from agent_fleet.restate_analyst.grouped_review_workflow import run as grouped_review_run
    from agent_fleet.restate_analyst.autonomous_review_workflow import run as autonomous_review_run
    from agent_fleet.restate_analyst.policy_rules_client import fetch_policy_rules
    from agent_fleet.restate_analyst.orchestrator.auth import current_trace_id

# ADMISSION POLICY (ADR-0034 phase 1.3). Lives in `agent_fleet/utils/` — the ONE tree BOTH runtimes
# carry — because engine-a's image has no `src/`, so `iagent.trust_table` was unreachable from here.
# Same relocation, same reason, as `utils/service_identity.py`.
try:
    from utils.trust_table import (  # type: ignore[no-redef]
        DEFAULT_RUNG, MONITORED, TRUSTED, load_trust_table,
    )
    from utils.artifact_provenance import (  # type: ignore[no-redef]
        ArtifactUnreadable, derive_provenance,
    )
except ImportError:  # pragma: no cover - import path differs by runtime
    from agent_fleet.utils.trust_table import (
        DEFAULT_RUNG, MONITORED, TRUSTED, load_trust_table,
    )
    from agent_fleet.utils.artifact_provenance import (
        ArtifactUnreadable, derive_provenance,
    )

# Telemetry (ADR-0038): baml_shared is on sys.path (the analyst app adds it at startup).
# Guarded so the ReviewStarter runs identically when the shim/leaf is absent (no-op
# primitives) — the witness channel never breaks the composition.
try:
    from telemetry import observed_trace, build_trace_values, MAPPING  # type: ignore[no-redef]
except Exception:  # pragma: no cover — telemetry is never load-bearing
    from contextlib import contextmanager as _cm

    @_cm
    def observed_trace(*_a, **_k):  # type: ignore[misc]
        yield

    def build_trace_values(**_k):  # type: ignore[misc]
        return {}

    MAPPING = None

ENGINE_O_URL = os.getenv("ONTOLOGY_SERVICE_URL", "http://iagent-engine-o:8084")
_HTTP_TIMEOUT = float(os.getenv("AGENT_HTTP_TIMEOUT", "30"))


# ---------------------------------------------------------------------------
# The composition — pure given the three seams (seals against the shared fixture)
# ---------------------------------------------------------------------------
def build_review_from_request(
    request: dict,
    *,
    ruleset: list,
    category_classes: dict,
    ruleset_ref: str,
    resolve_subject: Callable[[str], Optional[str]],
    can_act: Callable[[str, object], bool],
) -> dict:
    """Compose ONE notice's request into the serialized batch the workflow consumes, given an
    ALREADY-LOADED ruleset (loading + validation happened upstream in the policy-rules client, so a
    corrupt/absent ruleset never reaches here). Pure given the two seams — the same real-shaped
    IPCN25300X fixture the seam-diff seal uses drives it. Returns batch_items (JSON-native), funnel
    counts (conservation observable), ruleset_ref, and the resolved/unresolved residue-subject tally."""
    build = build_review_batch(
        impacted_parts=request["impacted_parts"],
        doc_type=request["doc_type"],
        categories=request.get("categories"),
        in_scope_mpns=set(request.get("in_scope_mpns") or []),
        ruleset=ruleset,
        category_classes=category_classes,
        ruleset_ref=ruleset_ref,
        approver=request["approver"],
        resolve_subject=resolve_subject,
        can_act=can_act,
    )
    return {
        "batch_items": batch_items_to_state(build.batch),
        "counts": build.funnel.counts(),
        "ruleset_ref": ruleset_ref,
        "resolved": build.resolved,
        "unresolved": build.unresolved,
    }


# ---------------------------------------------------------------------------
# Live seams
# ---------------------------------------------------------------------------
_RULESET_GRAPH = os.getenv("PCN_SUSTAINMENT_GRAPH", "SUSTAINMENT")
# Caller-DECLARED ruleset label (rides into ruleset_ref = <label>@<content-hash>). Matches the pcn/rules
# ontology's local name; declared not sniffed, so co-tenant vocabulary in the graph can't perturb it.
_RULESET_LABEL = os.getenv("PCN_RULESET_LABEL", "rules")
# The caller's registered actions (its domain vocab) — enables the registration check at load time.
_KNOWN_DISPOSITIONS = ["dispatchQualification", "dispatchLTB", "dispatchAltSourcing", "archive"]


def load_policy_rules() -> dict:  # pragma: no cover - deploy-gated (live engine-o fetch)
    """Fetch + load + validate the ruleset via the GENERIC policy-rules client (engine-o serves Turtle
    from the named graph; the client interprets it — source-authority, the domain is the ``graph``
    argument). Returns the client's dict incl. ``status`` (not_found/empty/invalid/ok) + validity."""
    return fetch_policy_rules(_RULESET_GRAPH, _RULESET_LABEL, known_dispositions=_KNOWN_DISPOSITIONS)


TOPAZ_DIRECTORY_URL = os.getenv("TOPAZ_DIRECTORY_URL", "http://topaz-svc:9393")
# Independent dark-launch toggle for the review-START authz gate. NOT the terminal ENABLE_AGENTIC_AUTH
# (whose flip turns on EVERY dark-launched content gate cluster-wide, irreversibly). It gates WHO may
# INITIATE a review — capability can_invoke(mesh:startReview) — so it gets its OWN toggle: dark until the
# capability grant is seeded (capability_grants.yaml), then flipped for this gate alone. Off -> no-op True
# (like the other gates when their flag is off). (Name kept as ENABLE_DISPOSITION_AUTHZ to avoid deploy-env
# churn mid-flight — it has always been the review-start authz switch.) WHO may REVIEW is a SEPARATE gate
# that lives at the HITL task layer (task_audience disposition_review:<compartment>, enforced at task
# registration + /act) — not here. Conflating "may initiate" with "is a reviewer" was the latent bug the
# first non-human initiator (svc:review-starter) exposed; this split is its repair.
ENABLE_DISPOSITION_AUTHZ = os.getenv("ENABLE_DISPOSITION_AUTHZ", "false").lower() in ("true", "1", "yes")

# The capability a review INITIATOR must be able to invoke. Starting a review is invoking mesh:startReview
# (an EFFECT), gated on the SAME single decider as every direct_call (ADR-0029 capability `can_invoke`,
# the SIXTH namespace — capability_grants.yaml). svc:review-starter is its first non-human invoker.
MESH_START_REVIEW = "mesh:startReview"


def can_invoke_start_review(initiator: str) -> bool:  # pragma: no cover - live Topaz (discrimination seal)
    """Topaz predicate for the review INITIATOR: capability ``can_invoke(initiator, mesh:startReview)``.

    Starting a review INVOKES a capability; it does not ACT on a HITL task — so the initiator is gated in
    the CAPABILITY namespace (capability_grants.yaml → capability_grant_sync.py), deny-by-default. This is
    deliberately DISTINCT from who may REVIEW (the human ``task_audience`` ``disposition_review:<compartment>``,
    enforced downstream at task registration + /act): a service identity may initiate without ever being a
    reviewer, and a reviewer needn't be able to initiate. Direct Topaz DIRECTORY check; an ungranted
    capability is "object not found" -> deny.

    No-op True when ``ENABLE_DISPOSITION_AUTHZ`` is off (its OWN dark-launch toggle, not the terminal
    ENABLE_AGENTIC_AUTH flip). Any error / not-found -> deny (a gate must not fail open)."""
    if not ENABLE_DISPOSITION_AUTHZ:
        return True
    if not initiator:
        return False
    try:
        import requests
        resp = requests.post(
            f"{TOPAZ_DIRECTORY_URL}/api/v3/directory/check",
            headers={"Content-Type": "application/json"},
            json={"object_type": "capability", "object_id": MESH_START_REVIEW, "relation": "can_invoke",
                  "subject_type": "user", "subject_id": initiator},
            timeout=5.0,
        )
        resp.raise_for_status()
        return bool(resp.json().get("check", False))   # absent/not-found/error -> deny (fail-closed)
    except Exception:  # noqa: BLE001 — fail-closed (deny) on any error, like the ontology gate
        return False


def compose_workflow_id(notice_id: str, approver: str, request_key: Optional[str] = None) -> str:
    """The grouped review's Restate workflow key. PURE, so its properties are testable.

    RESTATE WORKFLOW KEYS ARE SINGLE-USE. A key can be submitted exactly once, ever; a second
    ``workflow_send`` to the same key does nothing — and because that send is fire-and-forget,
    ``start_review`` still returns STARTED. Combine that with a key derived from ``notice_id``
    (the LLM-extracted doc_id) and two failures compound into one silent, permanent one:

      * TWO DOCUMENTS SHARING A doc_id collapse into ONE review — a real hazard, since doc_id
        degrades to a shared fallback exactly when extraction is going wrong.
      * A NOTICE WHOSE FIRST ATTEMPT DIED can never produce a review again. The key is spent,
        re-extraction cannot change it (the header pass yields the same doc_id), and every
        retry logs STARTED. Live at work 2026-07-31: eleven notices, eleven STARTED, ONE
        review — the other ten permanently unrecoverable without hand-editing doc_ids.

    So the key carries the ARTIFACT's identity (ETag + s3 key, hashed) as a discriminator —
    the same identity the sensor's run_key, the triage task_id and the ingress idempotency key
    already use. FOURTH enforcement point of one rule: identity comes from what the artifact
    IS and where it lives, never from a value a model derived.

    What each case now does:
      * same artifact re-sent      -> same key -> correctly idempotent, no duplicate review
      * RE-EXTRACTION (new bytes)  -> new key  -> a genuinely new review, which is the point:
                                      a corrected extraction must be reviewable, and today it
                                      silently is not
      * two docs, one doc_id       -> different keys -> no collision

    `notice_id` stays in the key as a HUMAN-READABLE prefix: these keys are read in Restate's
    UI and in logs during incidents, and an opaque hash would have made this very bug harder
    to see. Readability is the reason it is there — it is no longer load-bearing for identity.

    NO request_key (the hand-driven ops/re-drive path) falls back to the old shape. That path
    is then subject to the single-use constraint, exactly as before — honest rather than
    silently uniquified, and the same choice the ingress key makes when it cannot name an
    artifact.
    """
    base = f"pcn-review-{notice_id}-{approver}"
    rk = (request_key or "").strip()
    if not rk:
        return base
    return f"{base}-{hashlib.sha1(rk.encode()).hexdigest()[:10]}"


ESCALATION_MARKER = "escalated-from"


def escalation_request_key(request_key: str, refusing_invocation_id: str) -> str:
    """The request_key an ESCALATED admission carries — derived, never reused.

    THE TRAP THIS EXISTS TO AVOID, in production shape. When an autonomous run refuses (a
    `needs_review` row, a row with no disposition) the notice must reach a human, and the honest way
    is a fresh admission through the front door — same `ReviewStarter`, full provenance, real
    audience. But the BFF derives its ingress idempotency key from `(request_key, approver)`, and an
    escalation naturally carries the SAME artifact key and the SAME `svc:review-starter` as the
    autonomous admission that just refused. Restate would therefore ATTACH the escalation to the
    prior invocation and hand back the AutonomousReview's own result: the escalation silently
    swallowed, the notice dropped, nothing red.

    That is not a hypothetical — it is the leg-3 collision from the phase-1.3 witness, where two legs
    differing only in table state shared an artifact and the second returned the first's answer. It
    was caught there by a readback naming the wrong notice, not by anything going red.

    So the escalated admission mints a DERIVED identity: the original key plus a marker naming the
    refusing invocation. Same repair pattern as the dispatch re-arm's attempt suffix (`…#a2`) — a
    genuinely new admission that still POINTS BACK, so the decision record can carry the chain
    (`admitted_by: escalation`, the refusing run, the rule that refused) instead of a fresh identity
    with no history.

    Deterministic and idempotent BY CONSTRUCTION: escalating the same refusing run twice yields the
    same key, so a workflow replay re-escalates onto the same admission rather than minting a second
    review for one notice. Re-derivation is safe; that is the property Restate replay requires.
    """
    base = (request_key or "").strip()
    inv = (refusing_invocation_id or "").strip()
    if not inv:
        # An escalation that cannot name its refusing run would be indistinguishable from a fresh
        # admission — and would collide with it. Refuse rather than mint an ambiguous identity.
        raise ValueError(
            "escalation_request_key needs the REFUSING invocation id: without it the derived key "
            "collapses onto the original admission's key and the escalation is swallowed by ingress "
            "idempotency (the leg-3 collision, in production shape)."
        )
    if not base:
        # No original key (the hand-driven ops path). Still derive something distinct and traceable.
        return f"{ESCALATION_MARKER}:{inv}"
    return f"{base}|{ESCALATION_MARKER}:{inv}"


def _no_reviewer_filter(approver: str, item) -> bool:
    """The per-item reviewer filter injected into grouped_review. TODAY the identity function: the single
    review audience (``disposition_review:<compartment>``) has no COMPOSITION-time per-item differential, so
    every residue item flows into the batch for the audience to triage; who may REVIEW is enforced at the
    HITL task layer (register_task materializes one row per audience actor, refusing a zero-recipient task;
    /act re-checks). NB the Slice-3 grouped-review filter already handles the per-approver VIEW (redacting a
    reviewer's OWN batch); THIS hook is a distinct COMPOSITION-time differential with no consumer yet.

    NAMED WAKER — replace this pass-through with a real predicate when EITHER: (a) a single batch spans
    multiple compartments (items carrying different reviewer audiences composed together), or (b) reviewer-
    specific redaction WITHIN one audience becomes real. When it wakes, the predicate is keyed on the
    REVIEWER audience — NEVER the initiator (that conflation was the bug this split repaired; the initiator
    is gated once, coarsely, by can_invoke above). ``grouped_review`` stays the genuine per-item filter,
    ready for it. The trigger is spelled out on purpose: a named waker survives a tidy-minded pass; a vague
    'TODO: filtering' gets deleted into a bug."""
    return True


# ---------------------------------------------------------------------------
# Review-state sourcing tripwire — laundering-by-substrate-gap guard (STANDING INVARIANT)
# ---------------------------------------------------------------------------
# The one attestation value that disarms the review-state tripwire: per-part flags read
# STRAIGHT FROM the doc-tools extraction (review.json), where they are authoritative.
# A request built from the lossy graph simply cannot honestly set this.
_REVIEW_STATE_FROM_EXTRACTION = "extraction"


def review_state_is_unsourced(doc_needs_review, impacted_parts, review_state_source=None) -> bool:
    """The laundering-by-substrate-gap signature. Per-part ``needs_review`` exists ONLY in the extraction
    (`review.json`) — BOTH graphs drop it (doc-tools writes only the DOC-LEVEL flag to Neo4j; Jena drops
    it entirely). So the request MUST be built from the extraction, never the mesh graph. The tripwire:
    if the DOC-LEVEL flag says "something here needs review" (``doc_needs_review`` True) but NO part
    carries ``needs_review`` True, the per-part flags were NOT sourced — the request was built from a
    lossy graph projection, and every downstream §3 laundering seal (UNVERIFIED badge → accept-all
    exclusion → override-with-reason) would fire CLEAN on an unverified MPN. That defeats five sealed
    layers without touching any of them. Standing rule: EXTRACTION is authoritative for review-state;
    [[feedback_synthetic_data_no_mock_leak]] one layer up. ``doc_needs_review`` is None/absent -> can't
    check (no-op); the request builder MUST pass it (from the extraction / Neo4j doc-level) to arm this.

    POSITIVE ATTESTATION beats silhouette-inference (2026-07-29). The shape {doc flagged, no part
    flagged} was only ever a PROXY for "built from the graph" — and it collides with legitimate
    outcomes of a CORRECT extraction: a doc-level-only reason (unclassifiable doc_type, header
    failure, a count cross-check) flags the document while every part extracts cleanly, and a
    zero-part notice trips it VACUOUSLY (`not any([])` is True). That false-positive class refused
    real notices outright (Qorvo 23-0171: a misparsed count number -> doc flagged -> both parts
    clean -> refused). So the caller now ATTESTS where review-state came from:
    ``review_state_source="extraction"`` means the per-part flags were read from review.json, where
    they are authoritative — no laundering is possible, so the check does not apply. The tripwire
    fires only when that attestation is ABSENT, which is exactly the graph-built request it was
    written to catch. Same guard, same purpose, no false positives: a wiring mistake now has to
    OMIT a declaration rather than merely produce an ambiguous silhouette."""
    if review_state_source == _REVIEW_STATE_FROM_EXTRACTION:
        return False
    if not doc_needs_review:
        return False
    return not any(bool(p.get("needs_review")) for p in (impacted_parts or []))


# ---------------------------------------------------------------------------
# The durable entry handler
# ---------------------------------------------------------------------------
review_starter = Service("ReviewStarter")


@review_starter.handler()
async def start_review(ctx: Context, request: dict) -> dict:
    """Explicitly-invoked: compose a notice into a batch and START the grouped-review workflow.

    request: ``notice_id``, ``doc_type``, ``categories``, ``impacted_parts`` (doc-tools extraction),
    ``in_scope_mpns``, ``approver``, ``audience``, ``user_jwt``, and ``doc_needs_review`` (the
    extraction's DOC-LEVEL flag — arms the review-state tripwire). The build runs in one journaled
    ``ctx.run`` step (reads only — resolveInstance/Topaz/rules-fetch — so a crash re-runs it
    idempotently); the only durable effect is starting the workflow (idempotent on its id). If nothing
    reaches residue, return ``NO_RESIDUE`` honestly — no workflow, no empty task."""
    notice_id = request["notice_id"]
    approver = request["approver"]

    # Adopt the doc-tools extraction trace id (threaded from review.json via the sensor +
    # gateway) into the request-scoped trace contextvar, so composition steps that become
    # trace-aware key on the SAME trace as the extraction — one trace bucket -> extraction
    # -> review (ADR-0038). Contextvar, not an env var: safe under concurrent requests.
    # (The Langfuse-visible join lands when the composition itself is instrumented; the id
    # is threaded and adopted here, ready for it.)
    _trace_id = request.get("trace_id")
    if _trace_id:
        try:
            current_trace_id.set(_trace_id)
        except Exception:  # noqa: BLE001 — telemetry never breaks the compose
            pass

    # 0) Review-state sourcing tripwire (BEFORE anything else): a request whose doc-level flag says
    #    "needs review" but whose parts carry no per-part flag was built from a lossy graph projection —
    #    refuse rather than launder an unverified MPN through five sealed layers.
    if review_state_is_unsourced(request.get("doc_needs_review"), request.get("impacted_parts"),
                                 request.get("review_state_source")):
        return {"status": "REVIEW_STATE_UNSOURCED", "notice_id": notice_id,
                "detail": "per-part review-state was not ATTESTED as extraction-sourced and no part "
                          "carries the doc-level flag — the request was likely built from the lossy "
                          "graph projection (set review_state_source='extraction' when the parts + "
                          "their needs_review flags are read from the doc-tools review.json)"}

    # 0.1) ZERO PARTS is its own honest outcome, NOT laundering and NOT 'no residue'. Conflating them
    #      was misleading in both directions: the tripwire fired VACUOUSLY on an empty list, and once
    #      attested past it a zero-part notice fell through to NO_RESIDUE — which claims parts were
    #      FILTERED when in fact none were ever extracted. Distinguish by the extraction's own signal:
    #      flagged + nothing extracted = the extraction is telling us it struggled (surface it);
    #      unflagged + nothing extracted = a notice with genuinely no affected parts (honest skip).
    if not (request.get("impacted_parts") or []):
        if request.get("doc_needs_review"):
            return {"status": "NO_PARTS_EXTRACTED", "notice_id": notice_id,
                    "detail": "the extraction flagged this document for review AND produced no "
                              "affected parts — parts were not extracted (check review.json "
                              "review_reasons), rather than extracted-and-filtered"}
        return {"status": "NO_AFFECTED_PARTS", "notice_id": notice_id,
                "detail": "the extraction reports no affected parts and did not flag the document — "
                          "nothing to review"}

    # 0.5) INITIATOR GATE (ADR-0029 capability, deny-by-default). Starting a review is INVOKING
    #      mesh:startReview — an EFFECT — so the initiator is gated on the single decider BEFORE any
    #      composition. This is the honest COARSE gate that replaces the old per-item can_act filter: that
    #      filter checked a FIXED audience (ignoring the item) against the INITIATOR, so it was a coarse
    #      initiator check wearing a per-item costume, and it conflated "may initiate" with "is a reviewer"
    #      — invisible until the first non-human initiator (svc:review-starter). WHO may REVIEW is a
    #      separate gate at the task layer. See docs/plans/pcn-can-act-topaz-binding.md (Audience Rule).
    if not can_invoke_start_review(approver):
        return {"status": "NOT_ENTITLED_TO_INITIATE", "notice_id": notice_id, "initiator": approver}

    # 1) Load + validate the ruleset (client interprets engine-o's served Turtle). A corrupt or absent
    #    ruleset is surfaced HONESTLY here — it never flows into the batch looking valid.
    rules = await ctx.run("load_policy_rules", load_policy_rules)
    if rules["status"] == "not_found":
        return {"status": "RULES_NOT_FOUND", "notice_id": notice_id, "graph": _RULESET_GRAPH}
    if rules["status"] == "invalid":
        # report-don't-reject reaches its terminus: the caller's policy is "do not dispatch under an
        # invalid ruleset." Honest halt with reasons, no batch, no workflow.
        return {"status": "RULESET_INVALID", "notice_id": notice_id,
                "ruleset_ref": rules["ruleset_ref"], "validation_errors": rules["validation_errors"]}

    # 2) Compose the batch (ok or empty ruleset — an empty ruleset abstains everything, which surfaces
    #    honestly as NO_RESIDUE below rather than a silent nothing).
    # The composition runs as a Langfuse span RE-KEYED to the extraction's trace (ADR-0038)
    # so bucket -> extraction -> review renders as ONE trace. @traced is a no-op when the
    # leaf/Langfuse is absent; the emission sits INSIDE ctx.run, so it is journaled with the
    # step (runs once, not re-emitted on a restate replay). Fail-soft throughout — telemetry
    # never changes the composition or its result.
    def _compose_batch():
        # v4: open (or JOIN) the trace on the EXTRACTION's id so this composition nests
        # under the SAME Langfuse trace as the doc-tools extraction — native, via
        # create_trace_id(seed=trace_id). No seed (older review.json) -> a fresh trace.
        # Enrichment + fail-soft are handled inside observed_trace.
        with observed_trace(MAPPING, build_trace_values(
            trace_id=_trace_id,
            authz_id=approver,
            engine="review_starter",
            verb="mesh:startReview",
            domain=request.get("domain"),
            subject_class=request.get("doc_type") or "PCN",
        ), name="review composition"):
            return build_review_from_request(
                request,
                ruleset=rules["ruleset"],
                category_classes=rules["category_classes"],
                ruleset_ref=rules["ruleset_ref"],
                resolve_subject=resolve_subject_via_engine_o,
                can_act=_no_reviewer_filter,
            )

    build = await ctx.run("build_review_batch", _compose_batch)
    batch_items = build["batch_items"]
    if not batch_items:
        # Nothing reached residue — every part filtered / auto-disposed. Honest empty (no workflow, no
        # empty task), not a silent success. The old "residue exists but approver entitled to NONE" branch
        # is GONE: entitlement to INITIATE is the coarse capability gate above (NOT_ENTITLED_TO_INITIATE),
        # and a permitted initiator composes the FULL residue for the audience to triage — who may REVIEW
        # is gated at the task layer (register_task per-actor + /act), not by pre-filtering the batch.
        return {"status": "NO_RESIDUE", "notice_id": notice_id, "counts": build["counts"]}

    # ── ADMISSION POSTURE: which workflow may handle this notice (ADR-0034 phase 1.3) ──────────
    # THE RUNG IS COMPUTED HERE, SERVER-SIDE, AND NEVER ACCEPTED FROM THE REQUEST. The caller
    # supplies FACTS about its input (`format_fingerprint`, `pipeline_version` — the same pair the
    # sensor stamps on the decision record); the AUTHORITY DECISION derived from those facts is the
    # server's alone. Handing the route over the wire would let anyone entitled to
    # `mesh:startReview` select their own supervision level — the confused-deputy shape
    # `_compartment_from_request` already refuses for audiences, on the same reasoning.
    #
    # THIS LAYER READS THE POSTURE; IT DOES NOT DECIDE IT. `rung_for` is the TABLE's resolver and
    # the table owns the decision (ADR-0034 rule 1). The starter owns only the DISPATCH of it:
    # rung -> definition, mechanically. No layer encodes another's decision.
    #
    # FLOOR PRESERVED: an unknown format, an absent table, or a `pipeline_version` mismatch all
    # yield `supervised` — the last of those is the property the whole table exists to enforce
    # (a rung earned under one pipeline version must not survive an upgrade), so it is inherited
    # from `rung_for` untouched rather than re-implemented here.
    #
    # A BROKEN TABLE SUPERVISES, LOUDLY. `load_trust_table` raises rather than returning a
    # permissive empty table; catching it HERE and forcing workflow 1 is the caller-side half of
    # that contract — the safe behaviour happens, and the reason is logged at a layer that can
    # say why.
    # ── DERIVED FROM THE ARTIFACT, NOT ACCEPTED FROM THE CALLER (phase 1.3 consumer half) ──────
    # The caller supplies a POINTER (`artifact_uri` — a full `s3://bucket/key`). Both halves of the
    # trust key are read from the artifact that pointer names. A caller can lie about exactly one
    # thing — WHICH artifact — and the artifact determines everything else, which collapses the
    # trust question to "can the caller read that artifact".
    #
    # IT READ `request_key` FOR ONE DAY, and that was a defect, not a shortcut. `request_key` is the
    # artifact's IDENTITY (`{epoch}{ETag}-{key}`), minted for ingress idempotency; handing it to a
    # fetch asks S3 for a key with an ETag glued to the front, so every derive refused. Identity and
    # location are different jobs and one string cannot hold both — the same rule the run_key and the
    # triage task_id already carry, applied in the other direction. Pinned by
    # tests/test_artifact_uri_contract.py and tests/test_cross_repo_contracts.py.
    #
    # FETCH FAILURE IS A REFUSAL, NOT A FLOOR-FALL. Floor-falling on an unreadable artifact would
    # let an S3 outage silently convert every admission to supervised — safe, invisible, and
    # indistinguishable from policy. Only a WELL-FORMED artifact with no producer stamp takes the
    # floor, and it is attested as such so the back-corpus degrades legibly rather than silently.
    rung = DEFAULT_RUNG
    trust_ref = "trust@unavailable"
    admitted_by = "content"
    # THE ARTIFACT'S LOCATION, not its identity. `request_key` is `{epoch}{ETag}-{key}` and exists
    # for ingress idempotency; reading it as a pointer asked S3 for a key with an ETag glued to the
    # front and refused every derive. One string cannot hold both jobs.
    _pointer = str(request.get("artifact_uri") or "")
    try:
        derived = derive_provenance(_pointer)
    except ArtifactUnreadable as exc:
        # TERMINAL: the admission posture is UNDECIDABLE, so no posture is assumed. Refusing is the
        # only answer that cannot be mistaken for a policy decision.
        raise restate.TerminalError(
            f"cannot derive the admission posture for notice {notice_id!r}: {exc}. The trust key is "
            f"derived from the artifact, so an unreadable artifact means the posture is UNKNOWN — "
            f"and an unknown posture must refuse, never quietly supervise (an outage would then be "
            f"indistinguishable from policy).",
            status_code=422,
        )

    fmt_fp = derived.format_fingerprint
    pipe_v = derived.pipeline_version
    if derived.version_missing:
        # The back-corpus: a well-formed artifact whose producer never stamped itself. Floor, and
        # SAY SO — the sibling of `policy-default-missing-facts`.
        admitted_by = "policy-default-missing-provenance"
    try:
        _table = load_trust_table()
        trust_ref = _table.ref
        if fmt_fp and pipe_v:
            rung = _table.rung_for(fmt_fp, pipe_v)
    except Exception as exc:  # noqa: BLE001 — a bad table supervises; it never blocks the review
        print(f"TRUST_TABLE unreadable ({type(exc).__name__}: {exc}) — supervising this notice",
              flush=True)

    autonomous = rung in (MONITORED, TRUSTED)
    print(f"ADMISSION notice={notice_id} format={fmt_fp or '(none)'} "
          f"pipeline={pipe_v or '(none)'} rung={rung} table={trust_ref} "
          f"admitted_by={admitted_by} derived_from={_pointer or '(no pointer)'} "
          f"-> {'autonomous_review' if autonomous else 'grouped_review'}", flush=True)

    workflow_id = compose_workflow_id(notice_id, approver, request.get("request_key"))
    ctx.workflow_send(
        autonomous_review_run if autonomous else grouped_review_run,
        key=workflow_id,
        arg={
            # The posture that SELECTED this path, carried so the workflow's own records can say
            # what admitted them without re-deriving it (and without re-reading a table that may
            # have changed since the decision).
            "trust_rung": rung,
            "trust_table_ref": trust_ref,
            "format_fingerprint": fmt_fp,
            "pipeline_version": pipe_v,
            # HOW this notice was admitted: `content` normally, or
            # `policy-default-missing-provenance` when the artifact carried no producer stamp and
            # therefore took the floor. Carried so the decision record can say WHY a notice
            # supervised, instead of leaving a floor-fall indistinguishable from a real posture.
            "admitted_by": admitted_by,
            # THE INITIATOR'S IDENTITY, and on the autonomous path it is LOAD-BEARING.
            # `_run_definition` builds its identity as
            #     request.get("authz_id") or request.get("caller_email") or ""
            # and a `direct_call` step gates on `can_invoke(that identity, capability)`. Without
            # this line the check runs for caller '' — witnessed live before it was added:
            #     403 "caller '' is not authorized (can_invoke) for capability
            #          'mesh:dispatchDispositions' — failing and releasing."
            # Workflow 1 never exposed it: its gate is the audience `can_act` on the human step,
            # so `direct_call` is unique to workflow 2 and the identity had never been needed.
            #
            # WHY IT MATTERS BEYOND A BUG: the ceremony's acceptance is "watch deny flip to allow
            # for THIS initiator". A deny recorded against '' is not the before-side of an allow
            # granted to `svc:review-starter` — they are different subjects, so the flip would be
            # UNWITNESSABLE, and granting the capability would have changed nothing while looking
            # like it should have. Found by capturing the before-picture on the deployed system,
            # which is the only place it was visible.
            "authz_id": approver,
            "approver": approver,
            "audience": request.get("audience") or approver,
            "notice_fingerprint": notice_id,
            "notice_id": notice_id,
            "doc_type": request.get("doc_type", "PCN"),
            "batch_items": batch_items,
            # Extraction-quality warnings ride WITH the batch to the reviewer: a review
            # composed from a degraded extraction must SAY so, else a partial parts list
            # looks complete and the missing parts get no disposition, silently.
            "extraction_warnings": list(request.get("extraction_warnings") or []),
            "user_jwt": request.get("user_jwt", ""),
            # THE ARTIFACT'S IDENTITY, carried so an ESCALATION can derive a distinct one. When the
            # autonomous path refuses (an unverified row, a row with no disposition) it must reach a
            # human, and the escalated admission cannot reuse this key: the BFF keys ingress
            # idempotency on (request_key, approver), so an escalation carrying the same pair would
            # ATTACH to the invocation that just refused it and return that result — swallowed,
            # dropped, nothing red. See `escalation_request_key`.
            "request_key": request.get("request_key", ""),
        },
    )
    return {
        "status": "STARTED",
        # THE ADMISSION DECISION, RETURNED SO NOBODY RECOMPUTES IT (2026-08-10).
        #
        # The decision record used to re-derive the rung itself — `rung_for(fingerprint,
        # os.getenv("PIPELINE_VERSION", "unset"))` — from an env var the deploy never set. So every
        # record in the corpus said `supervised` while this function routed `monitored`, and the
        # audit trail answered the trust arc's central question WRONG. Not missing: wrong, which is
        # worse, and invisible precisely because both values are plausible.
        #
        # THE ROOT WAS TWO DERIVATIONS OF ONE DECISION, not a bad env var. Two derivations disagree
        # whenever their inputs differ, and this codebase has now paid for that at the starter
        # (reader's env vs producer's artifact), at the fingerprint (two mints, two env contracts),
        # and in the record. The admission happens HERE, once, with the artifact-derived key; every
        # downstream reader is a RECORDER of that decision, never a second decider.
        "admission": {
            "rung": rung,
            "trust_table_ref": trust_ref,
            "admitted_by": admitted_by,
            "format_fingerprint": fmt_fp,
            "pipeline_version": pipe_v,
        },
        "workflow_id": workflow_id,
        "count": len(batch_items),
        "ruleset_ref": build["ruleset_ref"],
        "counts": build["counts"],
        "resolved": build["resolved"],
        "unresolved": build["unresolved"],
    }
