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


# ── §6: qualification status is DATA, validated loudly ─────────────────────
from src.iagent.product_writer import (  # noqa: E402
    load_qualification_statuses, validate_qualification_status,
)


def test_the_status_menu_comes_from_the_vocabulary_file_not_an_enum():
    """THE §6 RULING made mechanical. Statuses are POLICY VOCABULARY, so the writer validates
    against ratifiable data — which is why a wrong seed costs nothing: a state nobody uses sits
    inert, a state that turns out to be needed is one TTL entry through the normal path. If
    this ever becomes a Python set, the work-side update stops being a data edit and the whole
    reason the seed could be decided without the engineers is gone."""
    assert load_qualification_statuses() == {"proposed", "qualifying", "approved", "ltb_only",
                                             "withdrawn"}


def test_a_status_added_to_the_FILE_is_accepted_with_no_code_change(tmp_path, monkeypatch):
    """THE ACTUAL PROPERTY, and my first version of this test did not test it — it asserted the
    vocabulary FILENAME appeared in the source, which stayed true when I mutated the menu into a
    hardcoded Python set. The mutation passed and the seal was decorative.

    This is the point-of-consumption rule again: assert what the field DOES, not that it is
    mentioned. Here the doing is "a new status ratified in the FILE works, with no code touched"
    — which is the entire reason a wrong seed costs nothing."""
    vocab = tmp_path / "v.ttl"
    vocab.write_text(
        "qs:approved a qs:QualificationStatus ." + chr(10) +
        "qs:program_scoped a qs:QualificationStatus ." + chr(10),
        encoding="utf-8")
    # Exercise the DEFAULT path — not `allowed=`. My first two attempts at this test both
    # passed under a mutation that hardcoded the menu, because they either checked that the
    # filename was mentioned or passed the menu in explicitly. Neither touched the branch the
    # mutation changed. Point-of-consumption, third time: drive the code path that would break.
    import src.iagent.product_writer as _pw
    monkeypatch.setattr(_pw, "_QUALIFICATION_VOCAB_FILE", str(vocab))
    _pw.validate_qualification_status("program_scoped")      # default path, no `allowed`
    menu = load_qualification_statuses(str(vocab))
    assert menu == {"approved", "program_scoped"}, (
        "the menu did not come from the file — a work-side addition would need a code change, "
        "which is exactly what the config-native ruling exists to prevent"
    )
    validate_qualification_status("program_scoped", allowed=menu)


def test_an_unratified_status_is_refused_loudly():
    """A typo must not mint a phantom state that then accumulates rows nobody can explain."""
    with pytest.raises(CanonicalAssertionInvalid) as exc:
        validate_qualification_status("aproved", allowed={"approved"})
    assert "ratified vocabulary" in str(exc.value)


def test_every_seeded_status_is_accepted():
    for s in load_qualification_statuses():
        validate_qualification_status(s)


def test_the_status_is_validated_on_the_assertion_path():
    """Not just as a helper — the writer itself must refuse it, or the validation is optional."""
    bad = {"kind": "ApprovedSourceRelationship",
           "fields": {"forPart": "P", "qualificationStatus": "invented"},
           "provenance": _prov()}
    with pytest.raises(CanonicalAssertionInvalid):
        validate_canonical(bad)


def test_dispatchQualifications_own_output_state_exists():
    """`proposed` must exist because it is what the workflow WRITES: without it the disposition
    pipeline has no first-class value to record its result as — the exact gap the house bridge
    was created to close."""
    assert "proposed" in load_qualification_statuses()


def test_the_vocabulary_has_an_exit_that_is_not_deletion():
    """`withdrawn` exists so retiring a source does not mean removing rows. This graph's
    doctrine is that evidence does not delete, and a discontinued source's history staying
    queryable is what an auditor of an AML actually needs."""
    assert "withdrawn" in load_qualification_statuses()


def test_transitions_are_advisory_documentation_not_an_enforced_machine():
    """A state machine built before its first violation is a guess with a runtime cost. The
    graph records what happened; the vocabulary constrains what can be SAID."""
    ttl = (_ROOT / "setup" / "ontologies" / "qualification_status_vocabulary.ttl").read_text(encoding="utf-8")
    assert "expectedTransitions" in ttl and "Advisory only" in ttl
    src = (_ROOT / "src" / "iagent" / "product_writer.py").read_text(encoding="utf-8")
    assert "expectedTransitions" not in src, "transitions leaked into enforcement"
