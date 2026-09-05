"""THE QUESTION A PERSON READS IS THE QUESTION THEY ASKED — BYTE FOR BYTE.

TWO COMPOSERS, AND THEY COMPOUNDED INTO ONE STRING NOBODY TYPED.

**Plan time.** `b.DecomposeQuery` writes each task's `sub_query` freely, and it paraphrases.
Measured 2026-09-05: *"what is the capability path"* came back as *"Explain what a capability
path is, including its purpose and typical usage within system architecture or capability
modeling."* The classifier was handed a GLOSSARY question and honestly refused it at 0.22 — no
verb in this system explains what a term means — and the card read "no verb classified". Every
gate and every classifier downstream behaved correctly **on a question nobody asked**. That is
the confident-wrong shape moved upstream of every guard: the guards work, on the wrong input.

**RESPEAK.** `resolve_ask` then appended `" (<slot>: <answer>)"` to that same paraphrase, and
the result — `Provide the current funding status. (program_id: meridian)` — is what appeared on
the rail. Machine syntax, on top of a rewrite, presented as the user's question.

THE RULING (2026-09-05): **nothing is composed.** The rail shows the user's phrase; the answer
is displayed beneath it as `spoken -> resolved`, three facts as three facts, because there is no
join. What the RESOLVER receives is a separate question from what the RAIL displays — it gets
the answer as a value to resolve for a named slot, with the phrase as context. An implementation
input must never become the thing a person reads.

ENFORCED, NOT INSTRUCTED. A model told not to paraphrase still paraphrases on the draws nobody
watches. The plan's `sub_query` is overwritten with the user's query after the call; the model's
wording is KEPT under `model_phrasing`, because how the planner read the question is a real
signal — it is simply not the question.

Run: uv run --frozen pytest tests/routing/test_nothing_composes_the_question.py -v
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

_EO = (_REPO / "agent_fleet" / "ontology_service" / "main.py").read_text(encoding="utf-8")
_SUP = (_REPO / "src" / "iagent" / "defs" / "dynamic_supervisor.py").read_text(encoding="utf-8")
_GW = (_REPO / "src" / "iagent" / "gateway.py").read_text(encoding="utf-8")


# ── RESPEAK composes nothing ────────────────────────────────────────────────

def test_respeak_returns_the_phrase_unchanged():
    """THE 10:45 ARTIFACT. `Provide the current funding status. (program_id: meridian)` was
    a question nobody asked, rendered as though they had."""
    from iagent_pure.slot_disposition import RESPEAK, resolve_ask

    card = {"slot": "program_id", "sub_query": "what is the funding status",
            "accepted_slots": {}, "options": []}
    r = resolve_ask(card, "meridian")
    assert r.action == RESPEAK
    assert r.query == "what is the funding status", (
        f"RESPEAK is composing again: {r.query!r}"
    )


def test_the_answer_survives_as_a_FIELD():
    """Dropping the answer would be the opposite failure — the resolver needs it. It travels
    beside the phrase, not inside it."""
    from iagent_pure.slot_disposition import resolve_ask

    r = resolve_ask({"slot": "program_id", "sub_query": "what is the funding status",
                     "accepted_slots": {}, "options": []}, "meridian")
    assert r.spoken_answer == "meridian"
    assert r.slot == "program_id"


def test_no_machine_syntax_reaches_the_phrase():
    """Asserted on the SHAPE, not on one fixture: no parenthesised `slot: value` anywhere in
    what gets re-issued, whatever the slot or answer happen to be."""
    from iagent_pure.slot_disposition import resolve_ask

    for slot, answer in (("program_id", "meridian"), ("capability_id", "Integration Platform")):
        r = resolve_ask({"slot": slot, "sub_query": "what is the funding status",
                         "accepted_slots": {}, "options": []}, answer)
        assert not re.search(r"\(\s*\w+\s*:", r.query), f"composed syntax in {r.query!r}"
        assert answer not in r.query, "the answer was concatenated into the phrase"


def test_a_menu_pick_still_BINDS_and_carries_no_phrase():
    """BIND was already correct and must stay so — the pick rides as a parameter and the
    query is empty, which is why a pick is never re-parsed."""
    from iagent_pure.slot_disposition import BIND, resolve_ask

    r = resolve_ask(
        {"slot": "capability_id", "sub_query": "what is the capability path",
         "accepted_slots": {}, "options": [{"value": "C7", "label": "Integration Platform"}]},
        "C7",
    )
    assert r.action == BIND and r.query == "" and r.slots["capability_id"] == "C7"


# ── plan time composes nothing ──────────────────────────────────────────────

def _plan_window() -> str:
    i = _EO.index("plan = await b.DecomposeQuery(")
    return _EO[i:i + 2600]


def test_the_plan_overwrites_every_task_sub_query_with_the_users_query():
    w = _plan_window()
    assert '_task["sub_query"] = request.query' in w, (
        "the planner's paraphrase is reaching the classifier again"
    )


def test_the_overwrite_is_unconditional():
    """A guarded overwrite — "only when it looks rewritten" — needs a judgement about what
    counts as a rewrite, and that judgement is the thing that fails. Assign always."""
    w = _plan_window()
    i = w.index('_task["sub_query"] = request.query')
    preceding = w[:i].rstrip().splitlines()[-1].strip()
    assert not preceding.startswith("if "), (
        f"the overwrite is conditional on {preceding!r} — it must be unconditional"
    )


def test_the_models_phrasing_is_kept_but_not_as_the_query():
    """How the planner READ the question is real signal. It is simply not the question, and
    discarding it would trade one silence for another."""
    w = _plan_window()
    assert '_task["model_phrasing"] = _written' in w


def test_the_rewrite_is_visible_when_it_happens():
    """A silent correction hides how often the planner paraphrases, which is the number that
    says whether the prompt itself needs work."""
    w = _plan_window()
    assert "REWRITTEN" in w


# ── the classifier's input and the artifact's question ──────────────────────

def test_the_routing_query_is_the_phrase_or_the_users_query_and_nothing_else():
    """`sub_query or config.user_query` — two byte-equal sources, no third that composes."""
    i = _SUP.index("routing_query = ")
    line = _SUP[i:_SUP.index("\n", i)]
    assert line.strip() == "routing_query = sub_query or config.user_query", (
        f"the routing query is being built rather than chosen: {line!r}"
    )


def test_question_text_on_the_artifact_is_the_users_message():
    """What a reader sees on the rail. A composed value here is the defect wearing its most
    visible costume."""
    i = _GW.index('"question_text": ')
    line = _GW[i:_GW.index("\n", i)]
    assert line.strip() == '"question_text": user_query,', (
        f"question_text is composed: {line!r}"
    )


def test_no_fstring_builds_a_query_from_a_slot_anywhere_in_the_pure_layer():
    """THE CLASS, not the instance. Any f-string interpolating a slot name and a value into
    something called a query is this defect returning under a new name."""
    pure = (_REPO / "src" / "iagent_pure" / "slot_disposition.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(pure)):
        if not isinstance(node, ast.JoinedStr):
            continue
        rendered = "".join(
            v.value for v in node.values if isinstance(v, ast.Constant)
        )
        assert not re.search(r"\(\s*$|\(\s*:", rendered + ":"), (
            f"an f-string is composing slot syntax at line {node.lineno}: {rendered!r}"
        )
