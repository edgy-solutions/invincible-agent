"""SPO-step executor — the stage-2 eligibility verifier + dispatch, and the
direct_call capability gate (ADR-0029 Slice 1).

The load-bearing call-shape, DECIDED AGAINST LIVE ENGINE O (not guessed):

* **A step is PRE-RESOLVED.** An ``spo_operation`` declares ``(subject, verb)``. The
  verifier does NOT NL-resolve — it calls Engine O's **structural** seam
  ``POST /find_compatible_verbs {subject_uri, entitled_domains}`` (Neo4j is the (S,P)
  compatibility reasoner) and confirms the declared ``verb_iri`` is in the returned
  set. This is the same structural gate that scopes queries — reusing it is what
  makes enforcement-by-construction "for free".

* **The eligibility intersection composes across two seams, exactly like a query:**
  - ``domain ∩ arity ∩ argument-fit`` — STRUCTURAL, in the verifier here
    (``/find_compatible_verbs`` applies domain; the pure arity filter runs locally;
    argument-fit is inert until typed-arg extraction lands, mirroring the supervisor).
  - ``permission`` — enforced AT DISPATCH by the target engine's OWN gate (can_view /
    can_read / …), which fail-and-releases on 401/403. That is precisely where the
    query path enforces permission too, so a step inherits identical enforcement.
  Net: **a workflow cannot launder access.** A structurally/domain-ineligible verb is
  caught HERE (fail-and-release before dispatch); an unpermitted-but-eligible verb is
  caught at the engine gate (fail-and-release at dispatch). Both release durable state
  (Situation C — a denial is a FAILURE, never a suspend).

* **``direct_call`` is GATED on the single decider (RULING Q3).** Before the POST,
  Topaz ``can_invoke(caller, capability)``; ungranted → fail-and-release (never
  dispatch an unauthorized capability). The escape hatch escapes the verb ontology,
  NOT the gate.

This module is PURE of Restate: it raises :class:`StepFailAndRelease`; the runner maps
that to ``restate.TerminalError`` at the (reviewable) cutover seam. That keeps the
executor unit-testable without the Restate SDK.
"""
import os
from typing import Any, Optional

import httpx
import requests

__all__ = [
    "StepFailAndRelease",
    "verify_spo_step",
    "dispatch_spo_step",
    "check_can_invoke",
    "execute_direct_call",
]

ENGINE_O_URL = os.getenv("ONTOLOGY_SERVICE_URL", "http://iagent-engine-o:8084")
TOPAZ_DIRECTORY_URL = os.getenv("TOPAZ_DIRECTORY_URL", "")
STEP_HTTP_TIMEOUT = float(os.getenv("STEP_HTTP_TIMEOUT", "1800"))


class StepFailAndRelease(Exception):
    """A step must FAIL and RELEASE its durable execution state — Situation C
    (a denial is a failure, never a suspend; retrying/parking a denied step is the
    DoS surface). The runner catches this and raises ``restate.TerminalError`` so
    Restate fails the workflow and frees the journal. ``status_code`` carries the
    denial code (403 access, 400 config, 500 infra)."""

    def __init__(self, message: str, *, status_code: int = 403) -> None:
        super().__init__(message)
        self.status_code = status_code


def _filter_verbs_by_arity(verbs: list[dict], query_is_set: bool) -> list[dict]:
    """Pure arity gate (replicates the supervisor's). When the step's subject is a
    SET (a class, no resolved instance), drop verbs that POSITIVELY declare
    ``arity == "single"``; keep set/any/null. For a PRE-RESOLVED INSTANCE step
    (the common case) ``query_is_set`` is False and every verb is kept — arity does
    not restrict an instance step. No LLM, no network."""
    if not query_is_set:
        return list(verbs)
    return [v for v in verbs if (v.get("arity") or "any") != "single"]


def verify_spo_step(
    subject: str,
    verb_iri: str,
    entitled_domains: list[str],
    *,
    query_is_set: bool = False,
    engine_o_url: str = ENGINE_O_URL,
) -> dict:
    """STAGE-2 STRUCTURAL VERIFIER (the enforcement point). Confirms the DECLARED
    ``verb_iri`` is in the caller's eligible set for ``subject`` (domain ∩ arity),
    returning the matched CompatibleVerb dict (carrying ``endpoint_url`` for
    dispatch). Raises :class:`StepFailAndRelease` if the verb is not eligible — a
    workflow cannot execute a verb outside the caller's eligibility set.

    NOT NL: ``subject``/``verb_iri`` are resolved identifiers; this is the structural
    half only. Permission composes downstream at dispatch (the engine's gate)."""
    if not subject or subject == "UNKNOWN":
        raise StepFailAndRelease(
            f"spo_operation step has no resolved subject ({subject!r})", status_code=400
        )
    resp = requests.post(
        f"{engine_o_url}/find_compatible_verbs",
        json={"subject_uri": subject, "max_hops": 5, "entitled_domains": entitled_domains},
        timeout=30,
    )
    resp.raise_for_status()  # a 5xx is transient infra -> retry (NOT a denial)
    verbs = list(resp.json().get("verbs") or [])
    verbs = _filter_verbs_by_arity(verbs, query_is_set)
    match = next((v for v in verbs if v.get("verb_iri") == verb_iri), None)
    if match is None:
        eligible = sorted(v.get("verb_iri") for v in verbs)
        raise StepFailAndRelease(
            f"verb {verb_iri!r} is NOT eligible for subject {subject!r} under domains "
            f"{entitled_domains} (eligible: {eligible}) — a workflow cannot execute a "
            f"verb outside the caller's eligibility set; failing and releasing.",
            status_code=403,
        )
    return match


def dispatch_spo_step(
    verb: dict,
    subject: str,
    identity: dict,
    *,
    subject_instance: str = "",
    rendered_intent: str = "",
) -> dict:
    """Dispatch a VERIFIED spo_operation to its engine. Threads the caller identity
    so the engine's OWN gate enforces the PERMISSION dimension — a 401/403 is a
    denial → fail-and-release (Situation C); a 5xx is transient → raised for retry.
    The step's ``user_query`` is a templated INTENT, not a user's NL question (the
    verb is already chosen — no re-classification)."""
    endpoint = verb.get("endpoint_url")
    if not endpoint:
        raise StepFailAndRelease(
            f"eligible verb {verb.get('verb_iri')!r} has no endpoint_url", status_code=500
        )
    payload: dict[str, Any] = {
        "user_query": rendered_intent or f"workflow step: {verb.get('verb_iri')} on {subject}",
        "user_email": identity.get("authz_id", ""),      # authz_id (ADR-0025)
        "entitled_domains": list(identity.get("entitled_domains") or []),
        "user_persona": identity.get("persona"),
        "answerer_persona": verb.get("owner_persona") or identity.get("persona"),
        "predicate_verb_iri": verb.get("verb_iri"),
        "routed_verb_iri": verb.get("verb_iri"),
        "resolved_subject_uri": subject,
        "resolved_instance_id": subject_instance,
    }
    headers = {}
    if identity.get("user_jwt"):
        payload["user_jwt"] = identity["user_jwt"]
        headers["Authorization"] = f"Bearer {identity['user_jwt']}"
    resp = requests.post(endpoint, json=payload, headers=headers, timeout=STEP_HTTP_TIMEOUT)
    if resp.status_code in (401, 403):
        raise StepFailAndRelease(
            f"access denied ({resp.status_code}) dispatching {verb.get('verb_iri')!r} to "
            f"{endpoint} — the PERMISSION dimension (engine gate); failing and releasing.",
            status_code=403,
        )
    resp.raise_for_status()  # 5xx/network -> retryable
    return resp.json()


def check_can_invoke(
    capability: str, caller_authz_id: str, *, topaz_url: str = TOPAZ_DIRECTORY_URL
) -> bool:
    """RULING Q3: a direct_call is gated on the SINGLE DECIDER. Topaz
    ``can_invoke(caller, capability)`` on the ``capability`` object namespace.
    Deny-by-default: empty identity/capability/URL or any error → False."""
    if not caller_authz_id or not capability or not topaz_url:
        return False
    payload = {
        "object_type": "capability",
        "object_id": capability,
        "relation": "can_invoke",
        "subject_type": "user",
        "subject_id": caller_authz_id,
    }
    try:
        r = httpx.post(f"{topaz_url}/api/v3/directory/check", json=payload, timeout=5.0)
        r.raise_for_status()
        return bool(r.json().get("check"))
    except Exception:
        return False  # fail-closed


def execute_direct_call(
    step: dict,
    identity: dict,
    *,
    topaz_url: str = TOPAZ_DIRECTORY_URL,
    extra_payload: Optional[dict] = None,
) -> dict:
    """TRANSITIONAL direct_call. GATE FIRST: Topaz ``can_invoke(caller, capability)``
    BEFORE the POST — ungranted → fail-and-release (never dispatch an unauthorized
    capability). Then POST the declared ``endpoint`` (behavior-identical to today's
    service_task; a 401/403 there also fails-and-releases)."""
    capability = step.get("capability") or ""
    caller = identity.get("authz_id", "")
    if not check_can_invoke(capability, caller, topaz_url=topaz_url):
        raise StepFailAndRelease(
            f"caller {caller!r} is not authorized (can_invoke) for capability "
            f"{capability!r} — failing and releasing.",
            status_code=403,
        )
    endpoint = step.get("endpoint") or ""
    if not endpoint:
        raise StepFailAndRelease(
            f"direct_call step {step.get('id')!r} has no endpoint", status_code=400
        )
    payload: dict[str, Any] = {
        "task_id": step.get("id"),
        "task_type": "direct_call",
        "capability": capability,
    }
    if isinstance(extra_payload, dict):
        payload.update(extra_payload)
    headers = {}
    if identity.get("user_jwt"):
        payload["user_jwt"] = identity["user_jwt"]
        headers["Authorization"] = f"Bearer {identity['user_jwt']}"
    resp = requests.post(endpoint, json=payload, headers=headers, timeout=STEP_HTTP_TIMEOUT)
    if resp.status_code in (401, 403):
        raise StepFailAndRelease(
            f"access denied ({resp.status_code}) on direct_call {step.get('id')!r} -> "
            f"{endpoint}; failing and releasing.",
            status_code=403,
        )
    resp.raise_for_status()
    return resp.json()
