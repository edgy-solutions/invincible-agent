"""THE RULE: is this part safety-critical in this domain?

One callable, the only place the decision is made. Ruled 2026-10-28: "safety-critical" is the graph
property `safety_critical` on the Component; this rule decides what it is SET to, and it is applied
on EVERY Component write:

  * existing nodes  -> `setup/safety_critical_seed.py` (the prime-substrate hook), via `mpns()`
  * new nodes       -> the promotion path (cortex-bff), via `safety_critical(mpn, domain)`

Both call this module and neither restates it. A caller that decides criticality any other way is
a second implementation, and tests/safety/test_the_safety_critical_rule_is_the_only_decision.py
reds on it.

WHERE IT LIVES, and why. It is stdlib-only and sits in `agent_fleet/safety_agent/`, a tree both
callers' images ship whole: `dagster-control-plane` (Dockerfile.dagster: `COPY . /app`) and
`cortex-bff` (Dockerfile.agent with AGENT_DIR=. : `COPY ./ /app/`, PYTHONPATH /app). The same
import path works in both: `agent_fleet.safety_agent.safety_critical`. (Per-engine images flatten
their own tree, so the engine itself imports it flat-first, like its siblings.)

DOMAIN. Components are labelled `Component:{domain}` (promotion_stores `_WRITE_EDGE_CYPHER`) and
carry no domain property. `DOMAIN` is the domain Engine S registers with
(`main.py` `DOMAINS = ["SUSTAINMENT"]`); a test reads main.py by AST and fails if they differ. A part
is safety-critical in THIS engine's domain only: the same mpn in another domain is not marked.

The records (`entities.SAFETY_ITEMS`) are entity data and carry no critical meaning; this rule is
what reads them for criticality, until the graph read (a mesh SDK call) replaces it.
"""
from __future__ import annotations

try:  # flat in the engine image (/app), packaged in the repo -- flat FIRST (runbook §5)
    from entities import SAFETY_ITEMS
except ImportError:
    from agent_fleet.safety_agent.entities import SAFETY_ITEMS  # type: ignore[no-redef]

#: The domain Engine S registers with. Sealed equal to main.py's `DOMAINS` by AST.
DOMAIN = "SUSTAINMENT"


def mpns(domain: str) -> list:
    """Every part number that is safety-critical in `domain`, in record order, de-duplicated.

    The enumerable form of `safety_critical` -- the same decision, listed -- for the seed.
    """
    if domain != DOMAIN:
        return []
    return list(dict.fromkeys(item.part_number for item in SAFETY_ITEMS))


def safety_critical(mpn: str, domain: str) -> bool:
    """True iff `mpn` is safety-critical in `domain`. Exact string match, as the graph's MATCH is."""
    return isinstance(mpn, str) and mpn in mpns(domain)
