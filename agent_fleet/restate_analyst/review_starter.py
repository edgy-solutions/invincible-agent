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
    ``task_audience`` (key ``pcn_disposition:<domain>``, permission ``can_act``, grantable direct or via
    group). Direct Topaz DIRECTORY check, deny-by-default; grants arrive by the git-rails seed CronJob
    (`task_grants.yaml`), never hand-surgery. Reading work's rails RETIRED the bespoke ``disposition_item``
    type + rego (they were reinventing this). Still deploy-gated (needs the seed + the grants).

The notice's affected parts + needs_review flags are the doc-tools EXTRACTION, passed in the request
(the upstream producer); the starter does not re-extract. Scope (BOM/AVL ``in_scope_mpns``) is an input.
"""
from __future__ import annotations

import os
from typing import Callable, Optional

import restate
from restate import Context, Service

try:  # lazy-import dance (container flattens the dir)
    from review_composer import build_review_batch, resolve_subject_via_engine_o  # type: ignore[no-redef]
    from grouped_review_workflow import batch_items_to_state  # type: ignore[no-redef]
    from grouped_review_workflow import run as grouped_review_run  # type: ignore[no-redef]
    from policy_rules_client import fetch_policy_rules  # type: ignore[no-redef]
except ImportError:  # pragma: no cover - import path differs by runtime
    from agent_fleet.restate_analyst.review_composer import build_review_batch, resolve_subject_via_engine_o
    from agent_fleet.restate_analyst.grouped_review_workflow import batch_items_to_state
    from agent_fleet.restate_analyst.grouped_review_workflow import run as grouped_review_run
    from agent_fleet.restate_analyst.policy_rules_client import fetch_policy_rules

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
# Independent toggle for the disposition can_act gate. NOT the terminal ENABLE_AGENTIC_AUTH (whose flip
# turns on EVERY dark-launched content gate cluster-wide, irreversibly). can_act gates WHO reviews (a
# grain-of-review property), so it gets its OWN dark-launch toggle — dark until grants are seeded, then
# flipped for its own gate alone. Off -> no-op True (like the other gates when their flag is off).
ENABLE_DISPOSITION_AUTHZ = os.getenv("ENABLE_DISPOSITION_AUTHZ", "false").lower() in ("true", "1", "yes")
_ITEM_DOMAIN = os.getenv("PCN_DISPOSITION_DOMAIN", "SUSTAINMENT")
_TASK_KIND = "pcn_disposition"   # the task_kind half of the task_audience key (task_kind:compartment)


def can_act_via_topaz(approver: str, item) -> bool:  # pragma: no cover - live Topaz (exercised by the discrimination seal)
    """Topaz predicate for grouped_review — reconciled onto WORK'S EXISTING mechanism (single-authz-
    decider): the HITL ``task_audience`` (`task_grants.yaml` → `task_grant_sync.py`). A grouped review is
    a HITL task, and "who may act on a class of HITL tasks in a compartment" is EXACTLY ``task_audience``
    — key ``<task_kind>:<compartment>`` where the compartment IS the domain (``pcn_disposition:SUSTAINMENT``),
    permission ``can_act`` (relation ``actor``, granted directly OR via ``group#member``). No bespoke
    ``disposition_item`` type, no rego, no manifest edit — that was reinventing this. The check is a
    direct Topaz DIRECTORY check (`POST /api/v3/directory/check`): deny-by-default (an ungranted audience
    is "object not found" -> deny). Grants arrive by the git-rails seed CronJob, never hand-surgery.

    No-op True when ``ENABLE_DISPOSITION_AUTHZ`` is off (its OWN dark-launch toggle, not the terminal
    ENABLE_AGENTIC_AUTH flip). Any error / not-found -> deny (a gate must not fail open); grouped_review
    then withholds the item and start_review surfaces NO_ENTITLED_ACTION rather than parking."""
    if not ENABLE_DISPOSITION_AUTHZ:
        return True
    if not approver:
        return False
    audience = f"{_TASK_KIND}:{_ITEM_DOMAIN}"   # task_kind:compartment — compartment is the domain
    try:
        import requests
        resp = requests.post(
            f"{TOPAZ_DIRECTORY_URL}/api/v3/directory/check",
            headers={"Content-Type": "application/json"},
            json={"object_type": "task_audience", "object_id": audience, "relation": "can_act",
                  "subject_type": "user", "subject_id": approver},
            timeout=5.0,
        )
        resp.raise_for_status()
        return bool(resp.json().get("check", False))   # absent/not-found/error -> deny (fail-closed)
    except Exception:  # noqa: BLE001 — fail-closed (deny) on any error, like the ontology gate
        return False


# ---------------------------------------------------------------------------
# Review-state sourcing tripwire — laundering-by-substrate-gap guard (STANDING INVARIANT)
# ---------------------------------------------------------------------------
def review_state_is_unsourced(doc_needs_review, impacted_parts) -> bool:
    """The laundering-by-substrate-gap signature. Per-part ``needs_review`` exists ONLY in the extraction
    (`review.json`) — BOTH graphs drop it (doc-tools writes only the DOC-LEVEL flag to Neo4j; Jena drops
    it entirely). So the request MUST be built from the extraction, never the mesh graph. The tripwire:
    if the DOC-LEVEL flag says "something here needs review" (``doc_needs_review`` True) but NO part
    carries ``needs_review`` True, the per-part flags were NOT sourced — the request was built from a
    lossy graph projection, and every downstream §3 laundering seal (UNVERIFIED badge → accept-all
    exclusion → override-with-reason) would fire CLEAN on an unverified MPN. That defeats five sealed
    layers without touching any of them. Standing rule: EXTRACTION is authoritative for review-state;
    [[feedback_synthetic_data_no_mock_leak]] one layer up. ``doc_needs_review`` is None/absent -> can't
    check (no-op); the request builder MUST pass it (from the extraction / Neo4j doc-level) to arm this."""
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

    # 0) Review-state sourcing tripwire (BEFORE anything else): a request whose doc-level flag says
    #    "needs review" but whose parts carry no per-part flag was built from a lossy graph projection —
    #    refuse rather than launder an unverified MPN through five sealed layers.
    if review_state_is_unsourced(request.get("doc_needs_review"), request.get("impacted_parts")):
        return {"status": "REVIEW_STATE_UNSOURCED", "notice_id": notice_id,
                "detail": "doc-level needs_review is set but no part carries it — per-part review-state "
                          "was not sourced from the extraction (built from the lossy graph projection?)"}

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
    build = await ctx.run(
        "build_review_batch",
        lambda: build_review_from_request(
            request,
            ruleset=rules["ruleset"],
            category_classes=rules["category_classes"],
            ruleset_ref=rules["ruleset_ref"],
            resolve_subject=resolve_subject_via_engine_o,
            can_act=can_act_via_topaz,
        ),
    )
    batch_items = build["batch_items"]
    if not batch_items:
        if build["counts"]["residue"] > 0:
            # Residue EXISTS but this approver is entitled to act on NONE of it. Surface LOUDLY — never
            # mask it as "nothing to review". This is the deny-for-everyone misconfig (the agentic-auth
            # flip's first-symptom class) / wrong-approver case: a review nobody can action is the
            # join-that-can-never-complete in review clothes (Slice-5 suspend-vs-fail, one level up).
            # Fail here (no workflow started) rather than register a review that parks forever, unseen.
            # AUDIENCE: this is an INITIATOR-PLANE outcome (operator/system starting the review). It is
            # honest here, but to a PARTICIPANT (an approver about their OWN view) it is an existence
            # oracle — "items exist you can't act on" is exactly what Slice-3 redaction withholds. Any
            # participant-facing entry path MUST collapse this to nothing-to-review. See
            # docs/plans/pcn-can-act-topaz-binding.md (Audience Rule).
            return {"status": "NO_ENTITLED_ACTION", "notice_id": notice_id,
                    "approver": approver, "counts": build["counts"]}
        # Genuinely nothing to review — every part filtered / auto-disposed (residue is empty).
        return {"status": "NO_RESIDUE", "notice_id": notice_id, "counts": build["counts"]}

    workflow_id = f"pcn-review-{notice_id}-{approver}"
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
