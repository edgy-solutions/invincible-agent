"""Any workflow-backed task resumes, and the DECLARED verb survives the trip.

TWO GAPS, ADJACENT LINES, AND EITHER ALONE MAKES CHAINING IMPOSSIBLE.

**GAP 1 — only `workflow_ack` resumed.** The kind test was `== "workflow_ack"`, so every other
species that suspends a definition — every safety acceptance, concurrence and redraft — was
disposed in the projection while the workflow was never told. **The definition stayed suspended
forever with the task showing resolved:** the two halves disagreeing, and neither reporting it.

The condition that matters is `workflow_id`. A task carrying one is a task some definition is
suspended on; **the species is irrelevant to whether it should be resumed.** Keying on the kind
made a structural property depend on a name, so every new species inherited the defect silently
and `workflow_ack` was simply the first one anybody tried.

**GAP 2 — the verb was collapsed to two words before it reached the runtime.**
`"APPROVED" if req.decision == "approved" else "REJECTED"` meant `concurred` arrived as
**REJECTED** — it is not the string `"approved"` — and `accepted`, `not_concurred`,
`returned_for_rework`, `linked`, `new_hazard` and `dismissed` all arrived as one of two words
nobody declared.

**So a chaining row on `{outcome: concurred}` matched NOTHING FOREVER, and §4.3.7's sequence read
as a rejection at the moment a concurrence was given.** The runtime now terminates with the last
step's actual disposition; this is the other end of it — **the verb has to arrive intact for the
terminal to mean anything.**

PASSING IT THROUGH IS NOT WIDENING THE SURFACE. `validate_decision` gates the verb against the
species' declaration at line 2464, before this point. The collapse was a **second, undeclared
gate that only knew two words** — declining to narrow twice is not the same as not gating.

Run: uv run --frozen pytest tests/test_the_gateway_resumes_with_the_declared_verb.py -v
"""
from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_GW = _REPO / "src" / "iagent" / "gateway.py"


def _resume_block() -> str:
    """The resume block, sliced from source.

    Read as source rather than executed: the handler needs a live FastAPI request, an
    authenticated user, a resolved projection row and a reachable Restate ingress. A test that
    stood all that up would be testing Restate. What these assert is the SHAPE of what the
    gateway sends, which is the part the decision rail depends on.
    """
    src = _GW.read_text(encoding="utf-8")
    start = src.index("    resumed = False")
    end = src.index("# FULFILLMENT", start)
    block = src[start:end]
    # ⛔ COMMENTS ARE STRIPPED, AND THIS SEAL NEEDED IT IMMEDIATELY.
    #
    # The first version matched the raw slice, and the comments EXPLAINING the fix quote the
    # defect verbatim — `"APPROVED" if req.decision == ...` appears in the prose that describes
    # why it was removed. So the seal went red against the fixed code, flagging its own
    # explanation.
    #
    # That is the instrument and the subject sharing a surface: a check matching a STRING cannot
    # tell code from the commentary about code, and the better a fix is documented the more
    # likely it is to trip. Strip to executable lines and the assertions are about behaviour
    # again.
    return "\n".join(
        ln for ln in block.splitlines() if not ln.lstrip().startswith("#")
    )


def test_the_resume_block_is_where_we_think_it_is():
    """THE FLOOR. Every assertion slices this block; a rename would raise rather than fail, and
    an error in a seal reads as a broken test rather than as a missing guard."""
    block = _resume_block()
    assert "/approve" in block, "the slice does not contain the resume call"
    assert len(block) > 400, "the sliced block is implausibly short"


def test_ANY_WORKFLOW_BACKED_TASK_RESUMES_not_only_workflow_ack():
    """GAP 1. The condition is the workflow_id, not the species."""
    block = _resume_block()
    assert 'match.get("kind") == "workflow_ack"' not in block, (
        "resume is still gated on the SPECIES. Every other kind that suspends a definition is "
        "disposed in the projection while the workflow is never told — the definition stays "
        "suspended forever with the task showing resolved."
    )
    assert 'if match.get("workflow_id")' in block, (
        "resume is not keyed on workflow_id, which is the fact that decides whether some "
        "definition is suspended on this task"
    )


def test_THE_DECLARED_VERB_SURVIVES_and_is_not_collapsed():
    """GAP 2. `concurred` must not arrive as REJECTED."""
    block = _resume_block()
    assert '"APPROVED" if' not in block, (
        "the verb is still collapsed to two words before it reaches the runtime. `concurred` "
        "arrives as REJECTED because it is not the string 'approved', and a chaining row on "
        "{outcome: concurred} matches nothing forever."
    )
    assert "status = req.decision" in block, (
        "the declared verb is not passed through intact"
    )


def test_THE_VERB_IS_STILL_GATED_which_is_what_makes_pass_through_safe():
    """THE CONTROL, and it is the one that keeps this from being a widening.

    Removing the collapse is only safe because `validate_decision` already refuses a verb the
    species does not declare. If that gate were ever removed, this change would turn an
    undeclared-but-narrow surface into an undeclared-and-wide one — so the seal asserts the gate
    exists and runs BEFORE the resume block.
    """
    src = _GW.read_text(encoding="utf-8")
    gate = src.index("human_tasks.validate_decision")
    resume = src.index("    resumed = False")
    assert gate < resume, (
        "validate_decision no longer runs before the resume block — the verb now reaches the "
        "runtime ungated, and passing it through stops being safe"
    )


def test_THE_STATUS_SENT_IS_THE_ONE_THE_HANDLER_RECEIVES():
    """A pass-through that re-derived the status between assignment and send would satisfy every
    assertion above while shipping the collapse one line lower. Asserted against the payload."""
    block = _resume_block()
    payload = re.search(r'json=\{[^}]*\}', block, re.S)
    assert payload, f"could not find the resume payload in the block:\n{block[:400]}"
    assert '"status": status' in payload.group(0), (
        f"the payload does not send the resolved `status` variable: {payload.group(0)}"
    )


def test_A_TASK_WITH_NO_WORKFLOW_IS_NOT_RESUMED():
    """The other direction. A projection row with no workflow_id has no suspended definition, and
    posting an approve for one would be a call about a workflow that does not exist."""
    block = _resume_block()
    assert 'if match.get("workflow_id")' in block, "the guard that skips non-workflow tasks is gone"
