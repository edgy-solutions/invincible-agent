"""HAZ-1003: THE COMPOSER TURN KEEPS ITS ARROW AND DOES NOT GET THE ROUTE.

THE TURN. A person reads a drawn card and types a sentence about it. That turn descends from
the card on any honest reading — it is the next step of one conversation — and it carries neither
a pick in `bound_slots` nor a typed slot reply in `spoken_answer`. Until 2026-09-27 ONE predicate
decided both whether the lineage arrow was drawn and whether the ask's stored (subject, verb)
could skip routing, so honouring the arrow meant granting the route. The arrow was dropped and
the composer turn rendered as an orphan card.

WHY THE TWO GATES ARE NOT THE SAME GATE, which is the whole subject of this file:

  the ARROW      a wrong one folds two cards on a lineage nobody produced
  the ROUTE      a wrong one DISPATCHES A VERB AGAINST A SUBJECT nobody confirmed this turn

WHY THE WIDE ARM COSTS A GRAPH READ. `bound_slots` and `spoken_answer` are shapes only a client
that was SHOWN this ask's menu can produce — their presence is itself weak evidence the named ask
is real. Prose is evidence of nothing: every ordinary question carries prose, so `named + prose`
is satisfiable by any caller typing any sentence at any invented id. And the writer links with
`MERGE (parent:AnswerArtifact {id: $parent_id})`, which CREATES the node when the id is unknown.
So the prose arm requires existence AND ownership, and these arms hold that it does.

THE RULE IS CALLED, NOT MIRRORED. `iagent_pure.lineage_claim` holds the decision at module level
precisely so this file can exercise the real one. The arms below that read `gateway.py` as text
are doing the other half — proving the handler calls it and that the ROUTE is still gated on the
narrow predicate — because that wiring is the part a pure-function seal cannot see.

Run: uv run --frozen pytest tests/routing/test_a_prose_turn_keeps_its_lineage_and_not_the_route.py -v
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from iagent_pure.lineage_claim import (  # noqa: E402
    REFUSED_NOTHING_CARRIED,
    REFUSED_NOT_THE_CALLERS,
    lineage_is_honoured,
    pre_resolved_route_allowed,
)

_GW = (_REPO / "src" / "iagent" / "gateway.py").read_text(encoding="utf-8")
_RULE = (_REPO / "src" / "iagent_pure" / "lineage_claim.py").read_text(encoding="utf-8")


class _Tripwire:
    """An `ownership_ok` that RECORDS whether it was consulted.

    The count is the subject of two arms, in opposite directions: the prose arm must call it
    (or the phantom guard is decoration) and the answering arm must not (or every answer turn
    pays a graph round trip it was never meant to). A bool would answer neither.
    """

    def __init__(self, result: bool = True) -> None:
        self.calls = 0
        self.result = result

    def __call__(self) -> bool:
        self.calls += 1
        return self.result


# ─────────────────────────────────────────────────────────────────────────────────────────────
# The turn the whole change exists for
# ─────────────────────────────────────────────────────────────────────────────────────────────
def test_THE_COMPOSER_TURN_KEEPS_ITS_LINEAGE():
    """Prose about a drawn card, no pick, no typed slot answer, the artifact is the caller's."""
    owns = _Tripwire(True)
    honoured, reason = lineage_is_honoured(
        names_an_ask=True, answers_something=False, carries_prose=True, ownership_ok=owns,
    )
    assert honoured, (
        f"the composer turn's lineage was refused: {reason!r}. This is HAZ-1003 — a sentence "
        f"typed about a card the person is looking at descends from that card."
    )
    assert reason == "", "an honoured claim must carry no refusal reason to log"
    assert owns.calls == 1, (
        "the prose arm was honoured WITHOUT consulting the graph. Then the phantom guard is "
        "decoration and any caller can name any id and be believed."
    )


def test_THE_COMPOSER_TURN_DOES_NOT_GET_THE_ROUTE():
    """⛔ THE OTHER HALF, and the reason this is a split and not a widening. Same turn, and the
    question that must still answer NO: may the ask's stored (subject, verb) skip routing?"""
    assert pre_resolved_route_allowed(answers_something=False) is False, (
        "a prose turn was granted the pre-resolved route. Lineage draws an arrow; the route "
        "dispatches a verb against a subject nobody confirmed on this turn."
    )
    assert pre_resolved_route_allowed(answers_something=True) is True, (
        "the narrow arm no longer grants the route at all — this arm's negative half above "
        "would then pass with the whole feature deleted"
    )


# ─────────────────────────────────────────────────────────────────────────────────────────────
# The phantom, which is what the wide arm is paying for
# ─────────────────────────────────────────────────────────────────────────────────────────────
def test_a_prose_turn_naming_AN_ASK_THAT_IS_NOT_THE_CALLERS_IS_REFUSED():
    owns = _Tripwire(False)
    honoured, reason = lineage_is_honoured(
        names_an_ask=True, answers_something=False, carries_prose=True, ownership_ok=owns,
    )
    assert honoured is False, (
        "prose plus an id the graph will not vouch for was honoured. The writer's MERGE would "
        "then CREATE the named node — conjuring the ancestor it appears to have found."
    )
    assert reason == REFUSED_NOT_THE_CALLERS
    assert owns.calls == 1


def test_A_TURN_THAT_ANSWERS_NOTHING_AND_SAYS_NOTHING_IS_REFUSED_WITHOUT_A_GRAPH_READ():
    """The floor under the widening, and the ordering that makes the round trip affordable:
    two free predicates decide first, so an empty turn never reaches Neo4j."""
    owns = _Tripwire(True)
    honoured, reason = lineage_is_honoured(
        names_an_ask=True, answers_something=False, carries_prose=False, ownership_ok=owns,
    )
    assert honoured is False
    assert reason == REFUSED_NOTHING_CARRIED
    assert owns.calls == 0, (
        "an empty turn paid for a graph read. The check is ordered last on purpose; moving it "
        "first would put a Neo4j round trip on turns that cannot be honoured anyway."
    )


def test_the_answering_arm_DOES_NOT_PAY_FOR_THE_GRAPH_READ():
    """⚠ THIS PINS A NAMED HOLE, NOT A GUARANTEE — and it is here so that closing the hole is a
    deliberate act with a red to change rather than a silent one.

    An answering turn is honoured WITHOUT the existence check, exactly as before 2026-09-27.
    That is a pre-existing gap in the same guard: adding the check would refuse valid lineage in
    any window where the ask's own write has not landed by the time the answer arrives, and
    whether that race exists on this path is UNMEASURED. Measure it, then close it — and when
    you do, this arm is the one that says so.
    """
    owns = _Tripwire(False)
    honoured, reason = lineage_is_honoured(
        names_an_ask=True, answers_something=True, carries_prose=True, ownership_ok=owns,
    )
    assert honoured is True and reason == ""
    assert owns.calls == 0, (
        "the answering arm now consults the graph. If that was deliberate, the race named in "
        "this docstring must have been MEASURED first — say where, and rewrite this arm."
    )


def test_NAMING_NO_ASK_IS_NOT_A_REFUSAL():
    """An ordinary question names no ask. That is the common shape, not a violation, and giving
    it a refusal reason would put a warning on the busiest path in the system — which is how a
    log line stops being read at all."""
    honoured, reason = lineage_is_honoured(
        names_an_ask=False, answers_something=False, carries_prose=True,
        ownership_ok=_Tripwire(True),
    )
    assert honoured is False
    assert reason == "", (
        f"an ordinary question produced the refusal reason {reason!r}, which would be logged "
        f"as a warning on every turn that simply asks something"
    )


# ─────────────────────────────────────────────────────────────────────────────────────────────
# The wiring a pure-function seal cannot see
# ─────────────────────────────────────────────────────────────────────────────────────────────
def _gate_window() -> str:
    """Derived from the code's own landmarks, never a byte count. A sibling arm in
    `test_ask_to_answer_lineage.py` lost sight of its subject on this very edit because its
    window was `+900` characters wide, and a window that silently shortens turns an absence
    assertion into a quiet pass."""
    start = _GW.index("_answers_something = ")
    end = _GW.index("_chain_slots = ", start)
    return _GW[start:end]


def _prose(text: str) -> str:
    """Source text with adjacent-string-literal joins closed and whitespace collapsed.

    A raw substring search for a wrapped message is a matcher whose reach does not cover the
    forms the shipping code is FORCED to take: both refusal reasons are long enough that any
    copy of them wraps, and it wraps wherever the copier's line length put it. Searching the
    prose instead of the wrapping is what makes the absence below mean something — and the arm
    positive-controls it against the module that really does hold the text.
    """
    return re.sub(r"\s+", " ", re.sub(r'"\s*\n\s*"', "", text))


def test_the_gateway_CALLS_the_rule_and_does_not_restate_it():
    w = _gate_window()
    assert "lineage_is_honoured(" in w, "the handler is deciding lineage on its own again"
    gw, rule = _prose(_GW), _prose(_RULE)
    for reason in (REFUSED_NOTHING_CARRIED, REFUSED_NOT_THE_CALLERS):
        frag = _prose(reason)[:60]
        assert frag in rule, (
            f"POSITIVE CONTROL FAILED: {frag!r} is not findable even in lineage_claim.py, so "
            f"this matcher cannot detect the copy it is looking for and its absence below "
            f"proves nothing"
        )
        assert frag not in gw, (
            f"the refusal text {frag!r} is spelled in gateway.py as well as in "
            f"lineage_claim.py. Two copies of a rule's own words is the shape a mirror takes "
            f"before it becomes a mirror of the logic."
        )


def test_THE_ROUTE_IS_GATED_ON_THE_NARROW_RULE_AND_NOT_ON_THE_HONOURED_ID():
    """The route must name its own predicate rather than inherit the lineage gate through
    `_answering_artifact_id`, or the day anyone widens the arrow again the route follows for
    free, on that same commit, with nothing red."""
    i = _GW.index("_pre_resolved = (")
    call = _GW[i:_GW.index("\n    if _pre_resolved", i)]
    assert "pre_resolved_route_allowed(answers_something=" in call, (
        f"the route's gate is no longer the narrow rule: {call!r}"
    )
    assert "_lineage_honoured" not in call, (
        "the route is reading the LINEAGE decision — the two gates have been re-joined"
    )


def test_THE_CHAIN_SLOTS_FOLLOW_THE_ARROW_AND_NOT_THE_ROUTE():
    """The dispatch's requirement, and it is not the same claim as the arrow's. What the chain
    has already bound is read from the ask the arrow points at, so a prose turn keeps it; a turn
    whose lineage was refused must not see it, and `_answering_artifact_id` is None there."""
    i = _GW.index("_chain_slots = ")
    line = _GW[i:_GW.index("\n", i)]
    assert "_answering_artifact_id" in line, (
        f"chain slots are not read from the honoured id: {line!r}"
    )
    assert "request.answering_artifact_id" not in line, (
        "chain slots are being read from the CLAIM rather than the conclusion — a refused "
        "lineage would still hand over another caller's bound values"
    )


def _ownership_check_code() -> str:
    """`_artifact_is_the_callers`'s CODE, with its own docstring removed.

    ⛔ THE FIRST FORM OF THIS ARM READ THE DOCSTRING. It searched the function's source text for
    `MERGE`, and redded — on the paragraph that explains WHY the check must never MERGE. Same
    family as the sibling in `test_ask_to_answer_lineage.py` that pinned a local variable's name:
    a check reading a string where the property is the code. The prose is free to name the hazard;
    the statements are the subject.
    """
    import ast
    fn = next(
        n for n in ast.walk(ast.parse(_GW))
        if isinstance(n, ast.FunctionDef) and n.name == "_artifact_is_the_callers"
    )
    body = fn.body[1:] if ast.get_docstring(fn) else fn.body
    assert body, "the ownership check has no code left, only prose"
    return "\n".join(ast.unparse(stmt) for stmt in body)


def test_the_ownership_check_REUSES_THE_ROUTE_LOOKUPS_OWN_CYPHER():
    """The ownership edge is the rule that authorizes (see `_PRE_RESOLVED_CYPHER`'s comment),
    and a second spelling of it is a second thing to keep correct. One constant, two readings."""
    code = _ownership_check_code()
    assert "_PRE_RESOLVED_CYPHER" in code, (
        "the existence check has grown its own Cypher. The ownership edge must not be spelled "
        "twice — it is an authorization surface, and the copies will drift."
    )
    assert "MERGE" not in code, (
        "an existence CHECK is writing: MERGE creates the node whose existence is in question, "
        "which is the exact fabrication this check was added to prevent"
    )
    assert "return rec is not None" in code, (
        "the check no longer decides on whether a row came back. Deciding on the row's CONTENT "
        "would refuse a real artifact whose ask predates subject capture — a legitimate parent."
    )


def test_the_ownership_check_REFUSES_ON_EVERY_UNCERTAINTY():
    """A graph that is down, slow or wrong must not widen the gate. The failure direction is the
    whole reason this is a callable and not a truthy field: `except` returns False, so an
    unreachable Neo4j refuses the lineage claim instead of waving it through."""
    code = _ownership_check_code()
    assert "except Exception" in code and "return False" in code, (
        f"no refusing failure path in the ownership check:\n{code}"
    )
    tail = code[code.index("except Exception"):]
    assert "return False" in tail, (
        "the exception path no longer returns False — an unreachable graph would fall through "
        "to the truthy return and HONOUR an unverified lineage claim"
    )
