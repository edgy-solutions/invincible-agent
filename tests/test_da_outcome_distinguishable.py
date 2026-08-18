"""Engine DA must not report a non-answer as a success (2026-08-15).

THE DEFECT. Witnessed at work 2026-08-15 01:16. The same question ran twice; one run resolved
the URN, queried MinIO and returned real CAGE codes, the other grounded nothing — and the
second is the one the user saw:

    "expert_response": {
      "status": "success",
      "data": "I couldn't locate a specific DataHub URN for the publog p_cage dataset, so I'm
               unable to retrieve cage values...",
      "sources": []
    }

`status: "success"`, with an honest failure as its payload. Nothing downstream could tell the
two apart, and everything downstream behaved correctly on what it was given.

WHAT IS SEALED HERE, AND WHAT IS NOT — stated because a check's scope is the thing that decides
whether green means anything ([[a-green-check-proves-only-its-scope]]):

  IN SCOPE   the classification RULE (`outcome.py`), which is pure and total; and the
             cross-module agreement that a status one component emits is a status the next
             component renders deliberately.
  NOT SEALED the live wiring — that `analyze_data` actually calls the classifier and puts the
             result on the envelope. That is a handler inside the Restate/FastAPI/smolagents
             chain; the source-reading pin below is the cheap half of it, and the honest
             statement is that a live run is what proves the whole path. The packet's
             definition of done is a VALUE ON THE UI, not this file going green.
"""
from __future__ import annotations

import ast
import pathlib
import sys

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

# BIND REAL DAGSTER AT COLLECTION TIME, not inside the tests. tests/routing/ installs a
# `dagster` STUB into sys.modules from a fixture (test time), and these tests assert on the
# real job graph's dependency EDGES — against the stub, `job`/`op` are `lambda f: f`, so
# there is no graph at all and the assertion would have nothing to fail on. Importing here
# means the real package is already in sys.modules before any fixture runs, whatever the
# collection order.
#
# This is the same defect the stub's own comment names: "a stub that works by depending on
# another test having run is not a stub." Binding at import removes the dependence rather
# than adding another name to the fake.
from dagster import DependencyDefinition, Failure as DagsterFailure, build_op_context  # noqa: E402

from agent_fleet.data_analyst.outcome import (  # noqa: E402
    OUTCOME_ANSWERED,
    OUTCOME_UNGROUNDED,
    REASON_NO_URN,
    REASON_QUERY_NEVER_SUCCEEDED,
    classify_outcome,
    message_for,
)

_URN = "urn:li:dataset:(urn:li:dataPlatform:s3,publog.p_cage,PROD)"


# ---------------------------------------------------------------------------
# The rule
# ---------------------------------------------------------------------------

def test_no_urn_is_ungrounded_and_says_why():
    """The witnessed case. Decided BEFORE the loop runs, without asking the model."""
    outcome, reason = classify_outcome("", [])
    assert outcome == OUTCOME_UNGROUNDED
    assert reason == REASON_NO_URN


def test_urn_but_no_successful_query_is_ungrounded():
    """A URN resolved and nothing read is not an answer either — a different reason, because
    it has a different cause and a different user action (infrastructure, not phrasing)."""
    outcome, reason = classify_outcome(_URN, [])
    assert outcome == OUTCOME_UNGROUNDED
    assert reason == REASON_QUERY_NEVER_SUCCEEDED


def test_a_query_that_returned_is_an_answer():
    outcome, reason = classify_outcome(_URN, [{"uri": _URN, "row_count": 2}])
    assert outcome == OUTCOME_ANSWERED
    assert reason == ""


def test_ZERO_ROWS_IS_AN_ANSWER_NOT_AN_ABSTENTION():
    """The distinction most likely to be got wrong, and the reason `ungrounded` is not `empty`.

    "The query ran and the table had no matching rows" is a RESULT. "I never ran a query" is
    not. Collapsing them would re-commit the one-field-for-two-outcomes defect one level down —
    and it would do it in the direction that hides working infrastructure behind an apology.
    """
    outcome, reason = classify_outcome(_URN, [{"uri": _URN, "row_count": 0}])
    assert outcome == OUTCOME_ANSWERED, (
        "an empty result set is an answer; only a run that never queried is ungrounded"
    )
    assert reason == ""


def test_attempts_are_not_corroboration():
    """THE TRAP THIS RULE EXISTS TO AVOID.

    `sources_collected` records ATTEMPTS — `_record_query_attempt` fires BEFORE the fetch on
    purpose, so the SourcesTrail can show "we tried this" when the data plane is unreachable.
    A classifier keyed on `sources` being non-empty would therefore call a failed read an
    answer, which is the original defect wearing a different signal.

    The classifier takes `query_successes` and nothing else, so an attempt list of any size
    cannot make an ungrounded run look answered. Asserted by construction: there is no
    parameter through which attempts could enter.
    """
    import inspect

    params = set(inspect.signature(classify_outcome).parameters)
    assert params == {"resolved_instance_id", "query_successes"}, (
        f"classify_outcome grew a parameter: {params}. If `sources` was added, an ATTEMPT can "
        "now be read as corroboration — that is the defect this rule was written to prevent."
    )


@pytest.mark.parametrize("reason", [REASON_NO_URN, REASON_QUERY_NEVER_SUCCEEDED])
def test_every_reason_has_its_own_user_facing_sentence(reason):
    """A reason that falls through to the default is a reason nobody wrote a message for —
    the user then gets a generic line for a specific, actionable problem."""
    assert message_for(reason) != message_for("some-unknown-reason")
    assert message_for(reason).strip()


# ---------------------------------------------------------------------------
# The cross-module agreement — the part that rots silently
# ---------------------------------------------------------------------------

def _literal_from_module(path: pathlib.Path, name: str):
    """Read a module-level literal WITHOUT importing the module.

    Both modules below sit behind FastAPI/BAML/Dagster import chains. Reading the source is
    the repo's existing idiom for pinning a binding that would otherwise need the whole stack
    stood up, and it is the only form that works in a plain unit run.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == name:
                    value = node.value
                    # Unwrap `frozenset({...})` / `set({...})` — `literal_eval` handles the set
                    # literal but not the constructor call around it.
                    if (isinstance(value, ast.Call)
                            and isinstance(value.func, ast.Name)
                            and value.func.id in {"frozenset", "set"}
                            and value.args):
                        value = value.args[0]
                    return ast.literal_eval(value)
    raise AssertionError(f"{name} not found at module level in {path}")


def _function_source(path: pathlib.Path, name: str) -> str:
    """Source of one top-level function, located by AST.

    NOT `split("async def name")` — this module also defines `analyze_data_proxy`, so a string
    split on the prefix silently returns the WRONG function and the assertion then reports a
    defect that is really a bug in the check. Scope again: the check must select the thing it
    claims to select.
    """
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(src, node) or ""
    raise AssertionError(f"top-level function {name}() not found in {path}")


def test_declared_non_answer_statuses_cover_what_producers_emit():
    """A status one component emits and the next does not recognise is a silent regression.

    The presentation agent renders a DECLARED non-answer deliberately, keyed on a frozenset of
    statuses. Engine DA emits `ungrounded`; the supervisor emits `engine_unreachable` when an
    engine cannot be reached. If either producer renames its status, or the renderer's set
    stops covering it, the payload silently falls back to archetype selection — which is
    exactly the inference-from-an-empty-payload path this work replaced.
    """
    pres = _REPO / "agent_fleet" / "presentation_agent" / "main.py"
    rendered = set(_literal_from_module(pres, "DECLARED_NON_ANSWER_STATUSES"))

    # Producer 1: Engine DA's vocabulary, imported directly (it is dep-free).
    assert OUTCOME_UNGROUNDED in rendered, (
        f"Engine DA emits {OUTCOME_UNGROUNDED!r} but the presentation agent does not render it "
        "deliberately — it will fall through to archetype selection and be inferred from an "
        "empty payload."
    )

    # Producer 2: the supervisor's transport-failure status, read from its source.
    sup = (_REPO / "src" / "iagent" / "defs" / "dynamic_supervisor.py").read_text(
        encoding="utf-8"
    )
    assert '"status": "engine_unreachable"' in sup, (
        "the supervisor's transport-failure result no longer emits `engine_unreachable`; "
        "update this seal and the renderer's set together, or a dead engine renders as a "
        "blank card again"
    )
    assert "engine_unreachable" in rendered, (
        "the supervisor emits `engine_unreachable` and the presentation agent does not "
        "recognise it"
    )


def test_an_ungrounded_run_cannot_produce_a_success_envelope():
    """THE ORIGINAL DEFECT, asserted behaviourally.

    This replaces a source-string check that asserted `OUTCOME_UNGROUNDED` appeared somewhere
    in the handler. That check was MEASURED NOT TO BITE: replacing the handler's branch with
    `if False:` left the constant present elsewhere in the function and the test stayed green
    — a guard reporting success over the exact defect it named. The envelope rule was moved
    into `outcome.py` so it can be executed rather than grepped for.
    """
    from agent_fleet.data_analyst.outcome import build_envelope

    env = build_envelope(
        OUTCOME_UNGROUNDED, REASON_NO_URN,
        agent_result="I couldn't locate a specific DataHub URN for the publog p_cage dataset.",
        sources=[{"uri": _URN}],          # ATTEMPTED — and an attempt is not an answer
        query_successes=[],
    )
    assert env["status"] == OUTCOME_UNGROUNDED
    assert env["status"] != "success"
    assert env["queries_succeeded"] == 0
    assert env["rows_returned"] == 0
    assert env["reason"] == REASON_NO_URN
    assert env["message"], "an ungrounded envelope must carry a typed, user-facing sentence"
    # The agent's own prose survives — it is usually the better sentence.
    assert "p_cage" in str(env["data"])


def test_an_answered_run_carries_its_own_corroboration():
    from agent_fleet.data_analyst.outcome import build_envelope

    env = build_envelope(
        OUTCOME_ANSWERED, "", agent_result="['00000', '00001']",
        sources=[{"uri": _URN}],
        query_successes=[{"uri": _URN, "row_count": 2}],
    )
    assert env["status"] == "success"
    assert env["queries_succeeded"] == 1
    assert env["rows_returned"] == 2, (
        "a success envelope must carry evidence a consumer can check independently of its "
        "own claim — `success` with queries_succeeded == 0 should be detectable"
    )


def test_da_handler_delegates_to_the_pure_rule():
    """A rule nothing calls is documentation. Scope: proves the binding, not a live run."""
    src = (_REPO / "agent_fleet" / "data_analyst" / "main.py").read_text(encoding="utf-8")
    assert "_classify_outcome_pure" in src, "main.py no longer imports the pure classifier"
    handler = _function_source(_REPO / "agent_fleet" / "data_analyst" / "main.py", "analyze_data")
    assert "_build_envelope(" in handler, (
        "analyze_data no longer builds its response through the pure envelope rule — if the "
        "branch moved back into the handler it is untestable again"
    )


def test_the_run_goes_red_AFTER_the_card_is_produced_not_instead_of_it():
    """Both properties, and the ORDER between them is the whole design.

    `execute_subtask` returns a typed failure instead of raising so the payload still gets
    built — which on its own buys the honest card by making the run GREEN, and a green run over
    a crashed subtask is the first-failure-direction lie at the orchestration layer. So a final
    op fails the run, and it takes `generate_ui_payload`'s output as an input SOLELY to force
    Dagster to schedule it afterwards.

    This asserts the dependency EDGE, not the source text. If someone reorders these ops the
    run still goes red and every unit test about the failure still passes — the only thing lost
    is the user's card, silently. That is precisely the class of regression a text-scanning
    check would sail past.
    """
    from iagent.defs.dynamic_supervisor import supervisor_query_job

    deps = supervisor_query_job.graph.dependencies
    key = next(
        (k for k in deps if "assert_every_engine_answered" in str(k)), None
    )
    assert key is not None, (
        "the run-level failure op is gone from supervisor_query_job — a crashed subtask now "
        "reports a clean run"
    )
    ui_dep = deps[key].get("ui_payload")
    assert isinstance(ui_dep, DependencyDefinition), (
        "the failure op no longer depends on ui_payload; without that edge Dagster may fail "
        "the run BEFORE generate_ui_payload records its output, and the user loses the card"
    )
    assert ui_dep.node == "generate_ui_payload", (
        f"the failure op is ordered after {ui_dep.node!r}, not generate_ui_payload"
    )


def test_the_red_op_fires_only_when_an_engine_did_not_answer():
    from iagent.defs.dynamic_supervisor import assert_every_engine_answered

    answered = [{"predicate_verb_iri": "mesh:analyzeDataset",
                 "expert_response": {"status": "success", "data": "['00000']"}}]
    # An UNGROUNDED run is an honest answer from a working system — it must NOT redden the run.
    ungrounded = [{"predicate_verb_iri": "mesh:analyzeDataset",
                   "expert_response": {"status": "ungrounded", "reason": REASON_NO_URN}}]
    unreachable = [{"predicate_verb_iri": "mesh:analyzeDataset",
                    "expert_response": {"status": "engine_unreachable", "error": "RemoteDisconnected"}}]

    for ok_case in (answered, ungrounded):
        assert_every_engine_answered(build_op_context(), ok_case, ui_payload="{}")

    with pytest.raises(DagsterFailure) as exc:
        assert_every_engine_answered(build_op_context(), unreachable, ui_payload="{}")
    assert "RemoteDisconnected" in str(exc.value.description)


def test_query_successes_is_returned_from_the_durable_step_not_read_from_a_closure():
    """The replay trap this file's own module documents at length.

    `ctx.run` returns its memoized value WITHOUT re-executing the body, so anything produced as
    a side effect inside the agent loop and read afterwards through a closure holds its INITIAL
    value on replay. `sources` and `denials` were already returned from the step for exactly
    this reason; `query_successes` and the classified outcome must be too, or every replayed
    answer classifies as ungrounded — a correctness regression introduced BY the durability
    machinery, which is the failure mode the module's comment warns about.
    """
    path = _REPO / "agent_fleet" / "data_analyst" / "main.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))

    run_agent = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "run_agent":
            run_agent = node
    assert run_agent is not None, "run_agent() not found in main.py"

    # The SUCCESS-path return specifically — identified by `ok: True`. An earlier version of
    # this check asked whether the KEY APPEARED ANYWHERE inside run_agent, which the EXCEPTION
    # path also satisfies: deleting the keys from the success return left the test green.
    # Measured, not supposed. Scope has to select the branch it claims to be about.
    success_returns = [
        n.value for n in ast.walk(run_agent)
        if isinstance(n, ast.Return) and isinstance(n.value, ast.Dict)
        and any(
            isinstance(k, ast.Constant) and k.value == "ok"
            and isinstance(v, ast.Constant) and v.value is True
            for k, v in zip(n.value.keys, n.value.values)
        )
    ]
    assert len(success_returns) == 1, (
        f"expected exactly one ok=True return in run_agent, found {len(success_returns)}"
    )
    keys = {
        k.value for k in success_returns[0].keys
        if isinstance(k, ast.Constant) and isinstance(k.value, str)
    }
    for key in ("query_successes", "outcome", "reason"):
        assert key in keys, (
            f"{key!r} is not returned from run_agent's SUCCESS path (returns: {sorted(keys)}). "
            "On a Restate replay `ctx.run` hands back the memoized dict without re-executing "
            "the body, so a closure read would classify from empty state and call every "
            "replayed answer ungrounded."
        )
