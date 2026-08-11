"""Service-identity token mint — MINT AT USE, never a stored credential.

THE RULE THIS MODULE EXISTS TO ENFORCE (filed 2026-08-04, from the notice-A defect —
``docs/plans/2026-08-04-notice-a-dispatch-failure.md``):

    A credential captured at one moment and used at another is stale by design wherever the gap
    is a HUMAN's. Mint at the point of use, under the ACTING identity.

The defect: a grouped review's ``user_jwt`` was captured when the review STARTED, stored in Restate
workflow state, and reused to register the per-part dispatch tasks at APPROVAL time. A grouped
review is *designed* to suspend for human latency — hours, days, a weekend — so that token is
ROUTINELY stale when the approval arrives. Notice ``M32-A-WITNESS`` sat ~90 minutes; both dispatches
died on ``401 -> fail-and-release`` 160ms after the approval, leaving the projection reading
``approved`` with no effects.

**The rejected fix was "a longer-lived credential."** Lifetime-tuning to outlast human reviewers
converges on effectively unbounded tokens stored durably in journals — a credential-at-rest surface
that grows to match the slowest reviewer.

**The conflation that caused it:** the stored token carried two different facts at once —
PROVENANCE (which human approved) and AUTHORIZATION TO EXECUTE EFFECTS (the pipeline's own
entitlement). They separate here. Provenance belongs in the decision record and in ``requested_by``;
effects run under the pipeline's identity, minted fresh at the moment of use.

ONE HOME, NOT TWO (``feedback: two escapers are two chances to disagree``). This lives in
``agent_fleet/utils/`` because that is the only tree BOTH runtimes carry: engine-a's image flattens
it to ``/app/utils/``, and the Dagster user-code image has it at ``/app/agent_fleet/utils/``
(verified on the running pods — ``src/iagent`` does NOT exist in engine-a, so the sensor's copy was
never importable there). The Dagster sensor keeps a thin wrapper that re-raises as ``dagster.Failure``
so its proven test contract is unchanged; the mint logic itself is only here.
"""
import logging
import os
from typing import Dict

__all__ = ["ServiceTokenError", "mint_service_token", "outbound_auth_headers"]


# ── THE ONE IMPLEMENTATION LIVES IN THE SDK (iagent_mesh >= 0.2.0) ──────────────────────
# This module is now a set of THIN BINDINGS: each names one identity's credentials and calls
# the SDK's general `mint_token`. The SDK is the mesh's membership package and a genuine leaf
# (pydantic/fastapi/httpx, nothing platform-side), so platform -> SDK is the ordinary
# shared-kernel direction. The reverse edge — the SDK reaching in here via a guarded import —
# is gone as of iagent_mesh 0.2.0, and with it the inline transcription that had already
# DIVERGED (MESH_CLIENT_ID here vs REVIEW_STARTER_CLIENT_ID there).
#
# WHY BINDINGS AND NOT ONE FUNCTION: identity is an ARGUMENT. Each service has its own
# credential pair, because that is what makes them separate identities — the lesson from
# `mint_service_token()`'s general name over review-starter-specific behaviour, which had the
# supervisor dispatching as svc:review-starter with that role's capability grant (3ac573d).
from iagent_mesh.service_identity import ServiceTokenError, mint_token  # noqa: F401


def mint_supervisor_token(*, timeout: float = 15.0) -> str:
    """The SUPERVISOR's dispatch identity (`svc:supervisor`). Its OWN credentials — not the
    review starter's, which is the bug this function exists to make unrepeatable."""
    return mint_token(
        client_id=os.environ["SUPERVISOR_CLIENT_ID"],
        client_secret=os.environ["SUPERVISOR_CLIENT_SECRET"],
        timeout=timeout,
    )


def mint_service_token(*, timeout: float = 15.0) -> str:
    """THE REVIEW STARTER'S MINT — despite the general name. NEW CALLERS: DO NOT USE THIS.

    NAME/BEHAVIOUR MISMATCH, kept only so the extraction->review sensor is untouched. This
    reads REVIEW_STARTER_CLIENT_ID/SECRET, so ANY caller using it authenticates as
    `svc:review-starter` and inherits that role's capability grant. The supervisor was wired
    against this name on 2026-08-07 and would have dispatched under the review starter's
    identity; a general NAME over specific BEHAVIOUR is the whole defect, and leaving the name
    unmarked is how the next caller repeats it.

    Use `mint_token(client_id=..., client_secret=...)` with YOUR identity, or a named wrapper
    like `mint_supervisor_token()`. This one should retire once the sensor moves over.

    Mint a FRESH access token for the pipeline's service identity (``svc:review-starter``) via
    Keycloak client-credentials. Fresh by construction — there is no stored JWT to go stale, and no
    lifetime knob to tune.

    The token's ``authz_id`` resolves to ``svc:review-starter`` through the client's hardcoded-claim
    mapper, so the pipeline acts under its OWN entitled identity and never a borrowed human token.

    The mint is part of the OBSERVABLE seam: a failure (Keycloak down, secret rotated, client
    disabled) RAISES and NAMES the cause. "Keycloak was down so nothing happened and nothing said so"
    is precisely the invisible death this refuses.

    Env (present on engine-a AND the Dagster user-code image — verified on the running pods):
    ``KEYCLOAK_REALM_URL``, ``REVIEW_STARTER_CLIENT_ID``, ``REVIEW_STARTER_CLIENT_SECRET``.
    """
    return mint_token(
        client_id=os.environ["REVIEW_STARTER_CLIENT_ID"],
        client_secret=os.environ["REVIEW_STARTER_CLIENT_SECRET"],
        timeout=timeout,
    )


def outbound_auth_headers(*, client_id: str, secret_env: str, timeout: float = 15.0) -> Dict[str, str]:
    """Authorization headers for ONE outbound mesh call, under a CALLER-NAMED identity.

    THE SEAM THE 11-SITE ENUMERATION ASKED FOR (``docs/plans/unminted-caller-enumeration.md``).
    Nineteen platform callers reached engine-o / engine-A / DA with no credential at all; eleven
    of them STOP under ``REQUIRE_TRANSPORT_AUTH``. They are two identities across two processes,
    so the fix is one helper and a literal at each site — not eleven bespoke edits.

    IDENTITY IS AN ARGUMENT — the same rule as ``engine_mint``, for the same reason. Both the
    client id and the env var holding its secret are named BY THE CALLER at the caller's own site.
    A helper that resolved the identity itself (from the module name, a conventional env var, a
    default) would be a general name over specific behaviour — which is exactly how
    ``mint_service_token()`` came to read REVIEW_STARTER_CLIENT_ID and would have had the
    supervisor dispatching as the review starter. **The literal at the call site is the feature.**
    Repeating it is cheaper than one wrong inheritance.

    OBSERVE-PHASE BEHAVIOUR — LOG AND PROCEED, NEVER RAISE. Engines currently accept
    unauthenticated callers (the SDK's transport-auth default is OBSERVE), so attaching a
    credential where none was sent is behaviourally inert: receivers validate-if-present and
    refuse nothing. A mint failure must therefore NOT break a call that works today — it is
    logged and the call proceeds token-less, which the receiving engine records as ``caller:
    none``. That is the migration gauge filling in, not an outage. When REQUIRE flips, the same
    failure becomes a 401 at the engine, which is the correct moment for it to become loud.

    Mirrors ``dynamic_supervisor._telemetry_headers`` deliberately — same posture, same
    diagnostic header, same reasoning. Process B already had this; process A did not.

    FAILS LOCALLY BEFORE IT FAILS REMOTELY, and that is load-bearing for tests: ``os.environ[
    secret_env]`` is evaluated BEFORE ``mint_token`` is entered, so an unconfigured environment
    raises ``KeyError`` here and never opens a socket. Unit tests that do not set the secret get a
    fast local warning rather than a real client-credentials POST against a nonexistent Keycloak.

    MINT AT USE — never a stored token. Returns only the headers it managed to build; callers
    merge it into their own (trace headers, content-type) rather than the reverse.
    """
    headers: Dict[str, str] = {}
    try:
        headers["Authorization"] = "Bearer " + mint_token(
            client_id=client_id,
            client_secret=os.environ[secret_env],
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001 — see OBSERVE-PHASE note above
        # THE GAUGE NEEDS THE DISCRIMINANT. A token-less call caused by a mint FAILURE and one
        # from a caller that never minted both surface at the engine as `caller: none`; without a
        # discriminant a Keycloak blip reads as caller-readiness REGRESSING.
        #
        # X-Auth-Status IS DIAGNOSTIC ONLY AND MUST NEVER REACH AN AUTHORIZATION DECISION: it is
        # caller-asserted and therefore unverifiable. Legal to LOG, illegal to TRUST.
        headers["X-Auth-Status"] = f"mint-failed:{type(exc).__name__}"
        logging.getLogger(__name__).warning(
            "outbound call minting no token for client_id=%s (%s: %s) — proceeding "
            "UNAUTHENTICATED; the receiving engine records caller:none until %s is configured",
            client_id, type(exc).__name__, str(exc)[:120], secret_env,
        )
    return headers
