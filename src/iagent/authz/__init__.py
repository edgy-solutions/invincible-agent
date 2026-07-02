"""Authorization primitives — persona/domain entitlements against Topaz.

Per ADR-0026:
    * `TopazDirectoryClient` — thin HTTP client for topaz's Directory
      v3 REST endpoints. Used by `get_current_user` to enrich the
      logged-in User with their (persona, domain) entitlement matrix.
    * `EntitlementCache` — per-token in-process cache. Avoids hitting
      topaz on every request; validated at token-issue time, valid
      until token TTL.
    * `AuthorizationUnavailable` — raised when topaz can't be reached
      AND no cached matrix is available. Translated to HTTP 503 at
      the FastAPI layer per ADR-0026 "deny honestly, distinct from
      denial" — the failing party can tell "auth is down" from
      "you're denied."
"""

from iagent.authz.topaz_client import (
    AuthorizationUnavailable,
    CellNotEntitled,
    EntitlementCache,
    Entitlements,
    EntitlementCell,
    TopazDirectoryClient,
)

__all__ = [
    "AuthorizationUnavailable",
    "CellNotEntitled",
    "EntitlementCache",
    "Entitlements",
    "EntitlementCell",
    "TopazDirectoryClient",
]
