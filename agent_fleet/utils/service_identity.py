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


def mint_token(*, client_id: str, client_secret: str, realm_url: str = "",
               timeout: float = 15.0) -> str:
    """Mint a fresh access token for AN EXPLICITLY NAMED client identity.

    THE GENERAL MINT. Every caller supplies ITS OWN credentials, because every service
    identity has its own — that is what makes them identities. Added 2026-08-07 after
    `mint_service_token()` (below) was found to be review-starter-SPECIFIC behind a GENERAL
    NAME: the supervisor was wired against the name and would have authenticated as
    `svc:review-starter`, carrying that role's can_invoke(mesh:startReview) on every
    specialist dispatch — the confused deputy, introduced while fixing the confused deputy.

    THE MINT'S WITNESS IS THE DECODED SUBJECT, NOT THE 200. A mint that returns a token
    proves a mint happened; it does not prove WHOSE. Every new call site decodes its first
    token and asserts the identity — the standing procedure that would have caught the bug
    above in minutes.
    """
    import httpx

    realm = (realm_url or os.environ["KEYCLOAK_REALM_URL"]).rstrip("/")
    token_url = f"{realm}/protocol/openid-connect/token"
    try:
        resp = httpx.post(
            token_url,
            data={"grant_type": "client_credentials", "client_id": client_id,
                  "client_secret": client_secret},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001
        raise ServiceTokenError(
            f"mint_token: Keycloak token endpoint unreachable at {token_url}: {exc}"
        ) from exc
    if resp.status_code != 200:
        raise ServiceTokenError(
            f"mint_token: client-credentials mint failed HTTP {resp.status_code} for "
            f"client {client_id!r} at {token_url}: {resp.text[:300]}"
        )
    tok = (resp.json() or {}).get("access_token")
    if not tok:
        raise ServiceTokenError("mint_token: token response carried no access_token")
    return tok


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
