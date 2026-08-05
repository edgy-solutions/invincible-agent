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
    from policy_rules_client import fetch_policy_rules  # type: ignore[no-redef]
    from orchestrator.auth import current_trace_id  # type: ignore[no-redef]
except ImportError:  # pragma: no cover - import path differs by runtime
    from agent_fleet.restate_analyst.review_composer import build_review_batch, resolve_subject_via_engine_o
    from agent_fleet.restate_analyst.grouped_review_workflow import batch_items_to_state
    from agent_fleet.restate_analyst.grouped_review_workflow import run as grouped_review_run
    from agent_fleet.restate_analyst.policy_rules_client import fetch_policy_rules
    from agent_fleet.restate_analyst.orchestrator.auth import current_trace_id

# Telemetry (ADR-0038): baml_shared is on sys.path (the analyst app adds it at startup).
# Guarded so the ReviewStarter runs identically when the shim/leaf is absent (no-op
# primitives) — the witness channel never breaks the composition.
try:
    from telemetry import traced, set_trace_standard, build_trace_values, MAPPING  # type: ignore[no-redef]
except Exception:  # pragma: no cover — telemetry is never load-bearing
    def traced(name=None, as_type=None):  # type: ignore[misc]
        def _d(f):
            return f
        return _d

    def set_trace_standard(*_a, **_k):  # type: ignore[misc]
        return None

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
    @traced(name="review composition")
    def _compose_batch():
        if _trace_id:
            try:
                set_trace_standard(MAPPING, build_trace_values(
                    trace_id=_trace_id,
                    authz_id=approver,
                    engine="review_starter",
                    verb="mesh:startReview",
                    domain=request.get("domain"),
                    subject_class=request.get("doc_type") or "PCN",
                ))
            except Exception:  # noqa: BLE001 — telemetry never breaks the compose
                pass
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

    workflow_id = compose_workflow_id(notice_id, approver, request.get("request_key"))
    ctx.workflow_send(
        grouped_review_run,
        key=workflow_id,
        arg={
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
        },
    )
    return {
        "status": "STARTED",
        "workflow_id": workflow_id,
        "count": len(batch_items),
        "ruleset_ref": build["ruleset_ref"],
        "counts": build["counts"],
        "resolved": build["resolved"],
        "unresolved": build["unresolved"],
    }
