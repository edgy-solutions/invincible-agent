"""Human-readable engine names from a verb edge's provider / endpoint.

Pure — no FastAPI / DB — so it unit-tests without importing gateway (whose
import connects to Postgres). gateway.py imports these for the routing HUD's
"Handled by" label. RELEASE-AGNOSTIC by construction: anchor on the chart
COMPONENT name (`engine-<letter>` / `data-analyst`), never a release-prefixed
service name — the prefix is `iagent-` in the sandbox release but
`invincible-agent-` at work, and endpoints are now the full FQDN form
(`…-engine-a.<ns>.svc.cluster.local:8081`, the svcDomain/NO_PROXY fix).
"""
from __future__ import annotations

import re


def engine_name_from_provider(provider: str | None) -> str:
    """Best-effort engine name from a provider string, conventionally
    ``engine_<letter>_<role>`` (e.g. ``engine_w_weaviate_expert_…``). Falls
    back to the raw provider when the convention doesn't apply.
    """
    if not provider:
        return "Unknown engine"
    p = provider.lower()
    if p.startswith("engine_a"):
        return "Engine A"
    if p.startswith("engine_b"):
        return "Engine B"
    if p.startswith("engine_c"):
        return "Engine C"
    if p.startswith("engine_d_") or p == "engine_d":
        return "Engine D"
    if p.startswith("engine_da"):
        return "Engine DA"
    if p.startswith("engine_e"):
        return "Engine E"
    if p.startswith("engine_f"):
        return "Engine F"
    if p.startswith("engine_o"):
        return "Engine O"
    if p.startswith("engine_w"):
        return "Engine W"
    return provider


# Engines whose chart COMPONENT name doesn't follow engine-<letter>. Keyed on
# the release-invariant component (a substring of the service DNS regardless of
# release prefix). A new such engine also needs an endpoint-probe entry.
_NAMED_COMPONENTS = {
    "data-analyst": "Engine DA",
}

_ENGINE_LETTER_RE = re.compile(r"engine-([a-z]{1,2})\b")


def engine_name_from_endpoint(endpoint: str | None) -> str:
    """Engine name from a verb edge's endpoint URL — the fallback when the
    predicate has no provider (the Weaviate Predicate record stores only
    ``endpoint_url``). Endpoint shape:
    ``http://<release>-engine-<letter>[.<ns>.svc.cluster.local]:<port>/<route>``.

    Anchors on the component, so any release prefix and the bare-or-FQDN host
    both resolve. (Anchoring on ``iagent-engine-`` showed "Unknown engine" at
    work — release ``invincible-agent`` — on an otherwise-correct route,
    2026-07-21; the ``data-analyst`` exception was the 2026-06-24 sibling.)
    Empty string when nothing matches.
    """
    if not endpoint:
        return ""
    e = endpoint.lower()
    for component, name in _NAMED_COMPONENTS.items():
        if component in e:
            return name
    m = _ENGINE_LETTER_RE.search(e)
    if not m:
        return ""
    letter = m.group(1)
    return "Engine DA" if letter == "da" else f"Engine {letter.upper()}"
