"""Every turn that reaches the gateway produces an artifact — `complete` or `failed`, never nothing.

THE ONE INVARIANT THE WRITER CANNOT ASSERT ABOUT ITSELF. Everything else built this week records
*what happened*. This closes the case where **the dispatch never happened**, and no amount of
better recording reaches it:

> **You cannot record an absence.**

MEASURED 2026-09-14, and it is the worst failure of the day. Four `orchestrate` calls reached the
gateway. Zero artifacts were written. The log stops dead after

    pre-resolved route for run session-1789440249741 ... skipping /plan, /resolve, /classify_predicate

— a one-word slip (`bound_slots` where the scope had `request.bound_slots`) raised `NameError`
inside an SSE generator. The stream ended. The rail showed no new row; the card held only the
question text. **Not failed, not complete: nothing.**

TWO WAYS OUT WITHOUT WRITING, AND BOTH ARE CLOSED.

  1. **An exception escapes the body.** `generate_dagster_stream` is now a thin wrapper around
     `_generate_dagster_stream_inner`; it catches, writes a `failed` artifact carrying the
     exception text, and emits a terminal error pair so the card renders the failure.

  2. **The body returns having never flipped `status` off `pending`.** No exception involved, and
     the outcome was identical — the dispatch site logged and SKIPPED the write. Its reasoning
     was careful and wrong in one step: *"the dispatch site has no idea what actually happened."*
     True of the DETAIL, false of the FACT — **"the turn ended without recording an outcome" is
     itself what happened**, and naming that is not guessing a cause.

WHY THE WRAPPER AND NOT A `try` INSIDE THE BODY: the body builds its bundle partway through, so a
handler within it covers only the part after the bundle exists — and the defect that prompted all
this fired BEFORE that point. The wrapper writes from its own parameters, which is the only
version that covers the failure that actually happened.

Run: uv run --frozen pytest tests/routing/test_a_turn_never_ends_in_silence.py -v
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from iagent import gateway

_REPO = Path(__file__).resolve().parents[2]
_GW = _REPO / "src" / "iagent" / "gateway.py"


def _src() -> str:
    return "\n".join(
        ln for ln in _GW.read_text(encoding="utf-8").splitlines()
        if not ln.lstrip().startswith("#")
    )


# ── THE BOUNDARY EXISTS AND WRAPS THE WHOLE BODY ────────────────────────────────────────────

def test_THE_ENTRY_POINT_IS_THE_WRAPPER_not_the_body():
    """The name every caller uses must be the guarded one. If the body kept the public name, the
    boundary would be a function nothing calls — which is this repo's most frequent defect."""
    assert hasattr(gateway, "_generate_dagster_stream_inner"), (
        "the body was not split out, so there is nothing for a wrapper to guard"
    )
    src = _src()
    assert "async def generate_dagster_stream(" in src
    assert "_generate_dagster_stream_inner(" in src, (
        "the wrapper does not delegate to the body"
    )


def test_THE_WRAPPER_CATCHES_EVERYTHING_not_a_named_subset():
    """A `NameError` is not in any hand-listed tuple somebody would think to write. The whole
    point is the exception nobody predicted — which is what the last one was."""
    src = _src()
    i = src.index("async def generate_dagster_stream(")
    j = src.index("async def _generate_dagster_stream_inner(", i)
    body = src[i:j]
    assert "except Exception" in body, (
        "the boundary catches a narrow set; the failure it exists for was a NameError, which "
        "nobody would have listed"
    )
    assert "_dispatch_answer_artifact(" in body, (
        "the boundary does not write an artifact, so a raised turn is still silent"
    )


def test_THE_BOUNDARY_ARTIFACT_IS_EXPLICITLY_FAILED():
    """`status` is required at construction precisely so a forgotten one cannot persist as
    `complete`, and this is the path where forgetting would be easiest: nothing here knows
    whether an answer was nearly ready."""
    b = gateway._boundary_failure_bundle(
        _Req(), "u1", "PROGRAM_FINANCE_ANALYST", ["PROGRAM_FINANCE"], "topaz",
        {"exception": "NameError", "message": "boom"},
    )
    assert b["status"] == "failed"
    assert b["resolved_intent"]["failure_cause"]["exception"] == "NameError"
    assert b["question_text"] == "brief on how this program is doing"
    assert b["produced_for"]["user_id"] == "u1"


def test_THE_BOUNDARY_ARTIFACT_SURVIVES_A_BARE_REQUEST():
    """It runs when the body has already failed, so it must not add a second failure of its own
    by assuming fields are present."""
    class _Bare:
        pass
    b = gateway._boundary_failure_bundle(_Bare(), "u", None, None, "fallback", {"x": 1})
    assert b["status"] == "failed"
    assert b["id"], "an artifact with no id cannot be read back"
    assert b["message_id"] == ""


def test_A_WRITER_FAILURE_DOES_NOT_REPLACE_THE_ORIGINAL_CAUSE():
    """If the artifact write itself raises, the reader must still be able to find the ENGINE
    failure. Letting it propagate would swap a diagnosable cause for a storage one, and the
    reader would chase the wrong thing."""
    src = _src()
    i = src.index("async def generate_dagster_stream(")
    j = src.index("async def _generate_dagster_stream_inner(", i)
    body = src[i:j]
    assert body.count("except Exception") >= 2, (
        "the boundary's own write is unguarded; a Neo4j blip would mask the original failure"
    )
    assert "original cause" in _GW.read_text(encoding="utf-8")


def test_THE_CLIENT_GETS_A_TERMINAL_EVENT_when_nothing_was_yielded():
    """A hung stream and a failed one look identical to a person, and only one is true."""
    src = _src()
    i = src.index("async def generate_dagster_stream(")
    j = src.index("async def _generate_dagster_stream_inner(", i)
    body = src[i:j]
    assert "if not _wrote:" in body, (
        "the boundary emits a terminal event unconditionally, which would append an error after "
        "a stream that already ended cleanly"
    )
    assert "_perror(" in body and 'stream_end' in body


# ── THE SECOND WAY OUT: A BODY THAT NEVER FLIPPED STATUS ────────────────────────────────────

def test_A_PENDING_BUNDLE_IS_WRITTEN_AS_FAILED_not_skipped():
    """The dispatch site used to log and RETURN. The log was the only trace, in a pod whose logs
    rotate — which is the same silence by a slower route."""
    src = _src()
    i = src.index("async def _dispatch_answer_artifact(")
    block = src[i:i + 4000]
    assert 'bundle["status"] = "failed"' in block, (
        "a bundle still 'pending' at stream_end is not written, so an exit path that forgets to "
        "flip status produces no artifact at all"
    )
    assert "NoOutcomeRecorded" in block, (
        "the pending case writes without naming WHY, leaving a failed artifact whose cause is "
        "as unrecoverable as the silence it replaced"
    )


def test_THE_PENDING_CAUSE_CLAIMS_ONLY_WHAT_IS_KNOWN():
    """The old reasoning was right that this site cannot know what went wrong. The fix is to
    record the fact it DOES know — the outcome was never recorded — not to invent one."""
    raw = _GW.read_text(encoding="utf-8")
    i = raw.index("NoOutcomeRecorded")
    msg = raw[i:i + 700]
    assert "never recorded" in msg
    for invented in ("engine", "timeout", "refused"):
        assert invented not in msg.lower().split("where")[0], (
            f"the pending cause asserts {invented!r}, which this site cannot know"
        )


def test_THE_SKIP_RETURN_IS_GONE():
    """Its removal IS the change. A `return` there discards the write the branch just prepared,
    and the branch would read as a fix while producing the original defect."""
    # ⛔ ANCHORED INSIDE THE FUNCTION. The first version searched the whole file for
    # `bundle["status"] = "failed"` and matched an unrelated site hundreds of lines away — a
    # substring that is correct everywhere and identifying nowhere, which is the same shape as
    # reading a grep COUNT for a grep RESULT.
    src = _src()
    fn = src.index("async def _dispatch_answer_artifact(")
    block = src[fn:fn + 4000]
    i = block.index('bundle["status"] = "failed"')
    j = block.index("_writer = get_writer()", i)
    between = block[i:j]
    # ⛔ THE FIRST VERSION ASSERTED `_writer = get_writer()` APPEARS AFTER THE STATUS LINE — and
    # a `return` between them does not remove it, so the assertion passed with the defect
    # restored. A guard that cannot fire, inside the seal written to prove a guard fires.
    # Mutation caught it; reading the assertion did not.
    #
    # What matters is that nothing EXITS between preparing the write and performing it.
    assert not any(
        ln.strip() in ("return", "return None") or ln.strip().startswith("raise ")
        for ln in between.splitlines()
    ), (
        "the pending branch exits between setting status=failed and the write, so the branch "
        "reads as a fix while producing the original defect. "
        + repr(between)
    )


class _Req:
    message = "brief on how this program is doing"
    session_id = "session-1789440249741"
    artifact_id = "artifact-4-1789440249741"


@pytest.mark.parametrize("marker", ["You cannot record an absence", "NameError"])
def test_THE_MEASUREMENT_TRAVELS_WITH_THE_CODE(marker: str):
    """A later reader simplifying the wrapper away would be removing a guard whose cost is not
    visible from the call site."""
    assert marker in _GW.read_text(encoding="utf-8")
