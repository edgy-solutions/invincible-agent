"""Seed `safety_critical = true` on the existing Component nodes the rule names.

WHY (architect, 2026-10-25/28). "Safety-critical" is a property of the Component in the graph. The
RULE that decides it is `agent_fleet.safety_agent.safety_critical`; this step applies it to the
nodes that already exist, and promotion applies the same rule to every node it writes. The seed is
folded into the Neo4j prime (`setup/prime_databases.py::prime_neo4j`), which the prime-substrate
hook runs on install and upgrade, so the state is reproduced by the bootstrap and never hand-run.

WHAT IT DOES, and nothing else:
  * `MATCH (c:Component:{DOMAIN} {mpn: $mpn}) SET c.safety_critical = true`, once per part number
    the RULE lists for the domain. Scoped to the engine's domain label: the same mpn under another
    domain label is not touched.
  * MATCH, never MERGE or CREATE: a part no notice has produced yet is not created as a bare node.
  * A 0-match is NEVER silent and NEVER fails setup (a fresh install has no Components yet). It is
    returned in `unmatched`; the prime records the list on its `:PrimeRun` row, which
    `scripts/version_census.py` already reads.
  * Idempotent: SET of the same value. Writes one property; never unsets, never touches another.

The part numbers come from the rule (`safety_critical.mpns`), never from the records directly and
never restated here.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from agent_fleet.safety_agent import safety_critical as rule  # noqa: E402

#: The label is interpolated, so it is validated -- the same pattern promotion_stores uses.
_DOMAIN_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")

DOMAIN = rule.DOMAIN


def statement(domain: str) -> str:
    if not isinstance(domain, str) or not _DOMAIN_RE.match(domain):
        raise ValueError(f"domain {domain!r} does not match {_DOMAIN_RE.pattern}")
    return (
        f"MATCH (c:Component:{domain} {{mpn: $mpn}})\n"
        "SET c.safety_critical = true\n"
        "RETURN count(c) AS matched"
    )


STATEMENT = statement(DOMAIN)


def seed(session, domain: str = DOMAIN) -> dict:
    """Apply the rule to the existing nodes of `domain`.

    Returns {"matched": {mpn: nodes}, "unmatched": [mpn, ...]} -- every listed part appears in
    exactly one of them. Never raises on a 0-match.
    """
    stmt = statement(domain)
    matched, unmatched = {}, []
    for pn in rule.mpns(domain):
        record = session.run(stmt, mpn=pn).single()
        n = int(record["matched"]) if record is not None else 0
        matched[pn] = n
        if n == 0:
            unmatched.append(pn)
    return {"matched": matched, "unmatched": unmatched}
