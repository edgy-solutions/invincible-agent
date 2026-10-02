"""AN ANSWER DESCENDS FROM THE ASK IT ANSWERED — WHEN IT REALLY IS ONE.

The rail shows two cards for one exchange: the ask, then the answer, unrelated. Collapsing
them into one item that transitions in place needs a link, and the link needs a producer —
`derived_from_artifact_id` has been on the bundle, on the writer, and read by the projector
(`[(a)-[:DERIVED_FROM]->(d) | d.id]`) the whole time, hardcoded to `None`. Everything existed
except the one line that sets it.

THE CLIENT IS THE ONLY PARTY THAT KNOWS. The server cannot infer which card a person acted on:
two asks can be open, and adjacency is not lineage — that is precisely the rule cortex's own
collapse seal enforces from the other side. So the client says, and the server checks.

WHY CHECKING MATTERS MORE HERE THAN FOR A USUAL UNTRUSTED FIELD. The writer links with
`MERGE (parent:AnswerArtifact {id: $parent_id})`, which CREATES the node when the id is
unknown. An unguarded field therefore does not merely record a wrong parent — it **conjures an
AnswerArtifact into the provenance graph by being named**, and the rail then folds two cards
together on a lineage nobody produced. A fabricated ancestor is worse than a missing one.

THE CHECK WAS STRUCTURAL AND IS NOW TWO CHECKS — corrected here 2026-09-27, because this
paragraph said "structural, NOT a lookup" and that sentence would have gone on reading as the
current rule. The claim is honoured when the turn CARRIES an answer (a pick in `bound_slots`, or
typed words in `spoken_answer`) — still structural — and ALSO when it carries prose naming an
artifact the graph confirms is the caller's, which is a lookup. A turn with neither answer nor
prose is an ordinary question, and an ordinary question does not descend from an ask.

The widening exists for HAZ-1003 and is NOT shared with the pre-resolved route, which still
requires a carried answer. `iagent_pure.lineage_claim` holds the rule;
`test_a_prose_turn_keeps_its_lineage_and_not_the_route.py` seals it. This file keeps the wire,
the writer's hop, and the local wiring.

Run: uv run --frozen pytest tests/routing/test_ask_to_answer_lineage.py -v
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

_GW = (_REPO / "src" / "iagent" / "gateway.py").read_text(encoding="utf-8")
_WRITER = (_REPO / "src" / "iagent" / "answer_artifact_writer.py").read_text(encoding="utf-8")


# ── the wire ────────────────────────────────────────────────────────────────

def test_the_client_can_name_the_ask_it_is_answering():
    from iagent.gateway import InterviewRequest

    assert "answering_artifact_id" in InterviewRequest.model_fields


def test_absent_parses_as_None_not_empty():
    from iagent.gateway import InterviewRequest

    assert InterviewRequest(message="q", session_id="s").answering_artifact_id is None


def test_the_field_is_named_as_a_CLAIM_not_a_conclusion():
    """`answering_artifact_id` is what the caller asserts; `derived_from_artifact_id` is what
    the server concluded. Two names because the second is the first AFTER a check, and a
    single name would make the check look like a rename."""
    from iagent.gateway import InterviewRequest

    assert "derived_from_artifact_id" not in InterviewRequest.model_fields, (
        "the wire field must not borrow the conclusion's name"
    )


# ── the guard ───────────────────────────────────────────────────────────────

def _guard_window() -> str:
    """The guard's text, bounded by the CODE'S OWN LANDMARKS rather than by a byte count.

    It used to be `i - 1200 : i + 900`. On 2026-09-27 the guard grew a second gate and the
    comment explaining why, the refusal warning slid past the +900 mark, and
    `test_the_refusal_is_audible` redded — not because the refusal had gone, but because the
    arm could no longer SEE it. That red was the lucky direction. An absence assertion keyed to
    the same window would have gone QUIET on exactly the same edit, and a seal that stops
    reaching its subject reports success.

    So both ends are derived: from the first predicate of the gate to the route lookup that
    closes it. If either landmark is renamed this raises, which is the correct failure — a
    window that cannot find its own edges must not silently return a shorter one.
    """
    start = _GW.index("_answers_something = ")
    end = _GW.index("_pre_resolved = ", start)
    return _GW[start:end]


def test_lineage_requires_the_turn_to_carry_an_answer():
    w = _guard_window()
    assert "bool(request.bound_slots) or bool(request.spoken_answer)" in w, (
        "the claim is being honoured without checking that this turn answers anything"
    )


def test_both_answer_shapes_count():
    """A pick and a typed reply are both answers. Accepting only BIND would silently drop
    lineage for every RESPEAK — the case with no menu, which is the harder one to follow."""
    w = _guard_window()
    assert "request.bound_slots" in w and "request.spoken_answer" in w


def test_the_honoured_id_IS_THE_RULES_CONCLUSION_AND_NOT_THE_CLAIM():
    """⛔ THIS ARM USED TO READ A BRANCH THAT NO LONGER EXISTS HERE, and the red it threw on
    2026-09-27 is the correct one to have thrown.

    It was `test_an_unanswered_turn_gets_no_lineage`, and it asserted `elif not _carries_prose:`
    appeared in the gate — the inline spelling of the floor. The rule then moved to
    `iagent_pure.lineage_claim` precisely so a seal could call it instead of matching its text,
    and the branch this arm was reading stopped being in gateway.py at all. Re-asserting the
    floor here would have made THIS file the mirror.

    So the subject narrowed to the hop that is genuinely local and that a pure-function seal
    cannot see: the id written to the bundle is the rule's CONCLUSION, never the caller's claim.
    The floor itself — a turn that answers nothing and says nothing gets no lineage — is held by
    `test_A_TURN_THAT_ANSWERS_NOTHING_AND_SAYS_NOTHING_IS_REFUSED_WITHOUT_A_GRAPH_READ` in
    `test_a_prose_turn_keeps_its_lineage_and_not_the_route.py`, against the real function.
    """
    w = _guard_window()
    assert "lineage_is_honoured(" in w, (
        "the gate is deciding lineage inline again, so the decision this arm follows has no "
        "single address and the floor's seal is measuring a function nothing calls"
    )
    assert "if _lineage_honoured else None" in w, (
        "the honoured id is no longer gated on the lineage decision at all"
    )
    assert "request.answering_artifact_id or None) if" in w, (
        "the id is no longer taken from the request under the decision — if the claim is being "
        "copied through by some other route, the decision is decorative"
    )


def test_the_refusal_is_audible():
    """A silently-dropped claim looks identical to a client that never sent one, and the two
    need different fixes."""
    w = _guard_window()
    assert "REFUSED" in w and "logger.warning" in w


def test_the_guarded_value_is_what_reaches_the_bundle():
    """The guard is worth nothing if the raw request field is what gets written."""
    i = _GW.index('"derived_from_artifact_id": ')
    line = _GW[i:_GW.index("\n", i)]
    assert "_answering_artifact_id" in line, f"the bundle takes an unguarded value: {line!r}"
    assert "request.answering_artifact_id" not in line


# ── the hop that already existed, pinned so it cannot rot ───────────────────

def test_the_writer_still_creates_the_edge():
    assert "MERGE (a)-[:DERIVED_FROM]->(parent)" in _WRITER


def test_the_writer_only_links_when_there_is_a_parent():
    """`if bundle.derived_from_artifact_id:` — without it, every ordinary answer would MERGE
    a parent node with id None."""
    i = _WRITER.index("MERGE (a)-[:DERIVED_FROM]->(parent)")
    assert "if bundle.derived_from_artifact_id:" in _WRITER[max(0, i - 600):i]


def test_the_MERGE_that_can_fabricate_is_documented_at_the_guard():
    """The reason the guard exists lives where the guard is, not only here. A future reader
    relaxing the check must be able to see what it is preventing."""
    w = _guard_window()
    assert "MERGE" in w and "CREATES" in w


def test_the_bundle_field_reaches_the_writer():
    """The last hop. It was already wired — the value was simply always None.

    BY AST, AND IT USED TO BE BY SUBSTRING. The old form matched the literal
    `derived_from_artifact_id=_artifact_bundle[`, which pinned the LOCAL VARIABLE'S NAME
    rather than the hop. Extracting the write into `_dispatch_answer_artifact` on
    2026-09-08 renamed that local to `bundle` and this went red with the behaviour
    completely intact — a check reading a string where the property is a data flow. The
    same family as a docstring lint flagging the comment that explains the fix.

    What actually matters is unchanged and is what is asserted now: the
    `AnswerArtifactBundle` is constructed with `derived_from_artifact_id` taken by
    subscript from the bundle dict, whatever that dict is called. Dropping the keyword,
    or hardcoding it to None, still goes red.
    """
    import ast
    call = next(
        (n for n in ast.walk(ast.parse(_GW))
         if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "AnswerArtifactBundle"),
        None,
    )
    assert call is not None, "the writer's bundle is no longer constructed by that name"
    kw = next((k for k in call.keywords if k.arg == "derived_from_artifact_id"), None)
    assert kw is not None, (
        "AnswerArtifactBundle is built without derived_from_artifact_id — the lineage edge "
        "cannot be created for any answer"
    )
    assert isinstance(kw.value, ast.Subscript), (
        f"the lineage id is not read from the bundle: {ast.unparse(kw.value)}"
    )
    assert ast.unparse(kw.value).endswith("['derived_from_artifact_id']"), ast.unparse(kw.value)
