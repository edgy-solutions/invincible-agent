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

import importlib
import os
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


#: Deployment wiring for the REAL connectors. Comma-separated ``name=module:callable`` entries;
#: ``callable(by)`` returns a ``SystemOfRecordQuery`` for that lookup key. The SDK ships no
#: connector (its docstring: "THIS SDK DOES NOT SHIP ANY ROWS"), so the classes that read
#: ``sor-events-a`` or a Relyence export live in the deployment's overlay image, named here.
#: UNSET means the sandbox: the in-engine fixture. SET means ONLY the named connectors, never
#: the fixture alongside them (fabricated sandbox rows must not mix into a real history).
CONNECTORS_ENV = "FAILURE_SOURCE_CONNECTORS"

#: The fields a hit must carry for ``gather`` to build a record from it. ``failure_mode`` may be
#: None (the verb names that "unrecorded failure mode"), but the KEY must be present.
REQUIRED_HIT_FIELDS = ("record_id", "failure_record_id", "part_number", "platform",
                       "failure_mode", "observed_on")
_NULLABLE = ("failure_mode",)


class SourceUnavailable(Exception):
    """A system of record could not be read, or answered with a hit this engine cannot use.
    NEVER converted to an empty answer: on a failure history "could not read" must not read as
    "no failures". Carries the connector's name so the refusal can say which."""

    def __init__(self, connector: str, detail: str) -> None:
        super().__init__(f"{connector}: {detail}")
        self.connector = connector
        self.detail = detail


def _configured() -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    for entry in (os.getenv(CONNECTORS_ENV, "") or "").split(","):
        entry = entry.strip()
        if not entry:
            continue
        name, sep, target = entry.partition("=")
        if not sep or ":" not in target or not name.strip():
            raise SourceUnavailable(
                name.strip() or entry,
                f"{CONNECTORS_ENV} entry {entry!r} is not name=module:callable")
        out.append((name.strip(), target.strip()))
    return out


def queries(by: str) -> List[Tuple[str, Any]]:
    """(connector name, SystemOfRecordQuery) for every system of record. Deployment-configured
    (``FAILURE_SOURCE_CONNECTORS``) when set, else derived from the fixture so a new sandbox
    system appears with no edit here. The seam a deployment (or a seal) replaces."""
    configured = _configured()
    if not configured:
        return [(name, FixtureFailureQuery(name, by))
                for name in sorted({r.system_of_record for r in FAILURE_RECORDS})]
    out: List[Tuple[str, Any]] = []
    for name, target in configured:
        module, _, attr = target.partition(":")
        try:
            out.append((name, getattr(importlib.import_module(module), attr)(by)))
        except Exception as exc:  # noqa: BLE001 - import/attr/factory failure is a source fault
            raise SourceUnavailable(name, f"cannot build connector from {target}: "
                                          f"{type(exc).__name__}: {exc}") from exc
    return out


def _missing(hit: Any) -> List[str]:
    if not isinstance(hit, dict):
        return list(REQUIRED_HIT_FIELDS)
    return [f for f in REQUIRED_HIT_FIELDS
            if f not in hit or (hit[f] in (None, "") and f not in _NULLABLE)]


def gather(by: str, value: str) -> List[FailureRecord]:
    """Every record any connector holds for ``value``, as ``FailureRecord`` with its citation
    built ``<connector>:<record_id>``. ALL-OR-ERROR: one connector failing, or one malformed
    hit, raises ``SourceUnavailable`` (a partial history presented as complete is the one
    wrong answer). A record returned twice under the same citation is kept once."""
    out: List[FailureRecord] = []
    seen = set()
    for connector, q in queries(by):
        try:
            hits = list(q.query(value))
        except Exception as exc:  # noqa: BLE001
            raise SourceUnavailable(connector, f"{type(exc).__name__}: {exc}") from exc
        for hit in hits:
            missing = _missing(hit)
            if missing:
                raise SourceUnavailable(connector, f"hit lacks {missing}")
            citation = f"{connector}:{hit['record_id']}"
            if citation in seen:
                continue
            seen.add(citation)
            out.append(FailureRecord(
                record_id=hit["failure_record_id"],
                part_number=hit["part_number"],
                platform=hit["platform"],
                system_of_record=connector,
                failure_mode=hit["failure_mode"],
                observed_on=hit["observed_on"],
                citation=citation,
            ))
    return out
