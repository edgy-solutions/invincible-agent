"""ADR-0041 §2 — a fifth `obtained_via` rung, `user-drop`, for the ingestion seam.

The ADR is explicit that this is an amendment to a CLOSED ordered tuple (Consequences: "A
fifth `obtained_via` value is a change to a closed ordered tuple — the order is meaningful,
not cosmetic, so every consumer that reasons over it must be checked"). This seal is that
check: it asserts the rung exists, is ORDERED LAST (farthest from truth — user-drop is the
least-trusted path that exists today), and that `make_provenance`/`validate_provenance` accept
it exactly like the other four rather than needing a parallel code path.

RED BEFORE: on the pre-change `provenance.py`, `USER_DROP` does not exist and
`"user-drop" not in OBTAINED_VIA`, so every assertion below fails (see the report for the
red-before run).
"""
from __future__ import annotations

from src.iagent import provenance


def test_user_drop_is_a_declared_rung():
    assert provenance.USER_DROP == "user-drop"
    assert provenance.USER_DROP in provenance.OBTAINED_VIA


def test_user_drop_is_ordered_last_the_farthest_rung():
    # The order IS the degradation distance (ADR-0035 §5) — not cosmetic, so a rung inserted
    # in the middle would silently misstate every consumer that reasons over the ordering.
    assert provenance.OBTAINED_VIA[-1] == provenance.USER_DROP
    assert provenance.OBTAINED_VIA == (
        provenance.DIRECT, provenance.ETL, provenance.WAREHOUSE,
        provenance.MANUAL_EXPORT, provenance.USER_DROP,
    )


def test_make_provenance_accepts_user_drop_through_the_existing_constructor():
    # No parallel path — the ingestion seam must build its stamp through the SAME constructor
    # every other path uses, per ADR-0041 §2 ("not a new vocabulary").
    block = provenance.make_provenance(
        authoritative_source="acme-pdm",
        obtained_via=provenance.USER_DROP,
        as_of=provenance.AS_OF_UNKNOWN,
        ingested_at="2026-09-30T00:00:00Z",
        ingest_run="ingest-run-1",
        standing="supervised",
    )
    provenance.validate_provenance(block)
    assert block["obtained_via"] == "user-drop"


def test_an_unknown_rung_is_still_refused():
    # Positive control for the seal above — the constructor must still be discriminating, not
    # widened into accepting anything.
    try:
        provenance.make_provenance(
            authoritative_source="acme-pdm", obtained_via="carrier-pigeon",
            as_of=provenance.AS_OF_UNKNOWN, ingested_at="2026-09-30T00:00:00Z",
            ingest_run="ingest-run-1", standing="supervised",
        )
    except provenance.ProvenanceIncomplete:
        pass
    else:
        raise AssertionError("an unrecognised obtained_via rung was accepted")
