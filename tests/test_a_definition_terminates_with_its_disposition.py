"""A definition terminates with its last disposition, or chaining has nothing to chain on.

WHY THIS EXISTS. `_run_definition` returned `status: "COMPLETED"` — a CONSTANT. Every definition
looked identical from outside, so an ADR-0039 decision table selecting the NEXT definition from
the outcome of the one that just ran could only ever match one row.

**UNDER §4.3.7 THAT IS THE DIFFERENCE BETWEEN "A CONCURRENCE HAPPENED" AND "THE CONCURRENCE WAS
GIVEN."** The executor proceeds past `human_await` unconditionally, so a `not_concurred` read
exactly like a concurrence. **Enforcing order while ignoring outcome is §4.3.7 satisfied on paper
and defeated in fact** — which is why `safety_acceptance_with_concurrence` is being deleted in
favour of one act per definition plus chaining.

THE FIELD IS ADDITIVE. `status` is the RUN's fate — did the executor finish. `outcome` is the
WORK's. Collapsing them would make "the workflow errored" and "the human said no" the same value,
which is the conflation the whole disposition rail exists to prevent.

AND THE FIRST IMPLEMENTATION READ A KEY THAT DOES NOT EXIST. It derived the outcome from
`approval["decision"]`; the approve handler's payload is `status`, `comments`, `task_id`,
`acted_by`. **That was not a crash — it made `outcome` permanently `None`**, indistinguishable
from "this definition disposes nothing", and a chaining table would have matched no row for every
definition forever. `test_the_outcome_can_actually_be_NON_null` is the control that catches it,
and it is the one a green suite would otherwise never have needed.

Run: uv run --frozen pytest tests/test_a_definition_terminates_with_its_disposition.py -v
"""
from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_MAIN = _REPO / "agent_fleet" / "restate_analyst" / "main.py"


def _executor_source() -> str:
    """`_run_definition`'s body, sliced from the file.

    Read as SOURCE rather than executed: the function is a Restate workflow handler needing a
    live `ctx`, a durable promise and a registered service. A test that stood all that up would
    be testing Restate; this asserts the shape of what the executor returns, which is the part
    the decision rail depends on.
    """
    src = _MAIN.read_text(encoding="utf-8")
    start = src.index("async def _run_definition")
    end = src.index("@bpmn_workflow.main()", start)
    return src[start:end]


def test_the_executor_is_where_we_think_it_is():
    """THE FLOOR. Every assertion below slices this function; if it were renamed the slice would
    raise rather than fail, and an error reads as a broken test rather than a missing guard."""
    body = _executor_source()
    assert "step_results" in body, "the executor no longer returns step_results — slice is wrong"
    assert len(body) > 500, "the sliced body is implausibly short"


def test_THE_TERMINAL_ENVELOPE_CARRIES_AN_OUTCOME():
    """THE SEAL. Without this field a decision table has nothing to match on."""
    body = _executor_source()
    assert re.search(r'"outcome":', body), (
        "the executor's return carries no `outcome` — every definition terminates identically, "
        "so an ADR-0039 chaining table can only ever match one row"
    )
    assert re.search(r'"outcome_step_id":', body), (
        "no `outcome_step_id` — a reader cannot tell WHICH step disposed, so a definition with "
        "two human steps produces an outcome nobody can attribute"
    )


def test_THE_OUTCOME_CAN_ACTUALLY_BE_NON_NULL():
    """THE CONTROL MY OWN BUG NEEDED, and the reason it is a separate test.

    The first implementation read `approval["decision"]`, which the approve handler does not
    produce. `outcome` was then `None` for every definition, forever — and every other assertion
    in this file still passed, because the FIELD was present. A seal checking only that the key
    exists cannot tell a working derivation from a permanently-null one.

    So this asserts the executor reads a key the resolve site actually WRITES, by checking both
    ends against each other rather than either alone.
    """
    body = _executor_source()
    src = _MAIN.read_text(encoding="utf-8")

    # What the approve handler actually puts in the promise payload.
    payload = src[src.index("approval_payload = {"):]
    payload = payload[:payload.index("}")]
    written = set(re.findall(r'"(\w+)":', payload))
    assert written, "could not parse the approval payload — this seal proves nothing"

    read = set(re.findall(r'\.get\("(\w+)"\)\s*(?:if _disposing|$)', body))
    read |= set(re.findall(r'or \{\}\)\.get\("(\w+)"\)', body))
    assert read, "could not find what the executor reads off the approval"

    assert read & written, (
        f"the executor derives `outcome` from {sorted(read)} but the approve handler writes "
        f"{sorted(written)} — no overlap. `outcome` would be None for every definition forever, "
        f"which is indistinguishable from 'this definition disposes nothing'."
    )


def test_STATUS_IS_NOT_COLLAPSED_INTO_OUTCOME():
    """`status` stays the RUN's fate. Merging them makes 'the executor errored' and 'the human
    said no' the same value — the conflation the disposition rail exists to prevent."""
    body = _executor_source()
    assert '"status": "COMPLETED"' in body, (
        "`status` was repurposed to carry the disposition. It reports whether the executor "
        "finished; `outcome` reports what was decided. Two facts, two fields."
    )


def test_THE_OUTCOME_COMES_FROM_THE_LAST_DISPOSING_STEP_not_the_last_step():
    """A definition ending in a dispatch or a notification must still terminate with the human's
    verb. Taking 'the last step' would make the outcome depend on trailing bookkeeping nobody
    thinks of as a decision."""
    body = _executor_source()
    assert "_disposing" in body, "no disposing-step filter — the outcome tracks the last step"
    assert 'r.get("kind") == "human_await"' in body, (
        "the disposing filter does not select human_await steps by kind"
    )
    assert "_disposing[-1]" in body, "the LAST disposing step is not the one taken"


def test_NO_DISPOSITION_YIELDS_NONE_rather_than_a_default():
    """An honest absence. A default here would make a chaining table match a row for a definition
    that decided nothing — the silent-fallback shape, on the rail that selects what happens next."""
    body = _executor_source()
    assert "if _disposing else None" in body, (
        "a definition that disposes nothing does not yield None — a chaining table would match "
        "on a manufactured value"
    )
