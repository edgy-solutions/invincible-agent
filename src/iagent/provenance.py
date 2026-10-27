"""THE PROVENANCE BLOCK — provenance is a field, never a join.

ADR-0035 §4. **No assertion enters a graph without its provenance riding in the same write.**

WHY EMBEDDED AND NOT SIDECAR. A separate audit table you *could* join against always decays,
because the join is OPTIONAL and optional joins stop happening — the query that omits it is
shorter, works, and becomes the one everyone copies. Embedded provenance cannot be skipped:
reading the claim IS reading its origin.

This module is the reusable shape every ingestion inherits, so the decision is made ONCE. It is
pure — no store, no transport — for the same reason the decision-record contract is: the shape
must be testable without a graph, and the graph must be replaceable without touching the shape.

SOURCE AUTHORITY IS DISTANCE FROM TRUTH, NOT A RANKING OF PEERS (ADR-0035 §5). Where the
authoritative system is guarded, groups build convenient copies and those copies become
load-bearing while their export date recedes. So every assertion names the SAME
`authoritative_source` and differs in `obtained_via` + `as_of`. "Per the owning system, via a
manual export of unknown vintage" and "per the owning system, via last night's ETL" are
different facts, and a consumer must be able to see which one it has without asking anyone.
"""
from __future__ import annotations

from typing import Any, Optional

# HOW the claim was obtained — the degradation path, ordered nearest-to-truth. The ORDER is
# meaningful (it is distance from the authoritative system), not cosmetic.
#
# FIFTH RUNG: `user-drop` — a document hand-carried into the system by a non-technical user
# (ADR-0041 §2, decision recorded 2026-08-17; landed here 2026-09-30 with the ingestion seam,
# ADR-0041 §8). It was the FARTHEST rung until the sixth: `authoritative_source` is unchanged (the drop
# does not change who owns the truth, only how far this copy travelled from it), `as_of` will
# often be AS_OF_UNKNOWN, and `standing` is `supervised` — born-supervised, ADR-0034's default,
# arrived at without an exception. Appended at the END of the tuple deliberately: the order is
# the degradation distance, and user-drop was the least-trusted path until the sixth rung. The
# SDK's copy (iagent_mesh.provenance, lane/ca b68926a) carried it first. Census when it landed:
# no reader in src/ or agent_fleet/ reasons over this tuple by position; the one exhaustive
# reader is tests/test_provenance_block.py, which iterates it.
#
# SIXTH RUNG: `steward-corrected` — a claim a steward corrected by hand after automated
# extraction got it wrong. It ranks LAST, after user-drop (architect ruling 2026-10-10, relayed
# 2026-10-14); mirrors iagent_mesh.provenance at v0.9.10. It carries `corrected_by` and
# `extracted_value`, both required on this rung and refused on every other.
DIRECT, ETL, WAREHOUSE, MANUAL_EXPORT, USER_DROP, STEWARD_CORRECTED = (
    "direct", "etl", "warehouse", "manual-export", "user-drop", "steward-corrected")
OBTAINED_VIA = (DIRECT, ETL, WAREHOUSE, MANUAL_EXPORT, USER_DROP, STEWARD_CORRECTED)

# `as_of` when the truth-date is genuinely not knowable — e.g. an export with no recorded
# date. A SENTINEL, NEVER A BLANK: empty would collapse "we could not know" into "we forgot to
# record", and an analyst counting missing dates could not tell instrument failure from process
# fact. Same rule as the decision record's `none:no-composition`.
AS_OF_UNKNOWN = "unknown"

# PROV terms, cherry-picked per the standards posture — a future auditor meets vocabulary they
# already know rather than a private dialect.
PROV_DERIVED_FROM = "http://www.w3.org/ns/prov#wasDerivedFrom"
PROV_GENERATED_AT = "http://www.w3.org/ns/prov#generatedAtTime"

_REQUIRED = ("authoritative_source", "obtained_via", "as_of", "ingested_at", "ingest_run",
             "standing")


class ProvenanceIncomplete(ValueError):
    """An assertion without complete provenance. Refused at WRITE, never at query."""


def make_provenance(*, authoritative_source: str, obtained_via: str, as_of: Optional[str],
                    ingested_at: Any, ingest_run: str, standing: str,
                    derived_from: Optional[str] = None,
                    ingest_id: Optional[str] = None,
                    corrected_by: Optional[str] = None,
                    extracted_value: Optional[str] = None) -> dict:
    """Build the block. Every field is required; there are no convenient defaults.

    `standing` is FROZEN AT WRITE — the source's trust rung *at the moment this claim was
    made*. The record is immutable, and "what this source's standing is now" is a different
    fact from "what it was when this was written". Conflating them would let a later promotion
    retroactively upgrade evidence gathered under weaker standing, which is exactly the
    regime-mixing ADR-0034 refuses.

    `ingest_run` chains this claim into PIPELINE provenance for free: claim → run → sensor →
    source object → ETag. Every link already exists; naming the run here is what assembles
    them into one lineage instead of four disconnected facts.

    `ingest_id` names the DOCUMENT the claim came from (ruled 2026-09-30: a field on the block,
    not `derived_from`; the SDK's ProvenanceBlock gains `ingest_id: str | None`). It is what a
    rejection's sweep keys on and what the answer's provenance floor names. Optional, because
    only a hand-carried document has one; present in the block only when given, like
    `derived_from`. A blank one is refused: a sweep keyed on "" finds nothing and reports
    success.

    `corrected_by` / `extracted_value` ride only with `obtained_via='steward-corrected'`: both
    are required on that rung (`extracted_value` may be blank) and refused on every other.
    """
    if ingest_id is not None and not (isinstance(ingest_id, str) and ingest_id.strip()):
        raise ProvenanceIncomplete(
            f"ingest_id, when given, must be a non-blank string, got {ingest_id!r}; omit it "
            f"for a claim that did not come from an ingested document")
    if not authoritative_source:
        raise ProvenanceIncomplete(
            "authoritative_source is required — it names WHO OWNS THE TRUTH, and it is the "
            "same value for every path to that truth. A claim that cannot name its owning "
            "system is a claim whose distance from truth is unmeasurable")
    if obtained_via not in OBTAINED_VIA:
        raise ProvenanceIncomplete(
            f"obtained_via must be one of {OBTAINED_VIA}, got {obtained_via!r} — the path IS "
            f"the degradation, so an unknown path cannot be scored")
    if not as_of:
        raise ProvenanceIncomplete(
            f"as_of is required; use {AS_OF_UNKNOWN!r} when the truth-date is genuinely not "
            f"knowable. A BLANK collapses 'we could not know' into 'we forgot to record', and "
            f"those are different facts about the pipeline")
    if not ingest_run:
        raise ProvenanceIncomplete(
            "ingest_run is required — without it the claim cannot be chained back to the run, "
            "sensor and source object that produced it, and the lineage stops at this row")
    if not standing:
        raise ProvenanceIncomplete("standing is required (the source's rung AT WRITE TIME)")
    if obtained_via == STEWARD_CORRECTED:
        if not corrected_by or extracted_value is None:
            raise ProvenanceIncomplete(
                "obtained_via='steward-corrected' requires both corrected_by and "
                "extracted_value — a correction with no corrector or no record of what it "
                "replaced is not an auditable correction")
    elif corrected_by is not None or extracted_value is not None:
        raise ProvenanceIncomplete(
            f"obtained_via={obtained_via!r} but corrected_by/extracted_value was supplied — "
            f"those two fields assert 'this row was corrected', which only "
            f"obtained_via='steward-corrected' can be true of")
    block = {
        "authoritative_source": authoritative_source,
        "obtained_via": obtained_via,
        "as_of": as_of,
        "ingested_at": ingested_at,
        "ingest_run": ingest_run,
        "standing": standing,
    }
    if derived_from:
        block["derived_from"] = derived_from      # -> prov:wasDerivedFrom on serialization
    if ingest_id is not None:
        block["ingest_id"] = ingest_id
    if corrected_by:
        block["corrected_by"] = corrected_by
    if extracted_value is not None:
        block["extracted_value"] = extracted_value
    return block


def validate_provenance(block: Any) -> None:
    """Re-check a block that did not come from `make_provenance` — a future writer must not be
    able to bypass the constructor and land an unprovenanced claim."""
    if not isinstance(block, dict):
        raise ProvenanceIncomplete("provenance block must be a dict")
    missing = [f for f in _REQUIRED if not block.get(f)]
    if missing:
        raise ProvenanceIncomplete(
            f"provenance block is missing {missing} — an assertion without complete provenance "
            f"is refused at WRITE, because discovering it at query time means the corpus "
            f"already contains claims nobody can place")
    if block["obtained_via"] not in OBTAINED_VIA:
        raise ProvenanceIncomplete(f"bad obtained_via {block['obtained_via']!r}")
    corrected_by = block.get("corrected_by")
    extracted_value = block.get("extracted_value")
    if block["obtained_via"] == STEWARD_CORRECTED:
        if not corrected_by or extracted_value is None:
            raise ProvenanceIncomplete(
                "obtained_via='steward-corrected' requires both corrected_by and "
                "extracted_value — a correction with no corrector or no record of what it "
                "replaced is not an auditable correction")
    elif corrected_by is not None or extracted_value is not None:
        raise ProvenanceIncomplete(
            f"obtained_via={block['obtained_via']!r} but corrected_by/extracted_value is "
            f"present — those two fields assert 'this row was corrected', which only "
            f"obtained_via='steward-corrected' can be true of")


def require_provenance(assertion: dict, *, key: str = "provenance") -> dict:
    """WRITE-SIDE MANDATORY. Wrap any assertion-writer with this: it refuses the write rather
    than accepting a claim that cannot say where it came from.

    The doctrine line, so it is enforceable and not merely documented:
    **the claim that cannot say where it came from doesn't get written.**
    """
    validate_provenance((assertion or {}).get(key))
    return assertion


def is_stale(block: dict, *, now_date: str, max_age_days: int) -> Optional[bool]:
    """Is this claim older than the freshness contract? `None` means UNKNOWABLE.

    Returns None — never False — for `as_of: unknown`. An unknown vintage is not "fresh"; it is
    a claim whose age cannot be established, and reporting that as "not stale" would be the
    optimistic default this codebase keeps refusing. Callers decide what unknowable is worth,
    which is the point of ADR-0035 §5: consumers judge distance, the model only records it.
    """
    if block.get("as_of") == AS_OF_UNKNOWN:
        return None
    from datetime import date

    def _d(s):
        y, m, d = (int(x) for x in str(s)[:10].split("-"))
        return date(y, m, d)

    try:
        return (_d(now_date) - _d(block["as_of"])).days > max_age_days
    except Exception:  # noqa: BLE001 — an unparseable date is unknowable, not fresh
        return None
