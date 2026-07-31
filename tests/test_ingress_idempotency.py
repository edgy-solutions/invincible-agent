"""INGRESS IDEMPOTENCY — a retry ATTACHES, it does not race a second composition.

THE GAP THIS CLOSES (diagnosed 2026-07-30, narrower than the ruling that sent us looking).
`start_review`'s composition was ALREADY durable: it is a Restate service handler whose work
runs in journaled `ctx.run` steps. Durability was never missing. What was missing is at the
FRONT DOOR: the ingress call carried no idempotency key, so when a hundreds-of-parts notice
outran the caller's HTTP budget, Restate kept composing (the invocation is durable), the
caller saw a ReadTimeout, the Dagster run failed — and the re-drive started a SECOND
composition racing the first. Exactly-once is sealed INSIDE the workflow; this closes the
same property at ingress. Attach-don't-recompose.

THE KEY IS THE ARTIFACT, NEVER `notice_id`. Third enforcement point of one rule (run_key,
triage task_id, now the ingress key): identity comes from what the artifact IS and where it
lives, never from an LLM-extracted field that collapses to a shared fallback exactly when
extraction is failing. Keying here on notice_id would make two documents that both derived
"inbound" ATTACH TO EACH OTHER'S COMPOSITION — one notice silently receiving another's
review, which is worse than either failure it would be papering over.

SUPERSEDE vs DUPLICATE is the distinction the key must preserve:
  * RE-EXTRACTION (new content, same location) = new work -> NEW key -> composes afresh
  * RETRY (same content) = same attempt      -> SAME key -> attaches

Run:  uv run --frozen python -m pytest tests/test_ingress_idempotency.py -q
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
_spec = importlib.util.spec_from_file_location("ers_idem", _SENSOR)
ers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ers)  # type: ignore[union-attr]


def _key():
    """The BFF's key derivation, skipped loudly if the gateway's deps are unavailable."""
    try:
        from src.iagent.gateway import _ingress_idempotency_key  # noqa: PLC0415
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"cortex-bff gateway not importable here: {type(e).__name__}: {e}")
    return _ingress_idempotency_key


# ── THE FRONT-DOOR RACE ────────────────────────────────────────────────────
class _FakeRestateIngress:
    """A faithful stub of the ingress semantics this design depends on: a request carrying
    an idempotency key ALREADY SEEN returns the first invocation's result and does NOT
    start a second one; an unkeyed request always composes.

    This is testing OUR USE of the contract — that both attempts present the same key —
    which is the half that lives in our code. Restate honouring the key is its own
    guarantee, stubbed here so the race is expressible offline at all."""

    def __init__(self):
        self.compositions = 0
        self._by_key = {}

    def post(self, *, idempotency_key, outcome):
        if idempotency_key is not None and idempotency_key in self._by_key:
            return self._by_key[idempotency_key]        # ATTACH: no new composition
        self.compositions += 1
        result = dict(outcome, workflow_id=f"wf-{self.compositions}")
        if idempotency_key is not None:
            self._by_key[idempotency_key] = result
        return result


def test_a_timed_out_call_and_its_redrive_compose_exactly_once():
    """THE SEAL. The sensor times out mid-composition and Dagster re-drives the same
    artifact. Both attempts must present the SAME key, so the second attaches to the first
    invocation and returns its real outcome — one composition, one workflow, one review."""
    k = _key()
    ingress, artifact, approver = _FakeRestateIngress(), "etag-aaa-sustainment/a/generated/review.json", "svc:review-starter"

    first = ingress.post(idempotency_key=k(artifact, approver), outcome={"status": "STARTED"})
    # ... client gives up here; Restate keeps composing. Dagster re-drives:
    second = ingress.post(idempotency_key=k(artifact, approver), outcome={"status": "STARTED"})

    assert ingress.compositions == 1, (
        "the re-drive started a SECOND composition racing the first — this is the "
        "duplicate-invocation bug the ingress key exists to close"
    )
    assert second["workflow_id"] == first["workflow_id"], (
        "the retry must receive the FIRST invocation's real outcome, not a fresh one"
    )


def test_a_reextraction_is_new_work_and_composes_again():
    """SUPERSEDE, not duplicate. New content at the same location is a different notice
    state and MUST get its own composition — a key that ignored content would make a
    corrected extraction silently return the stale review."""
    k = _key()
    ingress, approver = _FakeRestateIngress(), "svc:review-starter"
    key_path = "sustainment/a/generated/review.json"

    ingress.post(idempotency_key=k(f"etag-aaa-{key_path}", approver), outcome={"status": "STARTED"})
    ingress.post(idempotency_key=k(f"etag-bbb-{key_path}", approver), outcome={"status": "STARTED"})

    assert ingress.compositions == 2, "a re-extraction must compose afresh, not attach"


def test_two_notices_that_derived_the_same_doc_id_do_not_attach_to_each_other():
    """THE "inbound" INCIDENT at its third enforcement point. Both documents derive
    doc_id "inbound"; keyed on that they would share one composition and one of them would
    receive the OTHER's review."""
    k = _key()
    a = k("etag-aaa-sustainment/inbound/generated/DiodesA_pdf/review.json", "svc:review-starter")
    b = k("etag-bbb-sustainment/inbound/generated/QorvoB_pdf/review.json", "svc:review-starter")
    assert a != b


def test_two_initiators_on_one_artifact_get_separate_invocations():
    """The composed workflow_id is pcn-review-{notice_id}-{approver}, so two initiators are
    two outcomes. Sharing a key would hand the second caller the first's workflow — and
    since the approver is stamped SERVER-SIDE from the token, a caller cannot aim at
    someone else's invocation slot either."""
    k = _key()
    assert k("etag-aaa-s/a/generated/review.json", "alice@example.com") != \
           k("etag-aaa-s/a/generated/review.json", "svc:review-starter")


# ── the no-key path is HONEST, not optimistically deduplicated ─────────────
@pytest.mark.parametrize("absent", [None, "", "   "])
def test_no_artifact_means_no_key_at_all(absent):
    """The hand-driven ops/re-drive path names no artifact. Returning None sends NO header,
    which is honestly non-idempotent. Inventing a key from whatever fields are present
    would look safe while silently deduplicating unrelated requests — an optimistic default
    at exactly the layer that must not guess."""
    assert _key()(absent, "alice@example.com") is None


def test_unkeyed_calls_always_compose():
    """And the honest consequence, stated: two unkeyed ops calls really do compose twice.
    That is the correct behaviour for a human deliberately re-driving a notice."""
    ingress = _FakeRestateIngress()
    ingress.post(idempotency_key=None, outcome={"status": "STARTED"})
    ingress.post(idempotency_key=None, outcome={"status": "STARTED"})
    assert ingress.compositions == 2


def test_key_is_stable_and_opaque():
    k = _key()
    assert k("etag-aaa-s/a/review.json", "alice@example.com") == k("etag-aaa-s/a/review.json", "alice@example.com")
    # Opaque: the raw s3 key and the identity are not readable out of the header value,
    # which travels through Restate's logs and metrics.
    assert "review.json" not in k("etag-aaa-s/a/review.json", "alice@example.com")


# ── the producer half: the sensor actually sends the artifact identity ─────
def test_sensor_payload_carries_the_artifact_request_key():
    payload = ers.build_start_review_payload(
        {"doc_id": "PCN-1", "review_items": []},
        request_key="etag-aaa-sustainment/a/generated/review.json")
    assert payload["request_key"] == "etag-aaa-sustainment/a/generated/review.json"


def test_request_key_matches_the_sensors_own_run_key_shape():
    """ONE identity, three consumers. The ingress key, the Dagster run_key and the triage
    task_id must all be derived from the same ETag+key string — if they drift, the same
    artifact is 'the same work' to one mechanism and 'new work' to another, which is how a
    retry becomes a duplicate."""
    from datetime import datetime, timezone
    obj = {"Key": "sustainment/a/generated/review.json", "ETag": '"aaa"',
           "LastModified": datetime(2026, 7, 30, tzinfo=timezone.utc)}
    assert ers._run_key_of(obj) == "aaa-sustainment/a/generated/review.json", (
        "the op builds request_key with this exact shape; a change here must change both"
    )


def test_bff_declares_request_key_so_it_is_not_dropped():
    """The passthrough class again: a field the sensor sends and the BFF does not declare
    is silently eaten by Pydantic — how review_state_source went missing."""
    try:
        from src.iagent.gateway import ReviewStartRequest  # noqa: PLC0415
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"cortex-bff gateway not importable here: {type(e).__name__}: {e}")
    assert "request_key" in ReviewStartRequest.model_fields


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


# ── THE CACHED-SYSTEMIC-REFUSAL ESCAPE (found live 2026-07-31) ──────────────
def test_epoch_absent_by_default_leaves_the_key_purely_artifact_derived():
    """Default: no epoch, so the key is exactly ETag+location and normal retries attach."""
    assert ers._REQUEST_KEY_EPOCH == "" or ers._REQUEST_KEY_EPOCH.endswith("|")


def test_epoch_changes_the_key_so_a_cached_refusal_can_be_re_driven(monkeypatch):
    """THE LIVE FINDING. A notice refused NOT_ENTITLED_TO_INITIATE (missing grant) is a
    COMPLETED invocation; once the grant is fixed, re-driving the identical artifact attaches
    to the stored 403 and replays the refusal — correct dedup, wrong outcome, because what
    changed was the ENVIRONMENT and nothing about the artifact moved. Bumping the epoch
    invalidates cached refusals without touching any artifact.

    A CONTENT refusal needs no epoch: re-extracting changes the ETag, which changes the key
    on its own. That asymmetry is why this knob exists and why it is ops-driven."""
    k = _key()
    artifact, approver = "etag-aaa-s/a/generated/review.json", "svc:review-starter"
    before = k(artifact, approver)
    after = k("epoch-2|" + artifact, approver)
    assert before != after, (
        "bumping the epoch must produce a different ingress key, or a cached systemic "
        "refusal is unrecoverable without re-extracting an artifact that is not the problem"
    )


def test_epoch_is_a_prefix_not_a_replacement():
    """The epoch must not erase artifact identity — supersede-vs-duplicate still has to work
    WITHIN an epoch, or bumping it would make every retry a fresh composition forever."""
    k = _key()
    a = k("epoch-2|etag-aaa-s/a/generated/review.json", "svc")
    b = k("epoch-2|etag-bbb-s/a/generated/review.json", "svc")
    same = k("epoch-2|etag-aaa-s/a/generated/review.json", "svc")
    assert a != b, "different content within one epoch must still be different work"
    assert a == same, "identical content within one epoch must still attach"
