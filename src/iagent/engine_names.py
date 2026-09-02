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
    # engine-fin (finance, ADR-0045). MEASURED 2026-09-01: the HUD rendered
    # "Handled by: Unknown engine" on a finance answer that had routed perfectly —
    # Program 0.97 -> finVarianceAnalysis 0.95 -> VarianceDecomposition. The whole
    # chain worked and the engine could not be named.
    #
    # WHY IT FELL THROUGH: `_ENGINE_LETTER_RE` matches `engine-` plus ONE OR TWO
    # letters. `engine-fin` is three, so the regex misses it, and it was absent here.
    #
    # "ENGINE F" IS ALREADY TAKEN, by the presentation agent above — which is the
    # same collision that forced the component to be `engine-fin` rather than
    # `engine-f` in the first place. So the display name is disambiguated rather
    # than duplicated; a HUD reading "Engine F" for both would be worse than
    # "Unknown".
    "engine-fin": "Engine F (Finance)",
}

# NOT ENGINES AT ALL — and that is the point of a separate map.
#
# The seeding answer is produced by a BFF ORCHESTRATION, not by an engine. Asked for its
# handler, the HUD rendered "Unknown engine" — a captured fact that was not a true one. The
# handler was known; it simply was not the KIND of thing this module could name.
#
# The tempting fix was an entry in `_NAMED_COMPONENTS` above, which would have made the BFF
# impersonate an engine so an existing lookup would succeed. That is the same
# classification-is-not-existence shortcut cortex refused when it declined to invent a
# placeholder COMPONENT for an archetype that is acted on rather than drawn — and it refused
# it for the better reason: the model gains the category instead. A handler declares one of:
#
#     engine        answers a typed question          -> "Engine W"
#     orchestration composes several governed asks    -> "BFF orchestration"
#
# Both are enumerable and neither impersonates the other. Keyed on the release-invariant
# chart component, per this module's standing rule — `iagent-` in sandbox,
# `invincible-agent-` at work, and the endpoint may be bare or FQDN.
_NON_ENGINE_HANDLERS = {
    "cortex-bff": "BFF orchestration",
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


def handler_name_from_endpoint(endpoint: str | None) -> str:
    """The HUD's "Handled by" label for ANY handler — engine or not.

    Checks the non-engine handlers first, then defers to
    :func:`engine_name_from_endpoint`. Separate from that function on purpose: its name
    promises an ENGINE, and a caller reading `engine_name_from_endpoint` and receiving
    "BFF orchestration" would reasonably conclude the mesh had grown an engine by that
    name. One function per claim.

    Empty string when nothing matches — the caller keeps whatever it already had, so an
    unrecognised handler still degrades to "Unknown engine" rather than to a blank label.
    """
    if not endpoint:
        return ""
    e = endpoint.lower()
    for component, label in _NON_ENGINE_HANDLERS.items():
        if component in e:
            return label
    return engine_name_from_endpoint(endpoint)
