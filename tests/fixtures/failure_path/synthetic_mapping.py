"""A SYNTHETIC source mapping — fictional columns, every degradation the template permits.

The real mappings live where the data lives and never enter this repo (the restricted-boundary
rule at the data plane: the open side ships the vocabulary, the questions and the writer; the
filled declaration stays internal). So the writer cannot be sealed against a real source — and
it should not be. It is sealed against a source that is deliberately AS LOSSY AS THE TEMPLATE
ALLOWS, which is stronger: a real mapping will be some subset of these degradations, so a
writer proven here meets nothing new when the real one arrives.

Every name below is invented. Nothing here corresponds to any real sheet, column or part.

WHAT IT EXERCISES, and why each matters:
  * `cannot_populate` entries          — the enumerated absence, so a gap is queryable rather
                                         than a silence somebody has to notice
  * `as_of: unknown`                   — the sentinel; an undateable claim is not fresh
  * truth-columns vs local annotations — a note must never become a fact
  * a DISAGREEING PAIR across paths    — so the source-disagreement acceptance query has
                                         something to find. A query that has never returned a
                                         row is a query nobody has tested.
"""
from __future__ import annotations

import copy

# Two paths onto the same fictional truth, so disagreement is expressible.
SYNTHETIC_EXPORT_MAPPING = {
    "odcs_version": "1.0",
    "contract_id": "bom-synthetic-export-v1",
    "source": {
        "label": "synthetic-export",
        "authoritative_source": "windchill",
        "obtained_via": "manual-export",
        "standing": "commissioning",
    },
    "as_of": {"strategy": "unknown", "detail": "fictional export with no recorded date",
              "ingest_time_is_truth_time": False},
    "columns": {
        "pdm_derived": [
            {"source_column": "COL_A", "canonical_field": "Part.partNumber"},
            {"source_column": "COL_B", "canonical_field": "PartUsage.parent"},
            {"source_column": "COL_C", "canonical_field": "PartUsage.child"},
            {"source_column": "COL_D", "canonical_field": "PartUsage.quantity"},
        ],
        "local_annotation": [
            {"source_column": "NOTE_1", "disposition": "drop"},
            {"source_column": "NOTE_2", "disposition": "capture-separately"},
        ],
    },
    "cannot_populate": [
        {"field": "Part.revision", "reason": "flattened at export; not recoverable"},
        {"field": "PartUsage.applicability", "reason": "the export drops effectivity entirely"},
        {"field": "PartUsage.referenceDesignator", "reason": "not present in this export"},
    ],
    "shape_summary": "4 columns mapped, 2 local-annotation columns declared, no export date",
}

SYNTHETIC_ETL_MAPPING = {
    **copy.deepcopy(SYNTHETIC_EXPORT_MAPPING),
    "contract_id": "bom-synthetic-etl-v1",
    "source": {"label": "synthetic-etl", "authoritative_source": "windchill",
               "obtained_via": "etl", "standing": "monitored"},
    "as_of": {"strategy": "column", "detail": "sync watermark",
              "ingest_time_is_truth_time": False},
    # The ETL path CAN populate revision — which is the point: the two paths differ in what
    # they can say, not only in when they last spoke.
    "cannot_populate": [
        {"field": "PartUsage.referenceDesignator", "reason": "not carried by this pipeline"},
    ],
}


def assert_evokes_the_degradations(mapping: dict) -> None:
    """The fixture must EVOKE what it claims, not merely resemble a mapping.

    Without this, a future edit that tidies the fixture into something clean would leave the
    writer's tests green while exercising none of the lossiness they exist to cover — the
    green-over-nothing shape, in the corpus built to prevent it.
    """
    assert mapping.get("cannot_populate"), (
        "the fixture declares no unfillable fields — then it exercises no degradation, and a "
        "source claiming to populate everything is the one to distrust")
    cols = mapping.get("columns") or {}
    assert cols.get("pdm_derived"), "no truth columns"
    assert cols.get("local_annotation"), (
        "no local-annotation columns — the truth-vs-annotation split is the rule that keeps a "
        "note from becoming a fact, and an unexercised rule is an unproven one")
    assert (mapping.get("source") or {}).get("authoritative_source") == "windchill", (
        "every path must name the SAME authoritative source — this is lineage, not identity")


def assert_paths_can_disagree(a: dict, b: dict) -> None:
    """Two paths onto one truth must be distinguishable, or the source-disagreement acceptance
    query can never return a row and nobody would know it was broken."""
    assert (a["source"]["obtained_via"] != b["source"]["obtained_via"]), (
        "both fixtures declare the same path — disagreement would be unattributable")
    assert {e["field"] for e in a["cannot_populate"]} != {e["field"] for e in b["cannot_populate"]}, (
        "the two paths can say exactly the same things — then they model one path twice, and "
        "the degradation comparison has nothing to compare")
