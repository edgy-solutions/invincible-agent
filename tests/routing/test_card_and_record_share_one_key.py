"""THE CARD AND THE ROUTING RECORD MUST PICK THE SAME SUBTASK, BY THE SAME FUNCTION.

THEY HAVE NOW DIVERGED TWICE, IN OPPOSITE DIRECTIONS:

    2026-09-04 21:55   card right, record wrong.  The record took the first materialization,
                       and a 30-second timeout finishes sooner than a 44-second success, so
                       the FAILING subtask won the record by construction.

    2026-09-05 12:17   record right, card wrong.  The record was fixed to take the first
                       MATCHED decision. The card still took the first result carrying an
                       `output_uri` — and Engine A's generalist fallback stamps
                       `output_uri: mesh#AgentResponse` on every answer it gives
                       (restate_analyst/main.py:408, :3074). So a `no_match` result qualified,
                       landed first, and the card rendered a fabricated entitlement story
                       while the record correctly named Engine F.

THE SECOND WAS MY ERROR AND ITS SHAPE IS THE LESSON. I argued the two keys were already the
same, "because only a matched route produces an output_uri". That premise was never checked
against Engine A, and it is false. **Two functions that agree in a docstring are not one rule.**

So the rule lives in `iagent_pure.primary_selection.pick_primary`, both sides call it with
their own accessor, and this file asserts they call THAT — not that they happen to agree on a
fixture, which is exactly the evidence that misled me.

Run: uv run --frozen pytest tests/routing/test_card_and_record_share_one_key.py -v
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

from iagent_pure.primary_selection import MATCHED, pick_primary  # noqa: E402

_SUP = (_REPO / "src" / "iagent" / "defs" / "dynamic_supervisor.py").read_text(encoding="utf-8")
_GW = (_REPO / "src" / "iagent" / "gateway.py").read_text(encoding="utf-8")
_ENGINE_A = (_REPO / "agent_fleet" / "restate_analyst" / "main.py").read_text(encoding="utf-8")

_MODULE = "iagent_pure.primary_selection"
_FN = "pick_primary"


def _res(status, uri):
    return {"route_status": status, "expert_response": {"output_uri": uri}}


_FALLBACK = _res("no_match", "http://invincible-agent/mesh#AgentResponse")
_MATCH = _res("matched", "http://invincible-agent/fin#VarianceDecomposition")


# ── the three cases the dispatch named ──────────────────────────────────────

def test_fallback_first_still_renders_the_match():
    """THE 12:17 DEFECT. This is the ordering that produced the fabricated card."""
    assert pick_primary([_FALLBACK, _MATCH], lambda r: r["route_status"]) is _MATCH


def test_matched_first_renders_the_same_card():
    """Order must not change the answer — it is the tie-break, never the rule."""
    assert pick_primary([_MATCH, _FALLBACK], lambda r: r["route_status"]) is _MATCH


def test_a_fallback_alone_still_renders():
    """When nothing matched there IS no specialist answer, and the generalist's response is
    the honest thing to show. This must not manufacture a refusal."""
    assert pick_primary([_FALLBACK], lambda r: r["route_status"]) is _FALLBACK


def test_no_results_yields_None():
    assert pick_primary([], lambda r: r["route_status"]) is None


def test_a_malformed_status_cannot_take_routing_down():
    """The caller is choosing WHICH of several answers to show; an exception here loses all
    of them. Unreadable simply is not matched."""
    boom = {"x": 1}

    def _raises(_r):
        raise KeyError("route_status")

    assert pick_primary([boom, _MATCH], _raises) is boom  # degrades to first, never raises


# ── the premise that was false, pinned so it cannot be re-adopted ───────────

def test_the_generalist_really_does_stamp_an_output_uri():
    """THE FALSE PREMISE, now a test. If this ever stops being true, the old
    'first with an output_uri' shortcut becomes tempting again — and it would be wrong for a
    different reason. Pinned as a FACT about Engine A, where it lives."""
    assert "mesh#AgentResponse" in _ENGINE_A
    assert re.search(r'"output_uri":\s*"http://invincible-agent/mesh#AgentResponse"', _ENGINE_A), (
        "Engine A no longer stamps mesh#AgentResponse — this file's premise changed and the "
        "reasoning in primary_selection.py needs revisiting, not deleting"
    )


# ── both sides call the SAME function ───────────────────────────────────────

def _calls_pick_primary(src: str, fn_name: str) -> bool:
    tree = ast.parse(src)
    fn = next(
        (n for n in ast.walk(tree)
         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fn_name),
        None,
    )
    assert fn is not None, f"{fn_name} not found"
    return any(
        isinstance(n, ast.Call) and getattr(n.func, "id", "") == _FN
        for n in ast.walk(fn)
    )


def test_the_record_selector_calls_it():
    assert _calls_pick_primary(_GW, "_primary_routing_mat")


def test_the_card_selector_calls_it():
    assert _calls_pick_primary(_SUP, "generate_ui_payload")


def _imports_from_shared(src: str) -> bool:
    return any(
        isinstance(n, ast.ImportFrom)
        and (n.module or "") == _MODULE
        and any(a.name == _FN for a in n.names)
        for n in ast.walk(ast.parse(src))
    )


def test_it_is_LITERALLY_the_same_function_not_two_that_agree():
    """THE ASSERTION THIS FILE EXISTS FOR. Both sides must import the symbol from the one
    module. Two local copies that produce the same answer on today's fixtures is exactly the
    state that shipped the 12:17 defect — and it passed both sides' tests while doing it."""
    assert _imports_from_shared(_GW), "the gateway defines or copies its own rule"
    assert _imports_from_shared(_SUP), "the supervisor defines or copies its own rule"


def test_the_old_output_uri_shortcut_is_gone_from_the_card():
    """The exact loop that shipped the defect: first result with an output_uri wins."""
    i = _SUP.index("def generate_ui_payload")
    body = _SUP[i:i + 6000]
    assert 'if isinstance(expert_res, dict) and expert_res.get("output_uri"):' not in body, (
        "the card is keying on output_uri again — Engine A's fallback carries one"
    )


# ── every result carries a status to key on ─────────────────────────────────

def _result_dicts_missing_status() -> list[int]:
    """Every subtask-result construction, checked individually.

    PER SITE, NOT AS A COUNT — a floor stayed green yesterday when a key was deleted from one
    branch, which is the aggregate-floor defect inside the test written to prevent it.
    """
    missing = []
    for m in re.finditer(r'"expert_response"\s*:', _SUP):
        # walk back to the opening of this dict literal
        head = _SUP.rfind("return {", max(0, m.start() - 1400), m.start())
        if head == -1:
            continue
        if '"route_status"' not in _SUP[head:m.start()]:
            missing.append(_SUP[:head].count("\n") + 1)
    return missing


def test_every_subtask_result_carries_a_routing_status():
    missing = _result_dicts_missing_status()
    assert not missing, (
        f"subtask result(s) built without route_status at line(s) {missing} — the card "
        f"cannot key on what is not there, and the default would silently be 'not matched'"
    )


def test_there_are_several_result_sites_to_check():
    """Non-vacuity: zero sites would satisfy the assertion above and prove nothing."""
    assert _SUP.count('"route_status": "') >= 5


def test_the_generalist_result_is_marked_no_match():
    """The one that must never outrank a match. Asserted by name rather than by count."""
    assert '"route_status": "no_match"' in _SUP


def test_MATCHED_is_the_shared_vocabulary():
    """The supervisor writes the literal the pure module compares against. A rename on one
    side and not the other silently makes every result 'not matched'."""
    assert MATCHED == "matched"
    assert f'"route_status": "{MATCHED}"' in _SUP
