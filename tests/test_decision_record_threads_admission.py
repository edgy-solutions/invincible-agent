"""THE RECORD RECORDS THE DECISION — it does not re-make it.

THE DEFECT (found by the ceremony's own completion witness, 2026-08-10). The autonomous path
dispatched correctly at `monitored`, and then the decision record said `supervised`. Not a missing
field — a WRONG one, in the audit trail, on the exact question the trust arc exists to answer.

THE ROOT WAS TWO DERIVATIONS OF ONE DECISION, not a bad env var. `_emit_record` called
`rung_for(fingerprint, os.getenv("PIPELINE_VERSION", "unset"))` — a second derivation of a decision
`start_review` had already made, from an input the deploy never set. Two derivations disagree
whenever their inputs differ, and this codebase has paid for that three times now: at the starter
(reader's env vs producer's artifact), at the fingerprint (two mints, two env contracts), and here.

So the fix is not "read the right version". It is: **the admission happens once, and every
downstream reader is a RECORDER of that decision, never a second decider.**

Run:  uv run --frozen python -m pytest tests/test_decision_record_threads_admission.py -q
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_SENSOR = _ROOT / "src" / "iagent" / "defs" / "extraction_review_sensor.py"
# PACKAGE import, not file-path: `_emit_record` uses relative imports (`..decision_record_writer`),
# which raise under a file-path load and are swallowed by its own fail-soft except — so a file-path
# load would make every assertion below measure a record that was never written.
from src.iagent.defs import extraction_review_sensor as ers  # noqa: E402

_STARTER = _ROOT / "agent_fleet" / "restate_analyst" / "review_starter.py"

_REVIEW = {"doc_id": "IPCN25300X", "doc_type": "PCN", "doc_type_source": "extraction",
           "pipeline_version": "doc-tools@d5b4482",
           "review_items": [{"field_path": "header.mfr", "value": "onsemi"}]}


class _Log:
    def __init__(self): self.msgs = []
    def info(self, m): self.msgs.append(("info", m))
    def warning(self, m): self.msgs.append(("warning", m))
    def error(self, m): self.msgs.append(("error", m))


class _Ctx:
    def __init__(self): self.log = _Log()


def _emit(monkeypatch, admission):
    """Emit one record, capturing what the writer was handed."""
    captured = {}

    def _fake_writer(rec):
        captured.update(rec)
        return {"ok": True}

    import src.iagent.decision_record_writer as w  # noqa: PLC0415
    monkeypatch.setattr(w, "graph_writer", _fake_writer)
    ers._emit_record(_Ctx(), review=_REVIEW, key="k/review.json", request_key="rk",
                     outcome="STARTED", checks=[], ruleset_ref="rules@abc",
                     admission=admission)
    return captured


# ===========================================================================
# THE DISCRIMINATING PAIR — both rungs, record equals admission on each
# ===========================================================================
@pytest.mark.parametrize("rung,table_ref,admitted_by", [
    ("monitored", "trust@99464394e80c", "content"),
    ("supervised", "trust@eb3787d17399", "content"),
])
def test_the_record_carries_the_ADMISSIONS_rung_not_its_own(monkeypatch, rung, table_ref, admitted_by):
    """THE CLAIM, on BOTH rungs. One value would prove nothing: a recorder hardcoded to `monitored`
    passes the monitored case, and the old recompute passed the supervised case for years."""
    rec = _emit(monkeypatch, {"rung": rung, "trust_table_ref": table_ref,
                              "admitted_by": admitted_by,
                              "format_fingerprint": "onsemi/pcn/v1",
                              "pipeline_version": "doc-tools@d5b4482"})
    assert rec["trust_rung"] == rung, (
        f"the record says {rec['trust_rung']!r} while the admission decided {rung!r} — the audit "
        f"trail is answering the trust question differently from the router")
    assert rec["governing"]["trust_table_ref"] == table_ref
    assert rec["format_fingerprint"] == "onsemi/pcn/v1"
    assert rec["pipeline_version"] == "doc-tools@d5b4482", (
        "pipeline_version was ALSO taken from the unset env var — both fields lied, not just the rung")


def test_the_two_rungs_produce_DIFFERENT_records(monkeypatch):
    """The pair must actually differ. A recorder that ignores its input passes each case
    individually while producing identical rows — which is what the defect looked like."""
    a = _emit(monkeypatch, {"rung": "monitored", "trust_table_ref": "trust@A",
                            "format_fingerprint": "onsemi/pcn/v1", "pipeline_version": "v1"})
    b = _emit(monkeypatch, {"rung": "supervised", "trust_table_ref": "trust@B",
                            "format_fingerprint": "onsemi/pcn/v1", "pipeline_version": "v1"})
    assert a["trust_rung"] != b["trust_rung"]
    assert a["governing"]["trust_table_ref"] != b["governing"]["trust_table_ref"]


# ===========================================================================
# NO ADMISSION == NO POSTURE — never an invented one
# ===========================================================================
def test_a_notice_that_was_never_admitted_records_NOT_ADMITTED(monkeypatch):
    """The NO_PARTS_EXTRACTED / NO_AFFECTED_PARTS branches never call start_review, so there IS no
    admission decision. Recording a rung there would fabricate a posture for a notice nobody
    admitted — the same lie one field over. `not-admitted` is the honest value."""
    rec = _emit(monkeypatch, None)
    assert rec["trust_rung"] == "not-admitted", (
        f"a never-admitted notice recorded {rec['trust_rung']!r} — a posture was invented")
    # The version still comes from the ARTIFACT's own stamp — a producer fact, not a decision, and
    # the record schema requires it because trust is keyed on it. What must NOT appear is a rung.
    assert rec["pipeline_version"] == "doc-tools@d5b4482", (
        "a never-admitted notice must still record the EXTRACTOR that produced it — that is an "
        "artifact fact, unlike the rung, which is a decision nobody made here")


# ===========================================================================
# THE RECOMPUTATION PATH IS GONE — asserted structurally
# ===========================================================================
def test_the_recorder_no_longer_asks_the_TABLE_anything():
    """The root cause, forbidden. If the recorder can consult the trust table it can disagree with
    the router again, and the disagreement will be plausible and silent."""
    src = _SENSOR.read_text(encoding="utf-8")
    start = src.index("def _emit_record(")
    raw = src[start:src.index("\ndef ", start)]
    # CODE ONLY. The first version scanned the whole block and matched `rung_for(` inside the
    # comment that EXPLAINS the defect — a guard tripping on its own documentation, which is the
    # prose-vs-declaration trap this suite has paid for before.
    body = "\n".join(ln for ln in raw.splitlines() if not ln.strip().startswith("#"))
    assert "rung_for(" not in body, (
        "the record is re-deriving the rung — that is the defect, not a style issue")
    assert "load_trust_table" not in body, (
        "the recorder can reach the trust table again — if it can read it, it can disagree with "
        "the router, and the disagreement will be plausible and silent")


def test_the_lying_env_global_is_RETIRED():
    src = _SENSOR.read_text(encoding="utf-8")
    live = [ln for ln in src.splitlines()
            if "_PIPELINE_VERSION" in ln and not ln.strip().startswith("#")]
    assert not live, f"_PIPELINE_VERSION still has live consumers: {live}"


def test_the_STARTER_returns_the_admission_it_decided():
    """The other half of the thread. The recorder can only record what the decider hands it."""
    src = _STARTER.read_text(encoding="utf-8")
    assert '"admission": {' in src, "start_review does not return its admission decision"
    for field in ('"rung": rung', '"trust_table_ref": trust_ref', '"admitted_by": admitted_by',
                  '"format_fingerprint": fmt_fp', '"pipeline_version": pipe_v'):
        assert field in src, f"the returned admission omits {field}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
