"""DECISION RECORDS — bare verdicts are not evidence.

ADR-0034 Phase 1. The record exists to answer "why was this notice NOT reviewed?" from an
ARTIFACT rather than by re-running the pipeline that decided it. That only works if the record
carries what each check LOOKED AT, so the load-bearing seal here is the one the build directive
flagged as most likely to be quietly weakened:

    a check that records a verdict with no inputs must be REFUSED

Because a schema full of booleans validates, looks complete, and silently makes every future
promotion decision rest on the pipeline's self-report.

The two live false positives from 2026-07-31 are the standing argument. "~89 parts but 2
extracted" was the count parser reading a package type (SOT-89); "~2024 parts but 1 extracted"
was a year. Recorded as `{"verdict": "mismatch"}` both would have entered the corpus as
evidence the EXTRACTION was unreliable, and a vendor would have been held back on the strength
of a regex bug. Recorded with inputs, a reader sees the 89 came from "SOT-89 package parts".

Run:  uv run --frozen --extra agent-fleet python -m pytest tests/test_decision_record.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.iagent.decision_record import (  # noqa: E402
    ADMITTED_BY,
    DecisionRecordInvalid,
    build_decision_record,
    canonical_json,
    emit,
    make_check,
    record_id_for,
    validate_decision_record,
)

_RK = "etag-aaa-sustainment/inbound/generated/Qorvo_PCN_23_0171_pdf/review.json"


def _rec(**over):
    kw = dict(
        request_key=_RK,
        source_key="sustainment/inbound/generated/Qorvo_PCN_23_0171_pdf/review.json",
        notice_id="PCN-23-0171",
        pipeline_version="doc-tools@446fbae",
        format_fingerprint="qorvo/pcn/v1",
        outcome="STARTED",
        admitted_by="content",
        checks=[make_check("summary_part_count", verdict="ok",
                           inputs={"stated": None, "extracted": 2}, threshold={"tolerance": 0})],
        governing={"ruleset_ref": "rules@2915ddb229e4", "trust_table_ref": "trust@abc123"},
        trust_rung="supervised",
    )
    kw.update(over)
    return build_decision_record(**kw)


# ── THE LOAD-BEARING SEAL: inputs, not bare verdicts ───────────────────────
def test_a_check_with_no_inputs_is_refused():
    """The clause most likely to be weakened. `{"verdict": "pass"}` is re-derivable only by
    re-running the pipeline that produced it — which IS the audit gap."""
    with pytest.raises(DecisionRecordInvalid) as exc:
        make_check("summary_part_count", verdict="mismatch", inputs={})
    assert "bare verdict" in str(exc.value)


def test_a_check_carries_what_it_compared():
    """The real false positive, recorded properly: a reader can see the 89 came from a
    PACKAGE TYPE, not from a parts table. Without inputs this record would have entered the
    corpus as evidence the extraction was unreliable — and held a vendor back on a regex bug."""
    c = make_check(
        "summary_part_count",
        verdict="mismatch",
        inputs={"stated": 89, "extracted": 2, "source_phrase": "SOT-89 package parts"},
        threshold={"tolerance": 0},
    )
    assert c["inputs"]["stated"] == 89
    assert "SOT-89" in c["inputs"]["source_phrase"]
    assert c["threshold"] == {"tolerance": 0}


def test_a_record_cannot_smuggle_a_bare_check_past_the_builder():
    """A hand-built dict that skips make_check() must still be refused — the guard belongs to
    the RECORD, not to one convenience constructor."""
    with pytest.raises(DecisionRecordInvalid):
        _rec(checks=[{"name": "x", "verdict": "pass"}])


def test_validation_runs_again_at_emit():
    """A future path that bypasses the builder must not be able to write malformed evidence."""
    bad = _rec()
    bad["checks"] = [{"name": "x", "verdict": "pass"}]
    with pytest.raises(DecisionRecordInvalid):
        emit(bad, writer=lambda r: r)


# ── emission is LOUD, never silently dropped ───────────────────────────────
def test_emit_raises_rather_than_dropping_bad_evidence():
    """Evidence that vanishes when malformed is worse than no evidence: the corpus then looks
    complete while missing exactly the cases that went strangely — which are the cases
    promotion most needs to see."""
    written = []
    bad = _rec()
    del bad["governing"]
    with pytest.raises(DecisionRecordInvalid):
        emit(bad, writer=written.append)
    assert written == [], "a malformed record reached the writer"


def test_emit_passes_a_valid_record_to_the_writer():
    written = []
    rec = _rec()
    emit(rec, writer=written.append)
    assert written and written[0]["record_id"] == rec["record_id"]


# ── identity is the ARTIFACT's — fourth consumer of one key ────────────────
def test_record_id_derives_from_the_artifact_not_the_notice():
    """The corpus must join to the sensor run, the triage task and the invocation that share
    this identity. Deriving a fifth key here is how one artifact becomes 'the same work' to
    one mechanism and 'new work' to another."""
    a = _rec(notice_id="PCN-23-0171")
    b = _rec(notice_id="COMPLETELY-DIFFERENT")
    assert a["record_id"] == b["record_id"], "record identity moved with a DISPLAY field"
    assert a["record_id"] == record_id_for(_RK)


def test_two_documents_sharing_a_doc_id_get_distinct_records():
    """The "inbound" incident at its fourth site."""
    a = _rec(notice_id="inbound", request_key="etag-aaa-s/inbound/generated/A_pdf/review.json")
    b = _rec(notice_id="inbound", request_key="etag-bbb-s/inbound/generated/B_pdf/review.json")
    assert a["record_id"] != b["record_id"]


def test_a_reextraction_is_a_different_record():
    """New bytes are new evidence — the record must not silently overwrite the prior one."""
    a = _rec(request_key="etag-aaa-s/a/generated/review.json")
    b = _rec(request_key="etag-bbb-s/a/generated/review.json")
    assert a["record_id"] != b["record_id"]


# ── governing policy state is mandatory ────────────────────────────────────
@pytest.mark.parametrize("governing", [
    {},
    {"ruleset_ref": "rules@abc"},                 # missing trust table ref
    {"trust_table_ref": "trust@abc"},             # missing ruleset ref
])
def test_a_record_must_say_what_policy_state_it_was_decided_under(governing):
    """Without it, a corpus spanning a ruleset or trust-table edit silently mixes two regimes
    and every trend computed over it is meaningless."""
    with pytest.raises(DecisionRecordInvalid):
        _rec(governing=governing)


def test_pipeline_version_is_mandatory():
    """Trust is keyed on vendor-format x PIPELINE-VERSION. A record that cannot be attributed
    to the thing that produced it cannot support a promotion, and the Qorvo/Diodes/onsemi
    incidents are why the version is in the key at all."""
    with pytest.raises(DecisionRecordInvalid):
        _rec(pipeline_version="")


# ── admission outcome ──────────────────────────────────────────────────────
@pytest.mark.parametrize("how", ADMITTED_BY)
def test_every_admission_route_is_expressible(how):
    assert _rec(admitted_by=how)["admitted_by"] == how


def test_an_unknown_admission_route_is_refused():
    with pytest.raises(DecisionRecordInvalid):
        _rec(admitted_by="because")


def test_escalation_is_expressible_before_workflow_2_exists():
    """ADR-0034 §7: autonomy is always one bad check away from supervision. The vocabulary has
    to exist BEFORE the autonomous path does, or the first escalation has nowhere to be
    recorded and the road back is improvised at the worst moment."""
    assert _rec(admitted_by="escalation")["trust_rung"] == "supervised"


# ── the record is a stable, comparable artifact ────────────────────────────
def test_canonical_json_is_order_independent():
    a = canonical_json(_rec())
    b = canonical_json(_rec())
    assert a == b


def test_a_valid_record_validates():
    validate_decision_record(_rec())


def test_warnings_ride_along():
    r = _rec(warnings=["PARTS MAY BE MISSING: 2/5 table crops failed"])
    assert r["warnings"] == ["PARTS MAY BE MISSING: 2/5 table crops failed"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
