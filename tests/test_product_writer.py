"""PRODUCT WRITER — canonical-only, provenance-blocked, built BEHIND the contract.

ADR-0035 packet 2 step 3. The real mappings never enter this repo (the restricted-boundary rule
at the data plane), so the writer is sealed against a SYNTHETIC mapping deliberately as lossy as
the template permits — which is stronger than a real one, because a real mapping will be some
subset of these degradations.

Two boundaries, both structural rather than conventional:
  1. THE WRITER NEVER SEES SOURCE COLUMNS — a leaked column is refused, not passed through.
  2. NO ASSERTION LANDS WITHOUT COMPLETE PROVENANCE — refused at write, loudly.

Run:  uv run --frozen --extra agent-fleet python -m pytest tests/test_product_writer.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.iagent.product_writer import (  # noqa: E402
    CanonicalAssertionInvalid, as_of_for, product_graph, unmappable_report,
    validate_canonical, write_assertions,
)
from src.iagent.provenance import AS_OF_UNKNOWN, make_provenance  # noqa: E402
from tests.fixtures.failure_path.synthetic_mapping import (  # noqa: E402
    SYNTHETIC_ETL_MAPPING, SYNTHETIC_EXPORT_MAPPING,
    assert_evokes_the_degradations, assert_paths_can_disagree,
)


def _prov(**over):
    kw = dict(authoritative_source="windchill", obtained_via="manual-export",
              as_of=AS_OF_UNKNOWN, ingested_at=1, ingest_run="run-1", standing="commissioning")
    kw.update(over)
    return make_provenance(**kw)


def _usage(**over):
    a = {"kind": "PartUsage", "fields": {"parent": "P1", "child": "C1", "quantity": 2},
         "provenance": _prov()}
    a.update(over)
    return a


# ── boundary 1: the writer never sees source columns ───────────────────────
def test_a_leaked_source_column_is_refused():
    """The boundary that keeps the mapping whole. If the writer accepted a source column it
    would grow a per-source branch the first time two sources disagreed, and the mapping would
    then live half in a declared contract and half in code."""
    with pytest.raises(CanonicalAssertionInvalid) as exc:
        validate_canonical({"kind": "PartUsage",
                            "fields": {"parent": "P1", "COL_B": "leaked"},
                            "provenance": _prov()})
    assert "SOURCE COLUMN leaked" in str(exc.value)


def test_an_unknown_canonical_kind_is_refused():
    with pytest.raises(CanonicalAssertionInvalid):
        validate_canonical({"kind": "Widget", "fields": {"x": 1}, "provenance": _prov()})


# ── boundary 2: provenance is mandatory at write ───────────────────────────
def test_an_assertion_without_provenance_is_refused():
    with pytest.raises(CanonicalAssertionInvalid) as exc:
        validate_canonical({"kind": "Part", "fields": {"partNumber": "X"}})
    assert "provenance" in str(exc.value).lower()


def test_an_incomplete_provenance_block_is_refused():
    bad = dict(_prov()); bad.pop("ingest_run")
    with pytest.raises(CanonicalAssertionInvalid):
        validate_canonical({"kind": "Part", "fields": {"partNumber": "X"}, "provenance": bad})


# ── all-or-nothing: a half-ingested source is worse than none ──────────────
def test_validation_runs_over_the_whole_batch_before_any_write():
    """A partial product structure is worse than none: the missing rows are indistinguishable
    from parts that genuinely have no usage."""
    written = []
    batch = [_usage(), {"kind": "PartUsage", "fields": {"BAD": 1}, "provenance": _prov()}]
    with pytest.raises(CanonicalAssertionInvalid):
        write_assertions(batch, writer=written.append)
    assert written == [], "a batch with one bad assertion wrote rows anyway"


def test_a_clean_batch_writes_to_the_dedicated_product_graph():
    written = []
    res = write_assertions([_usage(), _usage()], writer=written.append)
    assert res["written"] == 2
    assert all(w["graph"].endswith("_PRODUCT") for w in written)


def test_product_assertions_never_land_in_a_vocabulary_or_prime_graph():
    g = product_graph("SUSTAINMENT")
    assert g.endswith("_PRODUCT")
    assert "_INSTANCES" not in g and "prime" not in g.lower()


# ── as_of: the single most consequential lie this model could tell ─────────
def test_ingest_time_is_never_substituted_for_truth_time_unless_declared():
    """Substituting ingest time for truth time makes a stale mirror look live. Allowed only
    where the mapping explicitly declares they are the same — true for a direct read, false for
    any export or copy."""
    m = {"as_of": {"strategy": "ingest-time-is-truth-time", "ingest_time_is_truth_time": False}}
    assert as_of_for(m, row_value="2026-08-01") == AS_OF_UNKNOWN


def test_an_undeclared_vintage_returns_the_sentinel_not_a_blank():
    assert as_of_for(SYNTHETIC_EXPORT_MAPPING) == AS_OF_UNKNOWN


# ── the synthetic mapping must EVOKE the degradations it claims ────────────
def test_the_synthetic_export_evokes_every_degradation():
    assert_evokes_the_degradations(SYNTHETIC_EXPORT_MAPPING)


def test_the_synthetic_etl_evokes_its_own_degradations():
    assert_evokes_the_degradations(SYNTHETIC_ETL_MAPPING)


def test_the_two_paths_can_disagree():
    """Or the source-disagreement acceptance query could never return a row — and a query that
    has never returned a row is a query nobody has tested."""
    assert_paths_can_disagree(SYNTHETIC_EXPORT_MAPPING, SYNTHETIC_ETL_MAPPING)


def test_what_a_source_cannot_say_is_readable_from_its_contract_alone():
    """Before a single row is ingested, you can tell what a source will be unable to tell you.
    That is the point of declaring lossiness as data instead of hiding it in transform code."""
    gaps = unmappable_report(SYNTHETIC_EXPORT_MAPPING)
    fields = {g["field"] for g in gaps}
    assert "Part.revision" in fields and "PartUsage.applicability" in fields
    assert all(g["reason"] for g in gaps), "an unfillable field with no reason is a shrug"


def test_the_two_paths_differ_in_what_they_can_say_not_only_when():
    """The ETL can populate revision; the export cannot. Degradation is about CAPABILITY as
    well as freshness — a model that only tracked staleness would miss it."""
    exp = {g["field"] for g in unmappable_report(SYNTHETIC_EXPORT_MAPPING)}
    etl = {g["field"] for g in unmappable_report(SYNTHETIC_ETL_MAPPING)}
    assert "Part.revision" in exp and "Part.revision" not in etl


# ── the template ships answerable, and answers nothing itself ──────────────
def test_the_template_has_no_source_side_content():
    """It must cross no boundary: the open side ships the QUESTIONS and the SHAPE; the filled
    declaration stays where the data lives."""
    t = (_ROOT / "setup" / "mappings" / "TEMPLATE.source-mapping.yaml").read_text(encoding="utf-8")
    for section in ("SOURCE INVENTORY", "as_of CONVENTION", "TRUTH COLUMNS vs LOCAL ANNOTATIONS"):
        assert section in t, f"the template lost its {section!r} question"
    assert 'strategy: "unknown"' in t, "the unknown sentinel must be the PRE-WIRED default"
    assert "cannot_populate" in t


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
