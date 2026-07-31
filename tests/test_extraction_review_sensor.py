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
import os
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
            {"field_path": "header.categories", "value": ["Material", "Process"], "needs_review": False},
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
    # in_scope_mpns MUST list every affected MPN — start_review's funnel filters out-of-scope parts
    # BEFORE residue, so omitting this returns NO_RESIDUE (the auto-fire reviews nothing). Regression
    # guard for the live bug of 2026-07-28; without this line the shape-test passed on an empty scope.
    assert payload["in_scope_mpns"] == ["MPN-A", "MPN-B"], payload["in_scope_mpns"]
    # categories MUST be sourced from the extraction — every PCN disposition rule requires a
    # change category, so an empty list makes the proposer return UNCLASSIFIABLE for EVERY part
    # and the UI shows 'needs a disposition' on all of them. Regression guard for the live bug of
    # 2026-07-29 (the payload dropped categories entirely). Sourced from the header.categories item.
    assert payload["categories"] == ["Material", "Process"], payload["categories"]
    # The sensor reads parts + their per-part needs_review STRAIGHT FROM review.json, so it ATTESTS
    # the provenance of review-state. start_review's tripwire fires when this is ABSENT (a graph-built
    # request can't honestly set it) instead of guessing from the {doc-flagged, no-part-flagged}
    # silhouette — which a CORRECT extraction legitimately produces (Qorvo 23-0171 was refused that
    # way). Drop this field and every doc-level-only review reason becomes a hard refusal again.
    assert payload["review_state_source"] == "extraction", payload


def test_extraction_warnings_are_carried_to_the_reviewer() -> None:
    """A degraded extraction's warnings must RIDE WITH the batch. Live case (Diodes PCN 2683):
    review.json recorded "2/5 table crops failed — extracted parts are likely INCOMPLETE" and
    NOTHING downstream carried it, so the reviewer would have dispositioned a partial parts
    list believing it complete — the missing parts silently getting no disposition. A partial
    list is indistinguishable from a complete one unless the payload says so."""
    rj = _review_json(doc_needs_review=True, part0_needs=False, part1_needs=False)
    rj["doc_review_reasons"] = [
        "PARTS MAY BE MISSING: 2/5 table crops failed (e.g. vision timeout) — "
        "extracted parts are likely INCOMPLETE"
    ]
    payload = ers.build_start_review_payload(rj)
    assert payload["extraction_warnings"] == rj["doc_review_reasons"], payload


def test_no_warnings_on_a_clean_extraction() -> None:
    """Absent field (older review.json) and clean extractions both yield [] — no phantom
    banner, so the warning means something when it DOES appear."""
    payload = ers.build_start_review_payload(
        _review_json(doc_needs_review=False, part0_needs=False, part1_needs=False))
    assert payload["extraction_warnings"] == []


def test_categories_from_string_and_top_level_forms() -> None:
    """header.categories may be a LIST (rich extraction) or a comma/;-separated STRING (some
    viewers/exports); and a newer doc-tools writes a top-level `categories`. All three normalize
    to the same enum-name list the ruleset's pcn:changeClass keys expect."""
    # string form in the header item
    rj = _review_json(doc_needs_review=False, part0_needs=False, part1_needs=False)
    for it in rj["review_items"]:
        if it["field_path"] == "header.categories":
            it["value"] = "Material, Process ; Location"
    assert ers.build_start_review_payload(rj)["categories"] == ["Material", "Process", "Location"]
    # top-level field WINS (newer doc-tools) over the header item
    rj2 = _review_json(doc_needs_review=False, part0_needs=False, part1_needs=False)
    rj2["categories"] = ["Discontinuation"]
    assert ers.build_start_review_payload(rj2)["categories"] == ["Discontinuation"]
    # doc_type prefers the extraction's own over the "PCN" default
    rj3 = _review_json(doc_needs_review=False, part0_needs=False, part1_needs=False)
    rj3["doc_type"] = "PDN"
    assert ers.build_start_review_payload(rj3)["doc_type"] == "PDN"


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
    """The outcomes. `refused` SPLIT into refused_content / refused_systemic when refusal
    routing landed: a per-notice content problem goes to the reviewers who own the answer
    (triage task, run COMPLETES); a deployment problem stays with ops (failed run). The
    split is sealed in tests/test_refusal_routing.py — including over the real
    {"detail": {...}} wire shape, which these flat bodies deliberately do not exercise."""
    assert ers.classify_start_review(200, {"status": "STARTED", "workflow_id": "wf1", "count": 2})[0] == "started"
    assert ers.classify_start_review(200, {"status": "NO_RESIDUE", "counts": {}})[0] == "no_residue_skip"
    # NOT_ENTITLED_TO_INITIATE comes back 403 (the auto-starter lacks can_invoke) -> a CONFIG
    # gap that fails every notice identically, so it stays a loud failed run for ops.
    assert ers.classify_start_review(403, {"status": "NOT_ENTITLED_TO_INITIATE"})[0] == "refused_systemic"
    # 422 = the tripwire / rules refusals — now routed by WHO OWNS THE ANSWER.
    assert ers.classify_start_review(422, {"status": "REVIEW_STATE_UNSOURCED"})[0] == "refused_content"
    assert ers.classify_start_review(422, {"status": "RULES_NOT_FOUND"})[0] == "refused_systemic"
    # 502 unreachable / any non-200 -> systemic.
    assert ers.classify_start_review(502, {"error": "review_start_unreachable"})[0] == "refused_systemic"


class _FakeResp:
    def __init__(self, status_code: int, body: dict):
        self.status_code = status_code
        self._body = body
        self.text = str(body)

    def json(self):
        return self._body


def test_submit_review_raises_on_refusal_returns_on_started(monkeypatch=None) -> None:
    """The honest-failure seam: a SYSTEMIC refusal RAISES dagster.Failure (=> failed run);
    a start returns normally. Monkeypatch httpx.post so no network is touched.

    The refusal used here is RULES_NOT_FOUND, not REVIEW_STATE_UNSOURCED — a deployment
    problem, which is what still belongs to ops. A per-notice CONTENT refusal deliberately
    no longer raises here: it is returned so the caller can route it to the reviewers who
    own the answer, and that path is sealed in tests/test_refusal_routing.py."""
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
        # systemic refusal -> Failure
        fake_post._resp = (422, {"status": "RULES_NOT_FOUND", "notice_id": "IPCN25300X"})
        raised = False
        try:
            ers.submit_review({"notice_id": "IPCN25300X"}, bff_url="http://bff", token="t")
        except Failure:
            raised = True
        assert raised, "a systemic 422 refusal must raise dagster.Failure (failed run)"
        assert captured["url"] == "http://bff/reviews"

        # started -> returns ("started", detail, body)
        fake_post._resp = (200, {"status": "STARTED", "workflow_id": "wf1", "count": 2})
        outcome, _detail, body = ers.submit_review({"notice_id": "IPCN25300X"}, bff_url="http://bff", token="t")
        assert outcome == "started" and body["workflow_id"] == "wf1"
    finally:
        httpx.post = orig


def test_mint_service_token_raises_loud_on_failure_returns_on_success():
    """The credential joins the observable seam (the ruling's rider): a mint failure — token endpoint
    unreachable, or a non-200 — RAISES dagster.Failure NAMING the cause, so the Dagster run fails loudly.
    Positive control: a 200 with an access_token returns it, so the red assertions discriminate. "Keycloak
    was down so no reviews started and nothing said so" is exactly the invisible-death this refuses."""
    import httpx
    from dagster import Failure

    os.environ["KEYCLOAK_REALM_URL"] = "http://keycloak/realms/invincible-agent"
    os.environ["REVIEW_STARTER_CLIENT_ID"] = "iagent-review-starter"
    os.environ["REVIEW_STARTER_CLIENT_SECRET"] = "s"
    orig = httpx.post
    try:
        # transport down -> loud, NAMED Failure (mentions the unreachable endpoint)
        def _down(*a, **k):
            raise httpx.ConnectError("connection refused")
        httpx.post = _down
        raised = False
        try:
            ers.mint_service_token()
        except Failure as f:
            raised = True
            assert "unreachable" in str(f.description).lower()
        assert raised, "token endpoint down must raise dagster.Failure (failed run), not return silently"

        # non-200 (e.g. bad secret) -> loud Failure
        httpx.post = lambda *a, **k: _FakeResp(401, {"error": "invalid_client"})
        raised = False
        try:
            ers.mint_service_token()
        except Failure:
            raised = True
        assert raised, "a non-200 client-credentials mint must raise dagster.Failure"

        # 200 with an access_token -> returns it (positive control: the red tests discriminate)
        httpx.post = lambda *a, **k: _FakeResp(200, {"access_token": "tok-abc", "expires_in": 300})
        assert ers.mint_service_token() == "tok-abc"
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
