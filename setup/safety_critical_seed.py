"""Seed `safety_critical = true` on the Component nodes the safety item records name.

WHY (architect, 2026-10-25/27). "Safety-critical" is a property of the Part in the graph, set by the
safety pass; a hard-coded list must not decide it. This is the one-shot migration that carries the
fixture's current answer onto the graph so the list can stop being the authority. It is folded into
the Neo4j prime (`setup/prime_databases.py::prime_neo4j`), which the prime-substrate hook runs on
install and upgrade, so the state is reproduced by the bootstrap and never hand-run.

WHAT IT DOES, and nothing else:
  * `MATCH (c:Component {mpn: $mpn}) SET c.safety_critical = true` once per part number.
  * MATCH, never MERGE or CREATE: a part no notice has produced yet is NOT created as a bare node.
    The consequence is stated, not hidden: a Component that does not exist at prime time, or whose
    `mpn` spelling differs from the record's, is not touched, and this step reports how many nodes
    each part matched so a miss is visible rather than a silent success.
  * Idempotent: SET of the same value; running it twice issues the same writes and changes nothing.
  * Writes one property, `safety_critical`; never unsets, never touches another property.

The part numbers are READ from the safety item records (`entities.SAFETY_ITEMS`), never restated.
The records carry no critical meaning of their own; criticality is this graph property.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

STATEMENT = (
    "MATCH (c:Component {mpn: $mpn})\n"
    "SET c.safety_critical = true\n"
    "RETURN count(c) AS matched"
)


def part_numbers() -> list:
    """The part numbers the records name, in record order, de-duplicated."""
    from agent_fleet.safety_agent.entities import SAFETY_ITEMS
    seen: dict = {}
    for item in SAFETY_ITEMS:
        seen.setdefault(item.part_number, None)
    return list(seen)


def seed(session) -> dict:
    """Run the statement once per part number on `session`; returns {part_number: nodes matched}."""
    matched = {}
    for pn in part_numbers():
        record = session.run(STATEMENT, mpn=pn).single()
        matched[pn] = int(record["matched"]) if record is not None else 0
    return matched
