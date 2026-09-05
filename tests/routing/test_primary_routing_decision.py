"""THE ROUTING RECORD MUST DESCRIBE THE SUBTASK THE ANSWER CAME FROM.

MEASURED 2026-09-04 on sandbox runs e82b3031 (21:47) and 2a627ea7 (21:55). A question decomposes
into PARALLEL subtasks, each posting its own `/resolve` to engine-o at the same moment. Engine
O's BAML calls run 8–30s against Ollama; two simultaneous posts contend; one subtask times out
at 30s while the other succeeds at roughly 44s. Both materialize `subtask_routing_decision`.

    02:44:47  task_0   resolve_subject failed ... Read timed out (read timeout=30)
                       routing_decision subject_uri=UNKNOWN fallback_reason=subject_unknown
    02:44:48  task_1   routing_decision subject_uri=fin#Program conf=0.97
                       verb_iri=mesh:finVarianceAnalysis verb_conf=0.94

THE OLD RULE WAS FIRST-TO-MATERIALIZE AND IT PREFERS THE FAILURE BY CONSTRUCTION. A 30-second
timeout finishes SOONER than a 44-second resolve-then-classify chain, so when one subtask fails
and another succeeds slowly the failing one wins every time. Not a coin flip weighted toward
failure — a rule that systematically records "not grounded" for a run that grounded.

WHAT IT PRODUCED: at 21:55 the card was Engine F's VARIANCE_TREE, drawn from real EVM rows
(WP-1102, ACWP 7.43M against BCWS 6.9M), inside a header reading NOT GROUNDED · General search ·
conf 0.00. **The record was never stale and never stamped pre-override.** It was ACCURATE about
a subtask whose answer nobody saw — which is precisely why every reading of the capture path
found nothing wrong with it.

AND THE KEY IS NOT `task_0`. That was inferred from two artifacts and it is wrong as a rule:
task_0 failed at 21:47 and task_1 failed at 21:55, and in both runs the card came from whichever
subtask produced a typed output. `generate_ui_payload` picks the first result carrying an
`output_uri` and skips those without; only a MATCHED route can produce one, because ADR-0019
Contract B sends an ungrounded subject to the generalist, which declares none. So "first matched
decision" is this side's expression of the card's own rule. Keying on the index would have been
right twice by luck.

Run: uv run --frozen pytest tests/routing/test_primary_routing_decision.py -v
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from iagent.gateway import _primary_routing_mat  # noqa: E402

_GW = (_REPO / "src" / "iagent" / "gateway.py").read_text(encoding="utf-8")


def _routing_mat(status: str, subject: str) -> dict:
    """A `subtask_routing_decision` materialization in Dagster's GraphQL shape."""
    return {
        "assetKey": {"path": ["subtask_routing_decision"]},
        "metadataEntries": [
            {"label": "route_status", "text": status},
            {"label": "subject_uri", "text": subject},
        ],
    }


def _other_mat() -> dict:
    return {
        "assetKey": {"path": ["subtask_graph_trace"]},
        "metadataEntries": [{"label": "subject_uri", "text": "x"}],
    }


_TIMED_OUT = _routing_mat("no_match", "UNKNOWN")
_GROUNDED = _routing_mat("matched", "http://invincible-agent/fin#Program")


# ── the measured defect, reproduced ─────────────────────────────────────────

def test_the_timeout_does_not_win_just_because_it_finished_first():
    """THE 21:55 RUN. The failing subtask materialized 14 seconds before the succeeding one,
    because failing fast is faster than succeeding slowly. It must not claim the record."""
    assert _primary_routing_mat([_TIMED_OUT, _GROUNDED]) is _GROUNDED


def test_order_does_not_decide_it():
    """The 21:47 run had the opposite task index. Same answer either way — that the outcome
    flipped on index is what made one night look like two different bugs."""
    assert _primary_routing_mat([_GROUNDED, _TIMED_OUT]) is _GROUNDED


def test_a_matched_decision_wins_from_ANY_position():
    """Three subtasks, the only grounded one last. First-arrival would take a failure."""
    mats = [_TIMED_OUT, _routing_mat("no_match", "UNKNOWN"), _GROUNDED]
    assert _primary_routing_mat(mats) is _GROUNDED


# ── the honest refusal must survive ─────────────────────────────────────────

def test_a_genuinely_ungrounded_run_still_records_its_refusal():
    """This fix must not manufacture a route. When NOTHING matched, the first decision stands
    — a run that really did not ground should say so, which is the 21:47 card being right."""
    first = _routing_mat("no_match", "UNKNOWN")
    assert _primary_routing_mat([first, _routing_mat("no_match", "UNKNOWN")]) is first


def test_no_routing_materialization_yields_None():
    assert _primary_routing_mat([_other_mat()]) is None
    assert _primary_routing_mat([]) is None


def test_it_ignores_other_assets():
    """A graph-trace materialization is not a routing decision, and the two are emitted under
    DIFFERENT conditions — the trace only when the subject grounded. Mixing them is how the
    two records in one artifact came to describe different subtasks in the first place."""
    assert _primary_routing_mat([_other_mat(), _TIMED_OUT]) is _TIMED_OUT


# ── non-vacuity ─────────────────────────────────────────────────────────────

def test_the_fixtures_are_actually_distinguishable():
    """Two identical fixtures would satisfy every identity assertion above and prove nothing."""
    assert _TIMED_OUT is not _GROUNDED
    from iagent.gateway import _metadata_dict
    assert _metadata_dict(_TIMED_OUT)["route_status"] == "no_match"
    assert _metadata_dict(_GROUNDED)["route_status"] == "matched"


# ── the consumer, which is the half that actually breaks ────────────────────

def test_the_gateway_branch_uses_the_selector():
    """A selector nobody calls is the orphan shape this repo has removed twice. Asserted on
    the branch itself so deleting the guard — the exact regression — goes red."""
    i = _GW.index('path == ["subtask_routing_decision"]')
    window = _GW[i:i + 700]
    assert "_primary_routing_mat(mats)" in window, (
        "the routing branch no longer selects by the card's rule — it is back to "
        "first-to-materialize, which prefers a timeout"
    )


def test_the_selector_is_defined_as_a_function():
    """AST rather than substring: the call above could otherwise be satisfied by a comment."""
    tree = ast.parse(_GW)
    assert any(
        isinstance(n, ast.FunctionDef) and n.name == "_primary_routing_mat"
        for n in ast.walk(tree)
    )


def test_the_first_wins_guard_is_still_there():
    """The selector narrows WHICH materialization may claim the record; it does not replace
    emit-once. Both must hold, or a second matched subtask would overwrite the first."""
    i = _GW.index('path == ["subtask_routing_decision"]')
    window = _GW[i:i + 700]
    assert '"route_decision_emitted" not in emitted_steps' in window
