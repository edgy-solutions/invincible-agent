"""Where FRACAS failure records come from: connectors that implement the SDK's
``SystemOfRecordQuery`` Protocol (iagent-mesh-sdk 0.9.9, ``iagent_mesh.systems_of_record``).

ADR-0056 Phase 1 read ``FAILURE_RECORDS`` directly because ``SystemOfRecordConnector.lookup``
returns at most ONE record per value. The SDK now ships the many-record sibling,
``query(value) -> Iterable[dict]``, and the verbs read through it. The engine does NOT import the
Protocol at runtime (it is structural, and an image built before the pin must still import this
file); a seal checks the sandbox connector against the real Protocol where the SDK has it.

THE SHAPE, DERIVED FROM THE PROTOCOL'S DOCSTRING and not invented here:
  * ``query`` returns an iterable of dicts, each carrying a connector-assigned ``record_id``
    plus the fields the matched row's ``lookup.returns`` names. Empty means "none found".
  * It must be RE-ITERABLE (we pass over it more than once), so we materialise it once.
  * A connector that cannot reach its source RAISES; nothing here converts that to an empty
    answer.
  * A citation is ``f"{connector}:{record_id}"``, built by the CALLER (this module), because the
    SDK does not format it.

The sandbox's connectors are the in-engine fixture, one per system of record, exactly the
"sandbox's one fake connector" the SDK's own ``SystemOfRecordConnector`` docstring describes.
Their ``returns`` are: ``failure_record_id`` (this engine's FR-nnnn), ``part_number``,
``platform``, ``failure_mode``, ``observed_on``. ``record_id`` is the connector's own id, the
suffix of the citation the fixture always carried, so every citation string is unchanged.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

try:  # flat in the image (/app), packaged in the repo — runbook §5, flat FIRST
    from entities import FAILURE_RECORDS, FailureRecord
except ImportError:  # pragma: no cover
    from agent_fleet.safety_agent.entities import FAILURE_RECORDS, FailureRecord  # type: ignore[no-redef]

#: The keys a ``query`` hit may be looked up BY. The verbs name which one they want.
BY_PART = "part_number"
BY_PLATFORM = "platform"


class FixtureFailureQuery:
    """One system of record's slice of the fixture, as a ``SystemOfRecordQuery``."""

    def __init__(self, connector: str, by: str) -> None:
        self.connector = connector
        self.by = by

    def query(self, value: str) -> Iterable[Dict[str, str]]:
        return [
            {
                "record_id": _connector_record_id(r),
                "failure_record_id": r.record_id,
                "part_number": r.part_number,
                "platform": r.platform,
                "failure_mode": r.failure_mode,
                "observed_on": r.observed_on,
            }
            for r in FAILURE_RECORDS
            if r.system_of_record == self.connector and getattr(r, self.by) == value
        ]


def _connector_record_id(r: FailureRecord) -> str:
    """The id the connector itself assigned: the part of the fixture citation after ``:``."""
    return r.citation.split(":", 1)[1]


def queries(by: str) -> List[Tuple[str, Any]]:
    """(connector name, SystemOfRecordQuery) for every system of record, derived from the
    fixture so a new system appears with no edit here. The seam a deployment (or a seal)
    replaces."""
    return [(name, FixtureFailureQuery(name, by))
            for name in sorted({r.system_of_record for r in FAILURE_RECORDS})]


def gather(by: str, value: str) -> List[FailureRecord]:
    """Every record any connector holds for ``value``, as ``FailureRecord`` with its citation
    built ``<connector>:<record_id>``. Connector errors propagate."""
    out: List[FailureRecord] = []
    for connector, q in queries(by):
        for hit in list(q.query(value)):
            out.append(FailureRecord(
                record_id=hit["failure_record_id"],
                part_number=hit["part_number"],
                platform=hit["platform"],
                system_of_record=connector,
                failure_mode=hit["failure_mode"],
                observed_on=hit["observed_on"],
                citation=f"{connector}:{hit['record_id']}",
            ))
    return out
