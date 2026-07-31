"""REFUSAL ROUTING — a refused notice goes to whoever owns the ANSWER.

THE LIVE FAILURE (2026-07-29). Three notices hit `REVIEW_STATE_UNSOURCED` and each one
ceased to exist for everyone whose job is processing notices. The refusal was real and
honest; the AUDIENCE was wrong. Every refusal — "this document is unreadable" and "the
ruleset isn't deployed" alike — surfaced as one thing: a failed Dagster run, phrased in
pipeline vocabulary, in a tool the sustainment reviewer does not open. That is the
invisible-dead-notice failure the sensor design explicitly rejected polling to avoid,
reintroduced through the ERROR path.

The split this file seals:
  * PER-NOTICE CONTENT  -> triage task to the owning audience; the run COMPLETES
  * SYSTEMIC/DEPLOYMENT -> the run FAILS, once, loudly, for ops

Three properties are load-bearing and each has a test that fails without it:

  1. THE STATUS MUST BE FOUND WHERE THE HTTP LAYER PUT IT. A 200 carries `status` at the
     top level; a refusal is re-raised by the BFF as HTTPException(detail=<engine body>)
     and FastAPI serializes it as {"detail": {...}}. Reading only the top level sees None
     for EVERY refusal — harmless while all refusals shared one fate, silently wrong the
     moment routing depends on it. Everything would route SYSTEMIC and the fix would be a
     no-op that looks installed.
  2. ROUTING FAILURE MUST RAISE. The triage POST is the only thing between a refused
     notice and invisibility. If a 403/422/timeout there were swallowed, the notice would
     vanish behind a GREEN run — strictly worse than the bug being fixed.
  3. TRIAGE IDENTITY COMES FROM THE ARTIFACT, NOT `doc_id`. doc_id is LLM-extracted and
     degrades to a shared fallback exactly when extraction is failing ("inbound" for every
     PDF in one inbox, live 2026-07-30). Keying triage on it collapses N dead notices into
     one task — the same silent loss, inside the fix.

Run:  uv run --frozen python -m pytest tests/test_refusal_routing.py -q
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
_spec = importlib.util.spec_from_file_location("ers_refusal", _SENSOR)
ers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ers)  # type: ignore[union-attr]

from dagster import Failure  # noqa: E402


def _bff_refusal(status: str) -> dict:
    """How a refusal ACTUALLY looks on the wire: the BFF re-raises the engine body as
    HTTPException(detail=...), and FastAPI wraps it in {"detail": ...}. Tests that
    hand-build a flat {"status": ...} body would pass while production mis-routed."""
    return {"detail": {"status": status, "notice_id": "PCN-2683"}}


# ── PROPERTY 1: the split itself, over the real wire shape ──────────────────
@pytest.mark.parametrize("code", ["REVIEW_STATE_UNSOURCED", "NO_PARTS_EXTRACTED", "NO_AFFECTED_PARTS"])
def test_per_notice_content_refusals_route_to_the_reviewer(code):
    """These are statements about THIS document. Only the reviewer can answer them."""
    outcome, _ = ers.classify_start_review(422, _bff_refusal(code))
    assert outcome == "refused_content", (
        f"{code} is a per-notice content problem — routing it systemic sends it back to "
        f"the one persona who cannot act on it, which is the bug this file seals"
    )


@pytest.mark.parametrize("code", ["RULES_NOT_FOUND", "RULESET_INVALID"])
def test_deployment_refusals_stay_with_ops(code):
    """A missing/corrupt ruleset affects EVERY notice. Fifty identical triage tasks in
    reviewers' queues is worse than one loud Dagster failure."""
    outcome, _ = ers.classify_start_review(422, _bff_refusal(code))
    assert outcome == "refused_systemic"


def test_missing_capability_grant_is_systemic_not_content():
    """403 NOT_ENTITLED_TO_INITIATE is a config gap: every notice fails identically. It
    must not be dressed up as N per-document problems."""
    outcome, detail = ers.classify_start_review(403, _bff_refusal("NOT_ENTITLED_TO_INITIATE"))
    assert outcome == "refused_systemic"
    assert "capability_grants.yaml" in detail, "the failure must name the fix"


def test_transport_and_unknown_failures_are_systemic():
    assert ers.classify_start_review(502, {"raw": "bad gateway"})[0] == "refused_systemic"
    assert ers.classify_start_review(500, {})[0] == "refused_systemic"


def test_unrecognized_status_defaults_to_systemic_not_content():
    """DEFAULT DIRECTION. An unknown refusal routed to a human asserts 'look at this
    document', which is a false statement when the truth is 'the pipeline is broken'.
    Unknown means unknown: it goes to ops."""
    outcome, _ = ers.classify_start_review(422, _bff_refusal("SOME_FUTURE_CODE"))
    assert outcome == "refused_systemic"


def test_success_paths_are_untouched_by_the_split():
    assert ers.classify_start_review(200, {"status": "STARTED", "workflow_id": "w1"})[0] == "started"
    assert ers.classify_start_review(200, {"status": "NO_RESIDUE"})[0] == "no_residue_skip"


# ── PROPERTY 1 (the trap, isolated): status must survive FastAPI's wrapper ──
def test_status_is_read_through_the_fastapi_detail_wrapper():
    """THE SILENT-NO-OP TRAP. `_status_of` must find the engine's status whether it is at
    the top level (200) or nested under `detail` (every refusal). Read the top level only
    and all refusals classify as systemic — the routing fix would ship, pass a smoke test,
    and change nothing for the reviewer."""
    assert ers._status_of({"status": "STARTED"}) == "STARTED"
    assert ers._status_of(_bff_refusal("REVIEW_STATE_UNSOURCED")) == "REVIEW_STATE_UNSOURCED"
    assert ers._status_of({}) is None
    assert ers._status_of({"detail": "plain string detail"}) is None
    assert ers._status_of(None) is None


# ── PROPERTY 3: triage identity is content-addressed, never doc_id ──────────
def test_two_notices_that_derived_the_same_doc_id_get_distinct_triage_tasks():
    """THE "inbound" INCIDENT, re-run against the triage path. Two different documents
    whose header pass failed both derive doc_id 'inbound'. Keyed on doc_id they would
    collapse into ONE task and one of the two dead notices would stay dead — the exact
    loss this routing exists to end, reproduced inside the cure."""
    a = ers.build_triage_payload(
        source_key="sustainment/inbound/generated/DiodesA_pdf/review.json",
        notice_id="inbound", reason_code="REVIEW_STATE_UNSOURCED", detail="x")
    b = ers.build_triage_payload(
        source_key="sustainment/inbound/generated/QorvoB_pdf/review.json",
        notice_id="inbound", reason_code="REVIEW_STATE_UNSOURCED", detail="x")
    assert a["task_id"] != b["task_id"]
    assert a["subject_ref"] != b["subject_ref"]


def test_the_same_artifact_refiles_the_same_task_id():
    """Idempotency: a re-drive of the same artifact must not mint a second task."""
    kw = dict(source_key="sustainment/a/generated/review.json", reason_code="NO_PARTS_EXTRACTED",
              detail="d")
    assert (ers.build_triage_payload(notice_id="PCN-1", **kw)["task_id"]
            == ers.build_triage_payload(notice_id="PCN-1", **kw)["task_id"])


def test_triage_task_id_ignores_the_extracted_notice_id():
    """Identity comes from the ARTIFACT. Two reads of one artifact that disagree about
    doc_id (a re-extraction with a better header pass) are still ONE notice."""
    kw = dict(source_key="sustainment/a/generated/review.json", reason_code="X", detail="d")
    assert (ers.build_triage_payload(notice_id="inbound", **kw)["task_id"]
            == ers.build_triage_payload(notice_id="PCN-2683", **kw)["task_id"])


# ── the reviewer-facing content ────────────────────────────────────────────
def test_summary_speaks_to_a_reviewer_not_an_engine():
    """The queue row is ALL they get. It must say what happened to their document, in
    their vocabulary, and point at the artifact."""
    t = ers.build_triage_payload(
        source_key="sustainment/inbound/generated/Diodes_pdf/review.json",
        notice_id="PCN-2683", reason_code="NO_PARTS_EXTRACTED", detail="raw engine detail",
        warnings=["PARTS MAY BE MISSING: 2/5 table crops failed"])
    assert "PCN-2683" in t["title"] and "could not be prepared" in t["title"]
    assert "No parts could be read" in t["summary"], "the status constant is not an explanation"
    assert "2/5 table crops failed" in t["summary"], (
        "extraction warnings are WHY it failed — the one thing that makes the refusal actionable"
    )
    assert "sustainment/inbound/generated/Diodes_pdf/review.json" in t["summary"]


def test_notice_id_still_travels_for_display():
    t = ers.build_triage_payload(source_key="s/a/generated/review.json", notice_id="PCN-2683",
                                reason_code="X", detail="d")
    assert t["payload"]["notice_id"] == "PCN-2683"


def test_missing_notice_id_falls_back_to_something_a_human_can_recognize():
    """When the header pass died entirely there IS no notice id — the row must still name
    the document, not print 'None'."""
    t = ers.build_triage_payload(
        source_key="sustainment/inbound/generated/Diodes_PCN_2683_pdf/review.json",
        notice_id=None, reason_code="NO_PARTS_EXTRACTED", detail="d")
    assert "None" not in t["title"]
    assert "Diodes_PCN_2683_pdf" in t["title"]


def test_triage_payload_is_clearance_safe():
    """Identifiers and a reason — never notice CONTENT. The row is visible to every
    authorized actor in the audience."""
    t = ers.build_triage_payload(source_key="s/a/generated/review.json", notice_id="PCN-1",
                                 reason_code="X", detail="d")
    assert set(t["payload"]) <= {"notice_id", "source_key", "detail", "warnings"}


# ── PROPERTY 2: routing failure must RAISE, never swallow ──────────────────
class _Resp:
    def __init__(self, status_code, body):
        self.status_code, self._body, self.text = status_code, body, str(body)

    def json(self):
        return self._body


def _patch_post(monkeypatch, fn):
    import httpx
    monkeypatch.setattr(httpx, "post", fn)


@pytest.mark.parametrize("code,body", [
    (403, {"detail": {"error": "not_entitled_to_file_triage"}}),
    (422, {"detail": {"error": "no_entitled_recipients"}}),
    (503, {"detail": {"error": "hitl_unconfigured"}}),
    (500, {"raw": "boom"}),
])
def test_triage_routing_failure_fails_the_run(monkeypatch, code, body):
    """THE ANTI-REGRESSION. Every reason the triage POST can fail is a reason the notice
    would otherwise disappear behind a GREEN run — strictly worse than the red run we are
    replacing. So it raises, and the operator sees it."""
    _patch_post(monkeypatch, lambda *a, **k: _Resp(code, body))
    with pytest.raises(Failure) as exc:
        ers.file_triage_task({"subject_ref": "s/a/generated/review.json"},
                             bff_url="http://bff", token="t", source="s/a/generated/review.json")
    assert "not be routed" in str(exc.value.description)
    assert "s/a/generated/review.json" in str(exc.value.description), (
        "the failure must name the ARTIFACT — 'refused for inbound' N times is unactionable"
    )


def test_triage_routing_unreachable_fails_the_run(monkeypatch):
    """A transport failure is the quietest way to lose a notice; it must be the loudest."""
    def _boom(*a, **k):
        raise RuntimeError("connection refused")
    _patch_post(monkeypatch, _boom)
    with pytest.raises(Failure) as exc:
        ers.file_triage_task({"subject_ref": "k"}, bff_url="http://bff", token="t")
    assert "UNREACHABLE" in str(exc.value.description)


def test_successful_routing_returns_the_filing_receipt(monkeypatch):
    _patch_post(monkeypatch, lambda *a, **k: _Resp(200, {"task_id": "triage-abc", "status": "FILED",
                                                        "recipients": 2}))
    out = ers.file_triage_task({"subject_ref": "k"}, bff_url="http://bff", token="t")
    assert out["status"] == "FILED" and out["recipients"] == 2


# ── submit_review's half of the contract ───────────────────────────────────
def test_submit_review_raises_only_for_systemic(monkeypatch):
    """A systemic refusal still fails the run — the ops path is unchanged."""
    _patch_post(monkeypatch, lambda *a, **k: _Resp(422, _bff_refusal("RULES_NOT_FOUND")))
    with pytest.raises(Failure):
        ers.submit_review({"notice_id": "n"}, bff_url="http://bff", token="t", source="k")


def test_submit_review_returns_content_refusals_for_the_caller_to_route(monkeypatch):
    """A content refusal must NOT raise — raising is what sent it to the wrong audience."""
    _patch_post(monkeypatch, lambda *a, **k: _Resp(422, _bff_refusal("REVIEW_STATE_UNSOURCED")))
    outcome, detail, body = ers.submit_review({"notice_id": "n"}, bff_url="http://bff",
                                              token="t", source="k")
    assert outcome == "refused_content"
    assert "REVIEW_STATE_UNSOURCED" in detail
    assert ers._status_of(body) == "REVIEW_STATE_UNSOURCED", (
        "the caller builds the triage reason_code from this body — it must survive the return"
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
