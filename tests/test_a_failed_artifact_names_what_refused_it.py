"""A failed artifact carries the verb that was refused and the gate that refused it.

WHY IT EXISTS, and the cost is the argument. `artifact-2-1789404372153` was written `status:
failed` in 191ms with its entire `resolved_intent` being::

    {"refused_slots": [], "accepted_slots": {"program_id": "NP-MERIDIAN"}}

**The slot that was bound, and not the verb that refused it.** Three reads of the artifact store
to learn that `mesh:finProgramBrief` had been excluded on an **arity** gate immediately after an
elicitation supplied its one slot — and the answer sat in `routing.excluded[]` the whole time.

**NOTHING WAS LOST. IT WAS UNFINDABLE FROM WHERE A READER STARTS.** The field naming the ACTION
had been dropped from the field recording the INTENT, so a reader who opened `resolved_intent` —
which is the field whose name promises exactly that — saw slots and no verb.

> **A failure recorded honestly where nobody reads is a success to everyone who looks.**

Three shapes of that class in one day: the **log** (`registered 3/3` against a dead mint), the
**column** (`status: failed` rendering as a blank card), and the **wrong column** (this one).
Every one produced a surface that looked fine over something that did not happen, and every one
was found by reading the row rather than the screen.

Run: uv run --frozen pytest tests/test_a_failed_artifact_names_what_refused_it.py -v
"""
from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_GW = _REPO / "src" / "iagent" / "gateway.py"


def _slot_branch() -> str:
    """The slot-materialisation branch, sliced from source.

    Read as source rather than executed: the writer needs a live outcome, a Dagster
    materialisation and a database. What these assert is the SHAPE of what gets written, which is
    the part a diagnosing reader depends on.

    Comments are stripped — the block's own commentary quotes the defect verbatim, and a check
    matching a string cannot tell code from the explanation of code. That was learned on the
    gateway resume seal, which went red against its own fix.
    """
    src = _GW.read_text(encoding="utf-8")
    i = src.index("    if outcome.slots_mat is not None:")
    j = src.index("if outcome.kind == direct_dispatch.ABSTAIN", i)
    return "\n".join(
        ln for ln in src[i:j].splitlines() if not ln.lstrip().startswith("#")
    )


def test_the_slot_branch_is_where_we_think_it_is():
    """THE FLOOR. A rename would raise rather than fail, and an error in a seal reads as a broken
    test rather than as a missing guard."""
    b = _slot_branch()
    assert "accepted_slots" in b and "refused_slots" in b, "the slice does not contain the branch"


def test_THE_VERB_TRAVELS_WITH_THE_SLOTS():
    """THE SEAL. Without `verb_iri` a failed artifact is unattributable by construction."""
    b = _slot_branch()
    assert "verb_iri" in b, (
        "the slot branch writes slots without the verb. A failed artifact then records WHICH "
        "SLOT WAS BOUND and never WHICH VERB REFUSED IT — and `resolved_intent` is the field a "
        "reader opens precisely to learn the second."
    )
    assert "disposition" in b, (
        "no `disposition` — a reader cannot tell a refusal from a route from an ask"
    )


def test_THE_SUBJECT_TRAVELS_TOO():
    """`resolved_intent` naming an action and not the thing acted on cannot be re-dispatched from
    the artifact alone — the producer's own comment says so about the other path."""
    b = _slot_branch()
    for field in ("subject_uri", "owner_persona"):
        assert field in b, f"{field} is not carried onto the slot path"


def test_IT_SUPPLIES_RATHER_THAN_OVERWRITES():
    """THE CONTROL, and it is the difference between a fix and a regression.

    The classify path fills a FULLER intent upstream. Assigning here would overwrite it with the
    direct path's narrower view — turning a bug that loses fields on one path into a bug that
    loses them on both. `setdefault` supplies only what is absent.
    """
    b = _slot_branch()
    assert "setdefault" in b, (
        "the verb is ASSIGNED rather than supplied — this overwrites the classify path's fuller "
        "resolved_intent with the direct path's view"
    )


def test_AN_EMPTY_VALUE_IS_NOT_SUPPLIED():
    """An empty string for `verb_iri` is worse than its absence: absence reads as "this path did
    not know", while `""` reads as "the verb was the empty string" and satisfies any check that
    only asks whether the key exists."""
    b = _slot_branch()
    assert 'not in (None, "")' in b or "not in (None, '')" in b, (
        "empty values are written through — a key present with an empty value passes a "
        "key-exists check while carrying no information"
    )


def test_THE_GATE_THAT_REFUSED_IS_RECORDED_SOMEWHERE_A_READER_REACHES():
    """The exclusion reason lives in `routing.excluded[]` and that is where it belongs — but the
    artifact must carry the verb so the two can be joined.

    THIS IS THE JOIN THAT COST THE TWO HOURS. Both halves were recorded correctly and separately:
    `excluded[]` knew the gate, `resolved_intent` knew the slots, and nothing named the verb in
    the field that would have connected them.
    """
    src = _GW.read_text(encoding="utf-8")
    assert '"excluded"' in src or "'excluded'" in src, (
        "the routing record no longer carries `excluded` — the gate that refused a verb is then "
        "recorded nowhere at all, which is worse than recorded in the wrong column"
    )
