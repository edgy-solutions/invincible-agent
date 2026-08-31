"""Where the BFF is, resolved ONCE for every caller that needs to know.

TWO ESCAPERS ARE TWO CHANCES TO DISAGREE. The seeding verb's registration (cortex-bff, which
bakes an ``endpoint_url`` into the verb edge) and the supervisor's vault redemption (the
Dagster user-code pod, which calls ``/internal/identity/redeem``) both need the BFF's base
URL. They ran on two different env vars with two different spellings and one of them was
wrong, so this module is the single answer both import.

── THE DEFECT THIS EXISTS TO CLOSE, 2026-08-31, from a live failure at work ──────────────

    ProxyError: HTTPConnectionPool(host='proxygov...', port=80): Max retries exceeded with
    url: http://iagent-cortex-bff:8090/canvas/seed
    (Caused by ProxyError('Unable to connect to proxy', RemoteDisconnected(...)))

An IN-CLUSTER call was handed to a CORPORATE PROXY. Three compounding mistakes, all in one
hardcoded default:

1. **A NAME THAT DID NOT EXIST.** The registration read ``CORTEX_BFF_PUBLIC_URL``, which no
   chart sets. The chart has supplied ``CORTEX_BFF_URL`` since long before — release-aware
   and FQDN-formed — and its own comment warns of "the same self-advertisement trap as
   ENGINE_*_PUBLIC_URL". The invented name was that trap, spelled out.
2. **A BARE HOST.** ``iagent-cortex-bff:8090`` has NO DOTS, so it cannot suffix-match a
   ``NO_PROXY`` entry of ``.svc`` / ``.svc.cluster.local``. Under a corporate proxy the
   in-cluster call is therefore proxied and fails. **This is chart 0.3.22's defect exactly**
   — fixed there for every engine URL, and reintroduced here by a literal.
3. **A SANDBOX RELEASE PREFIX.** ``iagent-`` is the sandbox release; work runs
   ``invincible-agent-``. The default named a service that does not exist there.

AND THE PART THAT MAKES IT EXPENSIVE: ``endpoint_url`` is baked into the verb edge at
REGISTRATION time. Fixing the environment is not enough — **cortex-bff must re-register to
overwrite the edge**, which is the same operator note chart 0.3.22 had to write.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

__all__ = ["cortex_bff_base_url", "host_is_bare"]

#: Last-resort only. Kept so a bare `python -m` run outside Kubernetes still points
#: somewhere, NOT as a deployment default — every deployment path sets CORTEX_BFF_URL.
_LAST_RESORT = "http://iagent-cortex-bff:8090"


def host_is_bare(url: str) -> bool:
    """True when the URL's host has no dot — the shape a NO_PROXY suffix cannot match.

    This is the whole tell for the proxy failure, and it is checkable in one line, which is
    why it is worth checking rather than trusting a value to be well-formed.
    """
    rest = url.split("://", 1)[-1]
    host = rest.split("/", 1)[0].split(":", 1)[0]
    return bool(host) and "." not in host


def cortex_bff_base_url() -> str:
    """The BFF's in-cluster base URL, without a trailing slash.

    Preference order, and the order is the argument:

    1. ``CORTEX_BFF_URL`` — what the CHART sets, built from the release name and the
       ``svcDomain`` helper, so it is release-aware and fully qualified. Always prefer the
       value an operator's chart computed over one this code guessed.
    2. ``CORTEX_BFF_PUBLIC_URL`` — DEPRECATED alias, accepted only so a cluster where
       somebody set it while chasing this bug keeps working. Warns.
    3. ``_LAST_RESORT`` — bare and sandbox-prefixed. Warns loudly, because reaching it in a
       cluster means the chart's value did not arrive.
    """
    val = (os.getenv("CORTEX_BFF_URL") or "").strip()
    if not val:
        legacy = (os.getenv("CORTEX_BFF_PUBLIC_URL") or "").strip()
        if legacy:
            logger.warning(
                "cortex-bff URL came from CORTEX_BFF_PUBLIC_URL, which no chart sets and "
                "which this code should never have invented. Prefer CORTEX_BFF_URL — the "
                "chart computes it release-aware and fully qualified."
            )
            val = legacy
    if not val:
        val = _LAST_RESORT
        logger.warning(
            "cortex-bff URL fell back to the hardcoded %s. In a cluster this means "
            "CORTEX_BFF_URL did not arrive: the host carries the SANDBOX release prefix and "
            "is BARE, so under a corporate proxy the in-cluster call will be proxied and "
            "fail. Set CORTEX_BFF_URL.", _LAST_RESORT,
        )

    val = val.rstrip("/")

    # A BARE HOST IS ANNOUNCED WHEREVER IT COMES FROM, including from an operator's own
    # override. The failure it causes surfaces as a ProxyError against a host nobody
    # configured here, three layers from its cause — one warning at resolution time is the
    # cheapest place in the system to notice it.
    if host_is_bare(val):
        logger.warning(
            "cortex-bff URL %r has a BARE host (no dots). It cannot suffix-match a NO_PROXY "
            "entry of .svc/.svc.cluster.local, so behind a corporate proxy this call will be "
            "handed to the proxy and fail. Chart 0.3.22 fixed exactly this for engine URLs; "
            "use the fully-qualified form.", val,
        )
    return val
