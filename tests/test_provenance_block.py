"""PROVENANCE IS A FIELD, NEVER A JOIN — refused at write, not discovered at query.

ADR-0035 §4. The doctrine in one line: **the claim that cannot say where it came from doesn't
get written.** Sidecar provenance decays because the join is optional and optional joins stop
happening; embedded provenance cannot be skipped because reading the claim is reading its
origin.

Three properties carry it, and each has an obvious way to be softened into uselessness:
  1. WRITE-SIDE MANDATORY — an incomplete block is refused, loudly, at ingest.
  2. SENTINELS, NEVER BLANKS — `as_of: unknown` says "could not know"; empty says "forgot",
     and an analyst counting gaps cannot tell instrument failure from process fact.
  3. UNKNOWN VINTAGE IS NOT FRESH — staleness returns None, never False, so nobody's
     optimistic default silently promotes an undateable claim.

Run:  uv run --frozen --extra agent-fleet python -m pytest tests/test_provenance_block.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.iagent.provenance import (  # noqa: E402
    AS_OF_UNKNOWN, MANUAL_EXPORT, OBTAINED_VIA, ProvenanceIncomplete,
    is_stale, make_provenance, require_provenance, validate_provenance,
)


def _blk(**over):
    kw = dict(authoritative_source="pdm", obtained_via="etl", as_of="2026-07-30",
              ingested_at=1, ingest_run="run-abc", standing="monitored")
    kw.update(over)
    return make_provenance(**kw)


# ── 1. write-side mandatory ────────────────────────────────────────────────
@pytest.mark.parametrize("field", ["authoritative_source", "as_of", "ingest_run", "standing"])
def test_an_incomplete_block_is_refused_at_construction(field):
    with pytest.raises(ProvenanceIncomplete):
        _blk(**{field: ""})


def test_a_writer_cannot_bypass_the_constructor():
    """A future writer that hand-builds a dict must still be refused — the guard belongs to the
    ASSERTION, not to one convenience constructor."""
    with pytest.raises(ProvenanceIncomplete):
        require_provenance({"provenance": {"authoritative_source": "pdm"}})


def test_a_complete_assertion_passes_through():
    a = {"subject": "part-1", "provenance": _blk()}
    assert require_provenance(a) is a


def test_an_unknown_path_cannot_be_scored():
    """`obtained_via` IS the degradation, so an unrecognized path has no distance."""
    with pytest.raises(ProvenanceIncomplete):
        _blk(obtained_via="carrier-pigeon")


# ── 2. sentinels, never blanks ─────────────────────────────────────────────
def test_unknown_vintage_is_a_sentinel_not_an_empty():
    b = _blk(obtained_via=MANUAL_EXPORT, as_of=AS_OF_UNKNOWN)
    assert b["as_of"] == AS_OF_UNKNOWN
    validate_provenance(b)


# ── 3. unknown vintage is NOT fresh ────────────────────────────────────────
def test_staleness_of_an_undateable_claim_is_None_not_False():
    """The optimistic default this codebase keeps refusing. False would read as 'fresh'."""
    assert is_stale(_blk(as_of=AS_OF_UNKNOWN), now_date="2026-08-01", max_age_days=90) is None


def test_an_unparseable_date_is_unknowable_not_fresh():
    assert is_stale(_blk(as_of="last tuesday"), now_date="2026-08-01", max_age_days=90) is None


def test_a_real_date_is_scored_both_ways():
    assert is_stale(_blk(as_of="2026-07-30"), now_date="2026-08-01", max_age_days=90) is False
    assert is_stale(_blk(as_of="2026-01-01"), now_date="2026-08-01", max_age_days=90) is True


# ── the lineage chain + frozen standing ────────────────────────────────────
def test_the_block_chains_into_pipeline_provenance():
    """ingest_run is what assembles claim -> run -> sensor -> source object -> ETag into ONE
    lineage instead of four disconnected facts."""
    assert _blk(ingest_run="dagster-run-xyz")["ingest_run"] == "dagster-run-xyz"


def test_standing_is_recorded_per_claim_so_it_can_be_frozen():
    """The source's rung AT WRITE TIME. Records are immutable, and 'standing now' is a
    different fact from 'standing then' — conflating them lets a promotion retroactively
    upgrade evidence gathered under weaker standing."""
    early, later = _blk(standing="commissioning"), _blk(standing="trusted")
    assert early["standing"] != later["standing"]


def test_every_path_is_expressible():
    for via in OBTAINED_VIA:
        assert _blk(obtained_via=via)["obtained_via"] == via
