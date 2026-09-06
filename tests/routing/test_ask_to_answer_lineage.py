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

THE CHECK IS STRUCTURAL, NOT A LOOKUP: the claim is honoured only when the turn actually
CARRIES an answer — a pick in `bound_slots`, or typed words in `spoken_answer`. A turn with
neither is an ordinary question, and an ordinary question does not descend from an ask.

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
    i = _GW.index("_answers_something = ")
    return _GW[max(0, i - 1200):i + 900]


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


def test_an_unanswered_turn_gets_no_lineage():
    w = _guard_window()
    assert "if _answers_something else None" in w


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
    """The last hop. It was already wired — the value was simply always None."""
    assert re.search(r"derived_from_artifact_id=_artifact_bundle\[", _GW)
