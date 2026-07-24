"""PCN/PDN review STARTER — the explicit entry that composes a notice into a running grouped review.

Wiring by construction over the sealed cores: fetch the ruleset (from the graph — source-authority),
compose the server-authored batch ([[pcn_review_builder]]), and start the [[pcn_workflow]]
``PcnGroupedReview`` workflow. Triggered by an EXPLICIT invocation carrying the notice reference — no
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
  * ``can_act``         -> DEPLOY-GATED, born generic. Topaz resource type is the workflow-model noun
    ``disposition_item`` with the domain as a Topaz ATTRIBUTE (never a ``pcn_disposition`` type — a
    domain-named type would write the domain into the entitlement contract). ``core/authz.py`` is
    decorator-shaped; the ``disposition_item`` type + action pending its Topaz wiring — the ONE seam
    that is genuinely unsealable offline (needs the live authz binding).

The notice's affected parts + needs_review flags are the doc-tools EXTRACTION, passed in the request
(the upstream producer); the starter does not re-extract. Scope (BOM/AVL ``in_scope_mpns``) is an input.
"""
from __future__ import annotations

import os
from typing import Callable, Optional

import restate
from restate import Context, Service

try:  # lazy-import dance (container flattens the dir)
    from pcn_review_builder import build_review_batch, resolve_subject_via_engine_o  # type: ignore[no-redef]
    from pcn_workflow import batch_items_to_state  # type: ignore[no-redef]
    from pcn_workflow import run as pcn_grouped_review_run  # type: ignore[no-redef]
    from policy_rules_client import fetch_policy_rules  # type: ignore[no-redef]
except ImportError:  # pragma: no cover - import path differs by runtime
    from agent_fleet.restate_analyst.pcn_review_builder import build_review_batch, resolve_subject_via_engine_o
    from agent_fleet.restate_analyst.pcn_workflow import batch_items_to_state
    from agent_fleet.restate_analyst.pcn_workflow import run as pcn_grouped_review_run
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
_RULESET_LABEL = os.getenv("PCN_RULESET_LABEL", "pcn_disposition_rules")
# The caller's registered actions (its domain vocab) — enables the registration check at load time.
_KNOWN_DISPOSITIONS = ["dispatchQualification", "dispatchLTB", "dispatchAltSourcing", "archive"]


def load_policy_rules() -> dict:  # pragma: no cover - deploy-gated (live engine-o fetch)
    """Fetch + load + validate the ruleset via the GENERIC policy-rules client (engine-o serves Turtle
    from the named graph; the client interprets it — source-authority, the domain is the ``graph``
    argument). Returns the client's dict incl. ``status`` (not_found/empty/invalid/ok) + validity."""
    return fetch_policy_rules(_RULESET_GRAPH, _RULESET_LABEL, known_dispositions=_KNOWN_DISPOSITIONS)


def can_act_via_topaz(approver: str, item) -> bool:  # pragma: no cover - deploy-gated (Topaz wiring pending)
    """Topaz predicate for grouped_review — DEPLOY-GATED, born generic. The resource type is the
    workflow-model noun ``disposition_item`` (domain as a Topaz ATTRIBUTE, never a ``pcn_disposition``
    type — a domain-named type would write the domain into the entitlement contract, the hardest layer
    to walk back). Pending its Topaz wiring against ``core/authz.py``. grouped_review fails CLOSED on a
    missing can_act, so an unwired default is safe-but-empty."""
    raise NotImplementedError(
        "can_act_via_topaz: wire the GENERIC Topaz resource type 'disposition_item' (domain as "
        "attribute) + action against core/authz.py — see the generic-at-birth rule in AGENTS.md"
    )


# ---------------------------------------------------------------------------
# The durable entry handler
# ---------------------------------------------------------------------------
pcn_review_starter = Service("PcnReviewStarter")


@pcn_review_starter.handler()
async def start_review(ctx: Context, request: dict) -> dict:
    """Explicitly-invoked: compose a notice into a batch and START the grouped-review workflow.

    request: ``notice_id``, ``doc_type``, ``categories``, ``impacted_parts`` (doc-tools extraction),
    ``in_scope_mpns``, ``approver``, ``audience``, ``user_jwt``. The build runs in one journaled
    ``ctx.run`` step (reads only — resolveInstance/Topaz/rules-fetch — so a crash re-runs it
    idempotently); the only durable effect is starting the workflow (idempotent on its id). If nothing
    reaches residue, return ``NO_RESIDUE`` honestly — no workflow, no empty task."""
    notice_id = request["notice_id"]
    approver = request["approver"]

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
            return {"status": "NO_ENTITLED_ACTION", "notice_id": notice_id,
                    "approver": approver, "counts": build["counts"]}
        # Genuinely nothing to review — every part filtered / auto-disposed (residue is empty).
        return {"status": "NO_RESIDUE", "notice_id": notice_id, "counts": build["counts"]}

    workflow_id = f"pcn-review-{notice_id}-{approver}"
    ctx.workflow_send(
        pcn_grouped_review_run,
        key=workflow_id,
        arg={
            "approver": approver,
            "audience": request.get("audience") or approver,
            "notice_fingerprint": notice_id,
            "notice_id": notice_id,
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
