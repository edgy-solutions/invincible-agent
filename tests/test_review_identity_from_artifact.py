"""REVIEW IDENTITY comes from the ARTIFACT — the fourth enforcement point.

THE LIVE FAILURE (work, 2026-07-31). Eleven notices re-run, eleven `STARTED` logs, ONE
review. No crashes. The other ten were not slow, not filtered, not refused — they were
PERMANENTLY unable to produce a review, and nothing said so.

Two mechanisms compounded into one silent failure:

  1. RESTATE WORKFLOW KEYS ARE SINGLE-USE. A key may be submitted exactly once, ever. A
     second `workflow_send` to a spent key does nothing — and that send is FIRE-AND-FORGET,
     so `start_review` returns STARTED regardless. "STARTED" means "the workflow was sent",
     never "a review exists in someone's queue".
  2. THE KEY WAS DERIVED FROM `notice_id` — the LLM-extracted doc_id. So a notice whose
     first attempt died burned its key forever: re-extraction cannot change the key (the
     header pass yields the same doc_id), and every retry logs STARTED. The only recovery
     was hand-editing doc_ids in MinIO.

And the collision hazard rode along: two DIFFERENT documents deriving the same doc_id
collapsed into one review — the same "inbound" failure already fixed at three other sites.

THE RULE, at its fourth site: identity comes from what the artifact IS and where it lives
(ETag + key), never from a value a model derived. The other three are the sensor's run_key,
the triage task_id, and the ingress idempotency key.

Run:  uv run --frozen --extra agent-fleet python -m pytest tests/test_review_identity_from_artifact.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _compose():
    try:
        from agent_fleet.restate_analyst.review_starter import compose_workflow_id  # noqa: PLC0415
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"review_starter not importable here: {type(e).__name__}: {e}")
    return compose_workflow_id


_SVC = "service-account-review-starter"


# ── THE REGRESSION: a re-extraction must be able to produce a review ───────
def test_a_reextraction_gets_a_fresh_key_so_a_dead_notice_can_recover():
    """THE ten-notices bug. Same notice, re-extracted (new bytes -> new ETag) must yield a
    DIFFERENT workflow key, or Restate's single-use semantics make the first failed attempt
    permanent. Before the fix these two were identical strings."""
    k = _compose()
    first = k("PCN-23-0171", _SVC, "etag-aaa-sustainment/a/generated/review.json")
    redone = k("PCN-23-0171", _SVC, "etag-bbb-sustainment/a/generated/review.json")
    assert first != redone, (
        "a re-extraction reuses the spent workflow key — the notice can never produce a "
        "review again, and every retry will still log STARTED"
    )


def test_the_same_artifact_stays_idempotent():
    """The other half: re-sending the SAME bytes must NOT mint a second review. Fixing the
    dead-notice case by uniquifying every call would trade a silent loss for silent
    duplication in reviewers' queues."""
    k = _compose()
    rk = "etag-aaa-sustainment/a/generated/review.json"
    assert k("PCN-23-0171", _SVC, rk) == k("PCN-23-0171", _SVC, rk)


# ── the collision hazard, at its fourth site ───────────────────────────────
def test_two_documents_sharing_a_doc_id_do_not_collapse_into_one_review():
    """The "inbound" incident reaching review identity. Both derive doc_id "inbound"; keyed
    on it they shared a workflow AND a grouped task, so one notice silently received the
    other's review."""
    k = _compose()
    a = k("inbound", _SVC, "etag-aaa-sustainment/inbound/generated/DiodesA_pdf/review.json")
    b = k("inbound", _SVC, "etag-bbb-sustainment/inbound/generated/QorvoB_pdf/review.json")
    assert a != b


def test_two_initiators_still_separate():
    k = _compose()
    rk = "etag-aaa-s/a/generated/review.json"
    assert k("PCN-1", "alice@example.com", rk) != k("PCN-1", _SVC, rk)


# ── readability is deliberate, not incidental ──────────────────────────────
def test_the_notice_id_survives_in_the_key_for_humans():
    """These keys are read in Restate's UI and in logs DURING INCIDENTS — an opaque hash
    would have made this very bug harder to see. notice_id stays as a readable prefix; it is
    simply no longer load-bearing for identity."""
    k = _compose()
    key = k("PCN-23-0171", _SVC, "etag-aaa-s/a/generated/review.json")
    assert key.startswith("pcn-review-PCN-23-0171-")
    assert _SVC in key


# ── the ops path degrades honestly ─────────────────────────────────────────
@pytest.mark.parametrize("absent", [None, "", "   "])
def test_no_artifact_falls_back_to_the_old_shape(absent):
    """The hand-driven ops/re-drive path names no artifact, so it keeps the old key and stays
    subject to the single-use constraint — honest rather than silently uniquified, the same
    choice the ingress idempotency key makes when it cannot name an artifact."""
    k = _compose()
    assert k("PCN-1", _SVC, absent) == f"pcn-review-PCN-1-{_SVC}"


# ── ONE identity, not two derivations ──────────────────────────────────────
def test_the_grouped_task_key_is_derived_from_the_workflow_key():
    """`task_key` was computed INDEPENDENTLY from the notice ("grouped:{fingerprint}:{approver}"),
    so it carried the identical collision hazard sitting right beside the key it had to agree
    with. The grouped task is 1:1 with the workflow — its identity must COME FROM the workflow,
    not be recomputed in parallel and hope to match."""
    # RE-POINTED 2026-08-04, not weakened. M3.2's delegation moved the grouped-task construction out
    # of grouped_review_workflow.py into main.py's _run_grouped_human_await; this assertion was
    # source-ANCHORED to the old file and went red on a legitimate move — a guard orphaned by a
    # refactor, indistinguishable from a real regression until someone reads it. The PROPERTY is
    # unchanged and still asserted; only its address moved. (Standing lesson: an assertion anchored to
    # a file path is a guard with a dependency nobody declares.)
    _RA = _ROOT / "agent_fleet" / "restate_analyst"
    src = "\n".join(
        (_RA / f).read_text(encoding="utf-8") for f in ("main.py", "grouped_review_workflow.py")
    )
    assert '"task_key": f"grouped:{ctx.key()}"' in src, (
        "the grouped task id is no longer derived from the workflow key in EITHER the executor or "
        "the workflow module — identity must come FROM the workflow, not be recomputed beside it"
    )
    assert '"task_key": f"grouped:{notice_fingerprint}:{approver}"' not in src, (
        "the grouped task id is being derived from the notice again — a second independent "
        "derivation of identity is how the two silently disagree"
    )


def test_request_key_actually_reaches_the_composer():
    """The producer half. `request_key` was deliberately NOT forwarded ("transport-level
    identity, not an input to composition") — and review identity is exactly what needed it.
    Asserted against the BFF's source so the field cannot be quietly dropped again, which is
    the drop-class this codebase has hit four times."""
    src = (_ROOT / "src" / "iagent" / "gateway.py").read_text(encoding="utf-8")
    assert 'body["request_key"] = req.request_key or ""' in src


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
