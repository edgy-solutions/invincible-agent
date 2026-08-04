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
import os

__all__ = ["ServiceTokenError", "mint_service_token"]


class ServiceTokenError(RuntimeError):
    """The service-identity mint failed, with the cause NAMED.

    Deliberately a plain exception, not ``dagster.Failure``: engine-a must not depend on Dagster.
    Each caller maps it to its own runtime's loud failure — the sensor to ``dagster.Failure`` (failed
    run), a Restate handler by letting it propagate (retryable; a Keycloak blip is transient infra,
    NOT an authorization denial, so it must NOT fail-and-release the way a 401 on the action does)."""


def mint_service_token(*, timeout: float = 15.0) -> str:
    """Mint a FRESH access token for the pipeline's service identity (``svc:review-starter``) via
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
    import httpx

    realm_url = os.environ["KEYCLOAK_REALM_URL"].rstrip("/")
    client_id = os.environ["REVIEW_STARTER_CLIENT_ID"]
    client_secret = os.environ["REVIEW_STARTER_CLIENT_SECRET"]
    token_url = f"{realm_url}/protocol/openid-connect/token"
    try:
        resp = httpx.post(
            token_url,
            data={"grant_type": "client_credentials", "client_id": client_id,
                  "client_secret": client_secret},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001 — transport failure is a loud, named failure, never silent
        raise ServiceTokenError(
            f"mint_service_token: Keycloak token endpoint unreachable at {token_url}: {exc}"
        ) from exc
    if resp.status_code != 200:
        raise ServiceTokenError(
            f"mint_service_token: client-credentials mint failed HTTP {resp.status_code} for "
            f"client {client_id!r} at {token_url}: {resp.text[:300]}"
        )
    tok = (resp.json() or {}).get("access_token")
    if not tok:
        raise ServiceTokenError(
            f"mint_service_token: token response carried no access_token: {resp.text[:300]}"
        )
    return tok
