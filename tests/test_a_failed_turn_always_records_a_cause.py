"""A FAILED artifact always carries a `failure_cause` — from the one exit every route passes.

THE DEFECT, measured on `artifact-1-1789497444373` ("draft a risk assessment for HAZ-1003"):

    status        failed
    duration_ms   58757
    failure_cause ABSENT

The resolution had worked perfectly — `outcome: exact`, the hazard's full label bound — and then
something waited 59 seconds and the record said nothing about what. **74 could not replay it
because there was no request to replay.**

WHY IT ESCAPED THE EXISTING WRITER. `failure_cause` is written in `direct_dispatch`'s `except`
block, so the graph-host route records its cause and the per-verb `/measure/{fn}` route safety uses
records none. **Five call sites in `gateway.py` set `status = "failed"` and exactly one of them
writes a cause.**

> Extending the writer to each route is a fix that must be repeated every time a route is added.
> This is the **exit they all pass through**, which is the only place the property can be made
> true of routes nobody has written yet.

AND IT IS THE SAME SILENCE AS THE `pending` BRANCH ABOVE IT, ONE STATE OVER. That branch catches a
route that returned without recording an outcome at all. A route that records `failed` and no
reason produces an artifact asserting a turn failed and nothing about why — which reads as a
diagnosis rather than as its absence.

WHAT IT DOES NOT DO: it does not claim the engine failed. Nobody at this exit knows that. It
records the one fact available — the turn ended failed and the path that failed it left no reason —
plus whatever routing metadata the bundle already carries, so the next diagnosis starts at the
right pod instead of at this function. `exception: "NoCauseRecorded"` is deliberately not an
engine-shaped error name.

Run: uv run --frozen pytest tests/test_a_failed_turn_always_records_a_cause.py -v
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_GW = _REPO / "src" / "iagent" / "gateway.py"


def _src() -> str:
    return _GW.read_text(encoding="utf-8")


def _exit_block() -> str:
    """The artifact-write exit, bounded so an assertion cannot be satisfied by a neighbour.

    Sliced from the `pending` catch-all to the writer call that follows it — the same
    too-wide-a-slice trap `/templates`' seal records, where the window swallowed hundreds of
    lines and every `in` check could have passed for the wrong reason.
    """
    src = _src()
    i = src.index('if bundle["status"] == "pending":')
    j = src.index("_writer = get_writer()", i)
    return src[i:j]


def test_THE_FAILED_BRANCH_EXISTS_AT_THE_SHARED_EXIT():
    """The property must hold at the exit every route passes, not in each route's own handler."""
    block = _exit_block()
    assert 'if bundle.get("status") == "failed":' in block, (
        "nothing catches a FAILED artifact with no cause at the artifact-write exit, so a route "
        "that sets failed without recording why produces an artifact that says a turn failed "
        "and nothing about it"
    )
    assert "NoCauseRecorded" in block


def test_IT_ONLY_FIRES_WHEN_THE_CAUSE_IS_ABSENT():
    """A route that DID record a cause must keep it. Overwriting a real diagnosis with
    'no cause was recorded' would be strictly worse than the defect."""
    block = _exit_block()
    assert re.search(r'if not _ri\.get\(["\']failure_cause["\']\)', block), (
        "the branch does not check for an existing cause, so a route that recorded a real "
        "diagnosis has it replaced by the placeholder"
    )


def test_IT_DOES_NOT_CLAIM_THE_ENGINE_FAILED():
    """THE ARM WITH TEETH, and the one a 'a cause exists' check would miss entirely.

    An invented cause is worse than a missing one: a missing cause is visibly absent, while
    `exception: "HTTPError"` written by a function that never made a request is a false lead the
    next reader follows. The recorded exception names the ABSENCE of a record.
    """
    block = _exit_block()
    assert '"exception": "NoCauseRecorded"' in block, (
        "the placeholder uses an engine-shaped exception name, which reads as a diagnosis "
        "rather than as the absence of one"
    )
    assert "not a claim that the engine failed" in block, (
        "the reasoning is gone; a later reader will 'improve' the message into one that asserts "
        "a cause nobody established"
    )


def test_IT_CARRIES_WHAT_IS_KNOWN_SO_A_REPLAY_HAS_SOMEWHERE_TO_START():
    """The point of the record is the next diagnosis, and `where: _dispatch_answer_artifact`
    alone sends that diagnosis to this function — which is never where the failure was."""
    block = _exit_block()
    for field in ("route_status", "engine_name", "endpoint_url", "duration_ms"):
        assert field in block, (
            f"{field!r} is not carried, so the artifact names the absence of a cause without "
            f"naming where to look for one"
        )


def test_THE_WRITER_READS_THE_SAME_ROUTING_THE_ARTIFACT_PERSISTS():
    """THE JOIN, and its absence is why every field above was present and EMPTY in production.

    `test_IT_CARRIES_WHAT_IS_KNOWN...` asserts the field NAMES appear in the block. They did. The
    writer read `bundle["routing_inline"]` — a column read back in a different query — while the
    artifact persists `bundle["routing"]`, the live decision, a few lines further down. So every
    row carried a complete route beside a cause that said `route_status: ""`, under a comment
    claiming the emptiness was itself the finding.

    Measured 2026-09-18 on the sandbox: `routing` held
    `handled_by.engine_name`, `handled_by.endpoint_url`, `route_status`, `action.candidate_count`
    and `action.classify_called`; the `failure_cause` beside it held empty strings.

    Two ends correct, the relation between them asserted nowhere. So it is asserted here: the key
    the cause writer reads IS the key the artifact is given.
    """
    src = _src()

    # What the artifact is handed, from the `routing=` keyword at the write call.
    m = re.search(r"routing=bundle\[(['\"])([a-z_]+)\1\]", src)
    assert m, "could not find the artifact's `routing=` argument — this arm cannot bind"
    persisted_key = m.group(2)

    # What the cause writer reads.
    block = _exit_block()
    # ANCHORED ON THE ASSIGNMENT, not on any `bundle.get(...)` in the block. The first
    # draft matched the earliest one and read `resolved_intent` — the neighbour, not the
    # claim.
    r = re.search(r"_inline = bundle\.get\((['\"])([a-z_]+)\1\)", block)
    assert r, "the cause writer no longer reads a routing dict off the bundle"
    read_key = r.group(2)

    assert read_key == persisted_key, (
        f"the cause writer reads bundle[{read_key!r}] while the artifact persists "
        f"bundle[{persisted_key!r}] — the cause and the route it should name come from two "
        f"different objects, so a fully-routed turn records a cause with empty fields"
    )


def test_THE_CAUSE_SAYS_WHY_THERE_WAS_NO_ANSWER_not_only_where():
    """An empty candidate pool with `classify_called: false` is a turn that never reached the
    classifier. That is a different failure from a classifier that ran and refused, and the two
    are indistinguishable unless the record says which."""
    block = _exit_block()
    for field in ("candidate_count", "classify_called", "subject_uri"):
        assert field in block, (
            f"{field!r} is not carried, so 'nothing matched' cannot be told from 'nothing was "
            f"asked'"
        )


def test_THE_PENDING_BRANCH_SURVIVES():
    """The two are different states with different messages and neither replaces the other:
    `pending` is a route that recorded NO outcome; `failed` with no cause is a route that
    recorded the outcome and not the reason. Collapsing them loses which happened."""
    block = _exit_block()
    assert "NoOutcomeRecorded" in block
    assert "NoCauseRecorded" in block
    assert block.index("NoOutcomeRecorded") < block.index("NoCauseRecorded"), (
        "the failed branch now precedes the pending branch; a pending artifact would be "
        "reported as a failure with no cause rather than as an unrecorded outcome"
    )


@pytest.mark.parametrize("marker", ["artifact-1-1789497444373", "58757", "/measure/{fn}"])
def test_THE_MEASUREMENT_TRAVELS_WITH_THE_CODE(marker: str):
    """The artifact id, the 59 seconds, and the route that escaped the old writer. A later
    reader deciding this branch is defensive clutter needs the case that produced it."""
    assert marker in _src()
