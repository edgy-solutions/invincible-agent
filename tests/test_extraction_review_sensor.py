"""Offline contract test for the extraction->review sensor (the canonical trigger).

Proves the load-bearing logic WITHOUT the cluster:
  1. build_start_review_payload sources impacted_parts (with per-part needs_review) +
     doc_needs_review ONLY from review.json — the REVIEW_STATE_UNSOURCED tripwire's
     substrate-gap invariant holds by the sensor's source choice.
  2. The tripwire is NOT papered over: a doc-level-needs-review notice with no per-part
     flag flows through as exactly the shape that ARMS the tripwire at engine-a.
  3. classify_start_review maps every outcome correctly; submit_review RAISES on a
     refusal (-> failed Dagster run) and returns on started/no-residue.

The live drop-PDF->review-materializes proof waits for the cluster; this pins the contract.

Run:  uv run --frozen python tests/test_extraction_review_sensor.py
      (needs the iagent image deps: dagster + boto3 + httpx — test-env == image-env)
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_MOD = _REPO / "src" / "iagent" / "defs" / "extraction_review_sensor.py"


def _load():
    spec = importlib.util.spec_from_file_location("extraction_review_sensor", _MOD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


ers = _load()


# A representative doc-tools review.json: 2 parts, part[0] flagged for review, doc-level
# needs_review True; plus a header row + a malformed row the builder must ignore.
def _review_json(*, doc_needs_review: bool, part0_needs: bool, part1_needs: bool) -> dict:
    return {
        "doc_id": "IPCN25300X",
        "needs_review": doc_needs_review,
        "pages": [],
        "review_items": [
            {"field_path": "header.notice_number", "value": "IPCN25300X", "needs_review": False},
            {"field_path": "parts[0].affected_mpn", "value": "MPN-A", "needs_review": part0_needs},
            {"field_path": "parts[0].replacement_mpn", "value": "MPN-A-R", "needs_review": False},
            {"field_path": "parts[1].affected_mpn", "value": "MPN-B", "needs_review": part1_needs},
            {"field_path": "parts[1].replacement_mpn", "value": "MPN-B-R", "needs_review": False},
            {"field_path": "garbage_no_index", "value": "x", "needs_review": True},
        ],
    }


def test_payload_sources_parts_and_per_part_flag_from_review_json() -> None:
    payload = ers.build_start_review_payload(
        _review_json(doc_needs_review=True, part0_needs=True, part1_needs=False)
    )
    assert payload["notice_id"] == "IPCN25300X"
    assert payload["doc_type"] == "PCN"
    assert payload["domain"] == "SUSTAINMENT"
    assert payload["doc_needs_review"] is True
    # parts assembled ONLY from review_items; header + malformed rows ignored; order by index.
    assert payload["impacted_parts"] == [
        {"affected_mpn": "MPN-A", "replacement_mpn": "MPN-A-R", "needs_review": True},
        {"affected_mpn": "MPN-B", "replacement_mpn": "MPN-B-R", "needs_review": False},
    ], payload["impacted_parts"]


def test_tripwire_shape_is_preserved_not_papered_over() -> None:
    """Doc says needs_review but NO part carries the flag -> the payload must carry
    doc_needs_review=True with all parts needs_review=False. THAT is precisely the shape
    engine-a's guard `review_state_is_unsourced` fires on. The sensor forwards it honestly
    (it does not invent a per-part flag to make the review start), so the tripwire still bites."""
    payload = ers.build_start_review_payload(
        _review_json(doc_needs_review=True, part0_needs=False, part1_needs=False)
    )
    assert payload["doc_needs_review"] is True
    assert all(p["needs_review"] is False for p in payload["impacted_parts"])


def test_no_parts_yields_empty_impacted_parts() -> None:
    payload = ers.build_start_review_payload({"doc_id": "N1", "needs_review": False, "review_items": []})
    assert payload["notice_id"] == "N1"
    assert payload["impacted_parts"] == []


def test_classify_covers_every_outcome() -> None:
    assert ers.classify_start_review(200, {"status": "STARTED", "workflow_id": "wf1", "count": 2})[0] == "started"
    assert ers.classify_start_review(200, {"status": "NO_RESIDUE", "counts": {}})[0] == "no_residue_skip"
    # NOT_ENTITLED_TO_INITIATE comes back 403 (the auto-starter lacks can_invoke) -> surface as a failure.
    assert ers.classify_start_review(403, {"status": "NOT_ENTITLED_TO_INITIATE"})[0] == "refused"
    # 422 = the tripwire / rules refusals.
    assert ers.classify_start_review(422, {"status": "REVIEW_STATE_UNSOURCED"})[0] == "refused"
    assert ers.classify_start_review(422, {"status": "RULES_NOT_FOUND"})[0] == "refused"
    # 502 unreachable / any non-200 -> refused.
    assert ers.classify_start_review(502, {"error": "review_start_unreachable"})[0] == "refused"


class _FakeResp:
    def __init__(self, status_code: int, body: dict):
        self.status_code = status_code
        self._body = body
        self.text = str(body)

    def json(self):
        return self._body


def test_submit_review_raises_on_refusal_returns_on_started(monkeypatch=None) -> None:
    """The honest-failure seam: a refusal RAISES dagster.Failure (=> failed run); a start
    returns normally. Monkeypatch httpx.post so no network is touched."""
    import httpx
    from dagster import Failure

    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["payload"] = json
        return _FakeResp(*fake_post._resp)

    orig = httpx.post
    httpx.post = fake_post
    try:
        # refusal -> Failure
        fake_post._resp = (422, {"status": "REVIEW_STATE_UNSOURCED", "notice_id": "IPCN25300X"})
        raised = False
        try:
            ers.submit_review({"notice_id": "IPCN25300X"}, bff_url="http://bff", token="t")
        except Failure:
            raised = True
        assert raised, "a 422 refusal must raise dagster.Failure (failed run)"
        assert captured["url"] == "http://bff/reviews"

        # started -> returns ("started", body)
        fake_post._resp = (200, {"status": "STARTED", "workflow_id": "wf1", "count": 2})
        outcome, body = ers.submit_review({"notice_id": "IPCN25300X"}, bff_url="http://bff", token="t")
        assert outcome == "started" and body["workflow_id"] == "wf1"
    finally:
        httpx.post = orig


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
