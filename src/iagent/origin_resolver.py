"""The origin RESOLVER and the SUGGESTION it builds (architect ruling 2026-10-02, "ORIGIN, not
audience", item 2; SDK 0.9.7 `iagent_mesh.systems_of_record`).

Algorithm, quoted from the SDK module's own docstring so this file can be checked against it:
"extracted identity -> first matching system's pattern -> connector lookup -> origin from the
record. Miss or no pattern -> origin unresolved, visible to the dropper only." This module runs
that algorithm; the SDK ships only the row shape, the pure match step, and the connector
Protocol -- never the resolver or any row (see that module's docstring).

`systems()` composes this platform's seed (README only -- the row set is deployment-owned, same
discipline as `content_kinds.py`) with `SYSTEMS_OF_RECORD_OVERLAY_DIRS` overlays, through
`iagent_mesh.systems_of_record.compose` (ADR-0036). FAIL CLOSED, cached on success only -- same
posture as `content_kinds.registrations()` and for the same reason: a silently-empty registry
here would not refuse anything, it would just stop suggesting origins, which is a silent
correctness regression a caller should be able to tell apart from "the resolver ran and found
nothing."

`CONNECTORS` is this deployment's registry of connector NAMES -> `SystemOfRecordConnector`
instances (one method, `lookup(value) -> dict | None`, see the SDK module). Sandbox ships one
fake, `"sandbox-fake"`, for the seal: a fixed value hits a fixed record, everything else misses.
`validate_connectors_known` runs at the first `systems()` load -- an unknown connector name in a
composed row is a load-time refusal, never a silent miss (the SDK's own "prefix-registry failure
class").

`resolve(artifact)` does not raise on a miss -- a system's pattern not matching, or a connector
lookup missing, are both ordinary outcomes (the SDK protocol's own "no third state"), not errors.
It returns `None` for "origin unresolved" either way; the caller's /ingest wiring decides what an
unresolved origin means for that artifact (today: visible to the dropper only, unchanged).
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from iagent_mesh.systems_of_record import SystemOfRecord, SystemOfRecordConnector

#: The platform seed: README only, no rows. See module docstring.
_SEED_DIR = Path(__file__).resolve().parents[2] / "policy" / "systems_of_record"

#: Colon/pathsep-separated overlay directories -- read the same way `content_kinds.py` reads
#: `CONTENT_KIND_OVERLAY_DIRS`.
_OVERLAY_DIRS_ENV = "SYSTEMS_OF_RECORD_OVERLAY_DIRS"

#: `obtained_via` for a system-of-record hit (ruling 2): this measures HOW the origin was
#: resolved, which is always "an authoritative source answered", regardless of which system.
_OBTAINED_VIA_RECORD = "authoritative_source"

_SYSTEMS_CACHE: "tuple[SystemOfRecord, ...] | None" = None


class _SandboxFakeConnector:
    """`CONNECTORS["sandbox-fake"]`: one fixed value hits one fixed record; everything else is a
    miss. Exists only so the sandbox (which ships zero real systems-of-record rows) still has a
    connector to validate at load, and a TEST-ONLY system-of-record row can prove the hit path
    end to end (spec section 6's own requirement) without a real external system."""

    FIXED_VALUE = "SANDBOX-FAKE-0001"
    FIXED_RECORD = {"owner_domain": "sandbox-domain", "program": "sandbox-program"}

    def lookup(self, value: str) -> dict[str, str] | None:
        return dict(self.FIXED_RECORD) if value == self.FIXED_VALUE else None


#: This deployment's connector registry: name -> instance. Sandbox ships the one fake above.
CONNECTORS: dict[str, "SystemOfRecordConnector"] = {"sandbox-fake": _SandboxFakeConnector()}


def systems() -> "tuple[SystemOfRecord, ...]":
    """Every composed system-of-record row (seed + overlays), cached on success.

    Raises whatever `iagent_mesh.systems_of_record.compose` raises (a row the SDK's
    `SystemOfRecord` validator rejects), and raises `UnknownConnector` (via
    `validate_connectors_known`) if any composed row names a connector not in `CONNECTORS` --
    fail closed, no empty fallback. See module docstring.
    """
    global _SYSTEMS_CACHE
    if _SYSTEMS_CACHE is not None:
        return _SYSTEMS_CACHE
    from iagent_mesh.systems_of_record import compose, validate_connectors_known  # noqa: PLC0415

    raw = (os.getenv(_OVERLAY_DIRS_ENV) or "").strip()
    overlay_dirs = [p for p in (s.strip() for s in raw.split(os.pathsep)) if p] if raw else []
    rows = tuple(compose(_SEED_DIR, overlay_dirs))
    validate_connectors_known(rows, CONNECTORS.keys())
    _SYSTEMS_CACHE = rows
    return rows


def _matched_value(identity: dict[str, Any], system: "SystemOfRecord") -> str | None:
    """Which of `identity`'s values WON the match for `system` -- the same walk
    `match_system_of_record` performs internally, repeated here because that function returns
    only the winning SYSTEM, never the field/value that matched it, and the resolver needs the
    value itself to call the connector and to cite it in `evidence.citation`."""
    for field in system.identity.fields:
        value = identity.get(field)
        if value is not None and re.search(system.identity.pattern, value):
            return value
    return None


def resolve(artifact: dict[str, Any]) -> dict[str, Any] | None:
    """`artifact` is a `/ingest` manifest (or anything carrying the same `ingest_id`,
    `dropped_by.authz_id` and `metadata` shape). Identity is the drop's DECLARED metadata
    (`artifact.get("metadata")`) -- never inferred or extracted by this module.

    Returns the `origin_suggestion` trigger's facts dict on a hit (every key
    `policy/triggers/origin_suggestion.yaml`'s `requires:` names, non-empty), or `None` on a
    miss -- no system's pattern matched, or the matched system's connector lookup missed.
    """
    from iagent_mesh.systems_of_record import match_system_of_record  # noqa: PLC0415

    identity = artifact.get("metadata") or {}
    sor = match_system_of_record(identity, systems())
    if sor is None:
        return None
    value = _matched_value(identity, sor)
    if value is None:
        return None
    connector = CONNECTORS.get(sor.lookup.connector)
    if connector is None:
        return None
    record = connector.lookup(value)
    if record is None:
        return None
    artifact_id = artifact["ingest_id"]
    return {
        "kind": "origin_suggestion",
        "suggestion_id": f"origin:{artifact_id}:{sor.id}",
        "artifact_id": artifact_id,
        "dropped_by": {"authz_id": artifact["dropped_by"]["authz_id"]},
        "suggested": {
            "owner_domain": sor.owner_domain,
            "program": record[sor.program_field],
            "obtained_via": _OBTAINED_VIA_RECORD,
        },
        "evidence": {
            "source": sor.id,
            "citation": f"{sor.lookup.connector}:{value}",
        },
    }
