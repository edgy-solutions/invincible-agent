"""PHASE 2's ACCEPTANCE INSTRUMENT — and it records WHICH ARM each failure died on.

Gate 2's bar: >=90% of the 51 cases route to the correct intent with correct
slots, and 100% of out-of-model cases refuse. A WRONG-BUT-CONFIDENT ANSWER FAILS
THE WHOLE GATE, NOT A POINT.

── WHY PER-ARM RECORDING IS NOT OPTIONAL ──────────────────────────────────────

A case can fail three different ways and the escalation levers target different
ones:

    routing  -> wrong intent_id                    -> few-shot exemplars
    slot     -> right intent, wrong slot values    -> two-step classify-then-fill
    number   -> narration cites an unsupported figure -> neither; the checker
                worked, and it is reported separately

An aggregate pass rate cannot choose between levers. "84%" sends someone to tune
a prompt when the failures might all be slot fills, which few-shot exemplars barely
move. The table is the deliverable; the percentage is its headline.

── FIXTURE VALIDATION RUNS WITHOUT AN ENDPOINT ────────────────────────────────

The structural arms below execute in CI with no model: every expected intent_id
exists in the catalog, every expected slot is declared on that intent, every
named entity appears in the seed. A fixture that references a slot the catalog
does not have measures nothing, and it would fail at 3am looking like a routing
problem.

The ENDPOINT run is separate and explicit (`--endpoint`), because a suite that
silently needs a live model is a suite that goes red for reasons unrelated to the
code under test.

Run (structural): uv run --frozen --with pytest --with pyyaml pytest tests/eval/test_planning_eval.py -v
Run (endpoint):   PLANNING_EVAL_ENDPOINT=1 uv run ... -v -s
"""
from __future__ import annotations

import os
from collections import Counter
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

_REPO = Path(__file__).resolve().parents[2]
_FIXTURE = Path(__file__).parent / "planning_questions.yaml"
_CATALOG = _REPO / "agent_fleet" / "planning_agent" / "intent_catalog.yaml"
_SEED = _REPO / "agent_fleet" / "planning_agent" / "seed.py"

_ENDPOINT_ENABLED = os.getenv("PLANNING_EVAL_ENDPOINT", "").strip() not in ("", "0")


def _fx() -> dict:
    return yaml.safe_load(_FIXTURE.read_text(encoding="utf-8"))


def _catalog() -> dict:
    return yaml.safe_load(_CATALOG.read_text(encoding="utf-8"))


def _by_id() -> dict:
    return {i["intent_id"]: i for i in _catalog()["intents"]}


# ── FIXTURE INTEGRITY (no endpoint needed) ─────────────────────────────────

def test_the_fixture_has_51_routing_cases():
    """17 questions x 3 phrasings. A short fixture reports a percentage of the
    wrong denominator, which reads as a gate result and is not one."""
    assert len(_fx()["cases"]) == 51


def test_the_fixture_has_exactly_the_three_out_of_model_refusals():
    """Gate 2 makes 100%-refusal absolute, so the set cannot be optional."""
    concepts = {r["expect"]["out_of_model_concept"] for r in _fx()["refusals"]}
    assert concepts == {"roi", "risk_owner", "headcount"}


def test_every_expected_intent_EXISTS_in_the_catalog():
    """A fixture expecting an intent nobody declared measures nothing, and fails
    at 3am looking like a routing problem."""
    ids = set(_by_id()) | {"no_intent_match"}
    for case in _fx()["cases"] + _fx()["refusals"]:
        assert case["expect"]["intent_id"] in ids, f"{case['id']}: unknown intent"


def test_every_expected_slot_is_DECLARED_on_its_intent():
    """THE DRIFT ARM. A fixture asserting a slot the catalog does not have would
    fail forever and be read as a model failure."""
    by_id = _by_id()
    for case in _fx()["cases"]:
        iid = case["expect"]["intent_id"]
        declared = set((by_id[iid].get("slots") or {}).keys())
        for slot in (case["expect"].get("slots") or {}):
            assert slot in declared, f"{case['id']}: {iid} has no slot {slot!r}"


def test_every_named_entity_APPEARS_IN_THE_SEED():
    """C4 and correctness at once. A phrasing naming an entity the seed lacks
    tests the RESOLVER's refusal path by accident — a different measurement
    wearing this one's name."""
    seed = _SEED.read_text(encoding="utf-8")
    for case in _fx()["cases"]:
        for value in (case["expect"].get("slots") or {}).values():
            if isinstance(value, str) and value[:1].isupper() and len(value) > 3:
                assert value in seed, f"{case['id']}: {value!r} is not in the seed"


def test_the_fixture_carries_its_PRE_REGISTRATION():
    """The number is measured against a claim made before the run, or it is a
    number described after the fact."""
    pre = _fx()["pre_registration"]
    assert pre.get("gate") and pre.get("predicted_weakest")
    assert len(pre["predicted_weakest"]) >= 2


def test_soft_phrasings_are_MARKED_so_the_prediction_is_checkable():
    """The pre-registration predicts soft-language phrasings are weakest. That
    claim is only falsifiable if the runner can tell which cases they are."""
    soft = [c for c in _fx()["cases"] if c.get("soft")]
    assert len(soft) >= 4, "too few marked soft cases to test the prediction"


# ── THE NUMBER-CHECK, IN SITU ──────────────────────────────────────────────

def test_the_number_check_boundary_cases_behave_as_the_rule_says():
    """The checker is the last gate every demo answer passes through, so the eval
    exercises it here and not only in its unit arms."""
    import importlib.util
    import sys

    src = _REPO / "agent_fleet" / "planning_agent" / "number_check.py"
    spec = importlib.util.spec_from_file_location("number_check__eval", src)
    nc = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = nc
    spec.loader.exec_module(nc)

    failures = []
    for case in _fx()["number_check_cases"]:
        clean, violations = nc.check_narration(case["narration"], case["rows"])
        kept = clean.strip() != ""
        if kept != case["expect_kept"]:
            failures.append(f"{case['id']}: expected kept={case['expect_kept']} ({case['why']})")
    assert not failures, "number-check boundary failures:\n" + "\n".join(failures)


# ── THE ENDPOINT RUN ───────────────────────────────────────────────────────

@pytest.mark.skipif(not _ENDPOINT_ENABLED, reason="set PLANNING_EVAL_ENDPOINT=1")
def test_routing_against_the_real_endpoint_with_per_arm_attribution():
    """THE GATE ITSELF. Reports the number against the pre-registration whatever
    it is — a 70% with per-arm attribution is a better deliverable than a number
    massaged toward 90.

    NOT SKIPPED SILENTLY WHEN THE ENDPOINT IS ABSENT: it is skipped EXPLICITLY on
    an env flag, so an absent model reads as "not run" and never as "passed".
    """
    from planning_eval_runner import run_suite  # noqa: PLC0415

    result = run_suite(_fx())

    arms = Counter(f["arm"] for f in result["failures"])
    print("\n=== PLANNING EVAL — per-arm attribution ===")
    print(f"routing correct : {result['routing_ok']}/{result['total']}")
    print(f"slots correct   : {result['slots_ok']}/{result['total']}")
    print(f"refusals correct: {result['refusal_ok']}/{result['refusal_total']}")
    print(f"arms            : {dict(arms)}")
    lat = result.get("latency_s", {})
    if lat:
        # INCIDENTAL BUT VALUABLE: the first latency sample through the REBUILT
        # funnel (preset directions, deterministic slots). Re-running 105 calls
        # just to measure it later would be waste, and it feeds the demo-latency
        # decision directly.
        print(f"latency (s)     : median {lat['median']}  p90 {lat['p90']}  max {lat['max']}  n={lat['n']}")
    soft_failed = result.get("soft_failures", [])
    print(f"soft-language failures: {len(soft_failed)} {soft_failed}")
    for f in result["failures"]:
        print(f"  [{f['arm']}] {f['id']}: expected {f['expected']} got {f['got']}")

    # The gate is asserted, but the TABLE prints first — a failed assertion that
    # hides its own diagnosis makes the next step a re-run instead of a decision.
    assert result["refusal_ok"] == result["refusal_total"], (
        "an out-of-model question was answered — Gate 2 fails the WHOLE gate on "
        "a wrong-but-confident answer, not a point"
    )
    pass_rate = result["slots_ok"] / result["total"]
    assert pass_rate >= 0.90, f"routing+slots {pass_rate:.1%} < 90% (see table above)"
