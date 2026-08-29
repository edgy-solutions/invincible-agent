"""THE PLANNING ARCHETYPES ARE PROJECTED, NOT GENERATED — and the card is the same twice.

Engine P returns typed rows against a declared output_uri, and every cortex-ui
contract for these five archetypes explicitly FORBIDS interpretation: "NOT
re-derive risk_flag", "NOT infer grouping from the ids", "NOT treat '(none)' as
missing data". A model in that path has nothing to decide and one thing to get
wrong.

WHY THIS GUARD EXISTS, measured 2026-08-24: the DesignUI fallback rendered
plan_schedule's 14 rows as "CHART DATA NOT RENDERABLE — no numeric column" on
one request and drew them cleanly on the next. Same measure, same rows, opposite
outcomes, because the chart shape was GUESSED per request.

    A beat that worked in rehearsal can fail in the room, with no change anywhere.

That is a nondeterministic component on the demo's critical path, in a project
that pre-registers every other number. These arms delete it.

Run: uv run --frozen --with pytest pytest tests/planning/test_planning_archetypes_are_projected.py -v
"""
from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "agent_fleet" / "presentation_agent" / "main.py"


def _fns():
    """Load ONLY the projection helpers, without importing the whole agent.

    main.py pulls fastapi, baml and the mesh client at import time. A guard that
    skips whenever its dependencies are absent is a guard that never runs in CI.
    """
    src = _SRC.read_text(encoding="utf-8")
    ns: dict = {
        "json": json, "Dict": dict, "Any": object, "Optional": object,
        "logger": types.SimpleNamespace(warning=lambda *a, **k: None),
    }
    import re as _re
    for marker in ("def _extract_agent_response(", "_PLANNING_ARCHETYPES: Dict[str, tuple] = {",
                   "def _project_planning_archetype("):
        start = src.index(marker)
        # End at the next TOP-LEVEL definition OF ANY KIND. Searching for a bare
        # newline-def walked straight past `async def _render_archetype_hardened`
        # and swallowed half the module, which surfaced as a SyntaxError in the
        # loader rather than a failure in the thing under test.
        tail = src[start + len(marker):]
        m = _re.search("[\n](?:async def |def |class |@)", tail)
        end = start + len(marker) + (m.start() if m else len(tail))
        exec(compile(src[start:end], str(_SRC), "exec"), ns)  # noqa: S102
    return ns


def _envelope(rows, **extra):
    return [{"persona": "PORTFOLIO_LEAD",
             "expert_response": {"summary": "s", "structured_data": rows, **extra}}]


TIMELINE_ROW = {
    "group_kind": "initiative", "group_id": "I1", "group_name": "ERP",
    "group_weight": None, "initiative_id": "I1", "initiative_name": "ERP",
    "phase_id": "P", "phase_name": "Build", "phase_sequence": 1,
    "project_id": "P5", "project_name": "Wave 1 Cutover",
    "planned_start": "2026-10-01", "planned_end": "2026-12-31",
    "actual_start": None, "actual_end": None, "risk_flag": None,
}


def test_every_planning_archetype_projects_without_a_model():
    """The arm returns a component for all five, with no BAML client in scope."""
    ns = _fns()
    for arch, key in [("INTERVAL_TIMELINE", "rows"), ("PERIOD_SERIES", "rows"),
                      ("THRESHOLD_GRID", "rows"), ("MATRIX_GRID", "rows"),
                      ("DELTA_SET", "effects")]:
        got = ns["_project_planning_archetype"](arch, _envelope([{"a": 1}]), "PORTFOLIO_LEAD", None)
        assert got is not None, f"{arch} did not project"
        assert got["archetype"] == arch
        assert got[key] == [{"a": 1}], f"{arch} did not carry rows verbatim as an ARRAY"


def test_rows_are_VERBATIM_including_the_capability_fan_out():
    """THE ROW KEY IS (group_id, project_id).

    Under the capability pivot ONE PROJECT PRODUCES MULTIPLE ROWS — one per
    contribution. A renderer that dedupes on project_id would silently drop real
    contributions, which the contract calls out by name. Projection must not
    collapse them.
    """
    ns = _fns()
    fan = [dict(TIMELINE_ROW, group_kind="capability", group_id="C1", group_weight=0.6),
           dict(TIMELINE_ROW, group_kind="capability", group_id="C2", group_weight=0.4)]
    got = ns["_project_planning_archetype"]("INTERVAL_TIMELINE", _envelope(fan), "X", None)
    out = got["rows"]
    assert len(out) == 2, "the capability fan-out was collapsed — project_id is not unique"
    assert [r["group_id"] for r in out] == ["C1", "C2"]
    assert out == fan, "rows were not verbatim"


def test_group_kind_is_LIFTED_never_inferred():
    """`group_kind` says what the top level MEANS. The contract forbids guessing
    it from whether an id looks like an initiative — that is how a capability
    pivot silently renders as an initiative one."""
    ns = _fns()
    got = ns["_project_planning_archetype"](
        "INTERVAL_TIMELINE", _envelope([dict(TIMELINE_ROW, group_kind="capability")]), "X", None)
    assert got["group_kind"] == "capability"


def test_absent_optional_fields_are_OMITTED_not_defaulted():
    """Nothing is invented. A field the producer did not write must not appear
    with a made-up value — inventing `scope_label` would put framing on a card
    that no verb asserted."""
    ns = _fns()
    got = ns["_project_planning_archetype"]("PERIOD_SERIES", _envelope([{"period": "FY26-Q3"}]), "X", None)
    assert "scope_label" not in got and "value_unit" not in got


@pytest.mark.parametrize("rows", [[], None, "not-a-list"], ids=["empty", "missing", "wrong-type"])
def test_a_rowless_payload_DEGRADES_rather_than_drawing_an_empty_card(rows):
    """An empty planning card is a REFUSAL, not an answer — the IntervalTimeline
    contract states it: "a plan with nothing in it is a broken scope filter".
    Returning a component here would render a confident blank."""
    ns = _fns()
    assert ns["_project_planning_archetype"]("INTERVAL_TIMELINE", _envelope(rows), "X", None) is None


def test_projection_is_DETERMINISTIC_across_repeated_calls():
    """The whole point. The same payload must produce byte-identical output —
    this is the property the DesignUI fallback did not have."""
    ns = _fns()
    env = _envelope([TIMELINE_ROW])
    outs = {json.dumps(ns["_project_planning_archetype"]("INTERVAL_TIMELINE", env, "X", None),
                       sort_keys=True) for _ in range(8)}  # dumps only to hash the result
    assert len(outs) == 1, "projection varied across identical inputs"


def test_a_non_planning_archetype_is_NOT_claimed():
    """The arm must not intercept archetypes it does not own, or CHART_WIDGET
    loses its existing key-conformance pass."""
    ns = _fns()
    assert ns["_project_planning_archetype"]("CHART_WIDGET", _envelope([{"a": 1}]), "X", None) is None


# ── THE ENVELOPE ────────────────────────────────────────────────────────────
#
# Caught in production 2026-08-25 and it is the reason this section exists.
# The planning arm returned the BARE component — {rows, archetype, group_kind,
# ...} — while every other return from _render_archetype_hardened hands back
# {"components": [...]}, the DashboardUI envelope. So `rendered_output` was
# stored unwrapped, `rendered_output?.components` was undefined, `components`
# became [], `hasRendered` went false, and the card drew its honest empty
# summary over a payload that was entirely correct.
#
# THE CONTENT WAS NEVER WRONG. archetype, group_kind and rows were all present
# and correct — the selector had chosen INTERVAL_TIMELINE, the projection was
# verbatim. One writer wrapped and another did not, and everything downstream
# was faithfully reporting what it received.
#
# Found by comparing top-level keys between a working artifact (`components`)
# and a failing one (`rows, archetype, ...`) — the envelope, not the content.

def test_the_planning_arm_WRAPS_before_it_returns():
    """The arm's own early return must hand back the DashboardUI envelope.

    Behavioural, not textual. A first version of this guard scanned the
    dispatch's source for `return ..., True` without a "components" literal —
    and failed on `return degraded, True`, where `degraded` is a variable
    already holding a wrapped dict. That is the same assert-on-the-neighbour
    mistake the defect itself was: checking a thing ADJACENT to the claim.

    So this executes the arm's actual wrap expression against a real projection
    and asserts the shape the client reads.
    """
    import re
    ns = _fns()
    src = _SRC.read_text(encoding="utf-8")
    # The exact early-return the planning arm takes, lifted from the dispatch.
    lines = src.splitlines()
    idx = next(i for i, ln in enumerate(lines) if ln.strip() == "if projected is not None:")
    ret = next(ln for ln in lines[idx:] if ln.strip().startswith("return "))
    expr = re.match(r"\s*return (.+), True\s*$", ret).group(1).strip()
    projected = ns["_project_planning_archetype"](
        "INTERVAL_TIMELINE", _envelope([TIMELINE_ROW]), "PORTFOLIO_LEAD", None)
    returned = eval(expr, {"projected": projected})  # noqa: S307 - fixed expr from our own source
    assert isinstance(returned, dict) and isinstance(returned.get("components"), list), (
        f"the planning arm returns a bare component, not the envelope: {expr}"
    )
    assert returned["components"][0]["archetype"] == "INTERVAL_TIMELINE"


def test_the_envelope_survives_a_real_projection():
    """End-to-end on the shape the client actually reads."""
    ns = _fns()
    projected = ns["_project_planning_archetype"](
        "INTERVAL_TIMELINE", _envelope([TIMELINE_ROW]), "PORTFOLIO_LEAD", None)
    envelope = {"components": [projected]}
    assert isinstance(envelope.get("components"), list) and envelope["components"]
    comp = envelope["components"][0]
    assert comp["archetype"] == "INTERVAL_TIMELINE"
    assert comp["rows"][0]["project_id"] == "P5"


def test_rows_are_an_ARRAY_not_a_json_string():
    """THE ENCODING. Every planning contract declares `encoding: "array",
    parsesTo: "array-of-objects"`.

    CHART_WIDGET is the ONE exception — its contract says of chart_data: "NOT an
    array. A STRING containing JSON... the single most surprising fact in the
    whole contract." That warning exists so nobody generalises from it, and the
    first version of this arm generalised from it anyway: it sent
    json.dumps(rows), the component hit `!Array.isArray(rows)` in
    validateIntervalTimeline, and drew "nothing to draw — no scheduled work in
    scope" over fourteen perfectly good rows. The component was right; the
    payload was wrong.
    """
    ns = _fns()
    for arch, key in [("INTERVAL_TIMELINE", "rows"), ("PERIOD_SERIES", "rows"),
                      ("THRESHOLD_GRID", "rows"), ("MATRIX_GRID", "rows"),
                      ("SHORTFALL_GRID", "rows"), ("DELTA_SET", "effects")]:
        got = ns["_project_planning_archetype"](arch, _envelope([{"a": 1}]), "X", None)
        assert isinstance(got[key], list), (
            f"{arch} sent {key} as {type(got[key]).__name__}; the contract declares "
            f"encoding: array — a JSON string reads as NO ROWS to the component"
        )


# ─────────────────────────────────────────────────────────────────────────────
# The freshness pair — carried for EVERY archetype, enumerated not remembered
# ─────────────────────────────────────────────────────────────────────────────

def _projected_archetypes(ns):
    """The population, read from the projector's own table."""
    return sorted(ns["_PLANNING_ARCHETYPES"])


def test_every_archetype_carries_the_freshness_pair():
    """`SemanticInterpreter.tsx` reads `comp.state_version` and hands it to six components.
    It was `undefined` for every planning card: the producer emits it on the envelope and the
    projection never carried it across — the SAME seam that swallowed the axis keys today.

    Enumerated from `_PLANNING_ARCHETYPES` rather than listed here, because a remembered list
    is what let SHORTFALL_GRID ship broken this morning while its seal passed.
    """
    ns = _fns()
    archetypes = _projected_archetypes(ns)
    assert len(archetypes) >= 5, f"parsed only {archetypes} — the table's shape moved"
    for arch in archetypes:
        key = ns["_PLANNING_ARCHETYPES"][arch][0]
        env = _envelope([{"a": 1}], state_ref="SC-DEMO", state_version=3)
        got = ns["_project_planning_archetype"](arch, env, "PORTFOLIO_LEAD", None)
        assert got is not None and got[key] == [{"a": 1}]
        assert got.get("state_ref") == "SC-DEMO", f"{arch} dropped state_ref"
        assert got.get("state_version") == 3, f"{arch} dropped state_version"


def test_a_state_version_of_ZERO_is_carried_not_dropped():
    """THE ONE-CHARACTER BUG THIS PINS. Baseline's version is legitimately 0. A truthiness
    test (`if val:`) drops it, so every baseline card reports no version while scenario cards
    work — which reads as 'the feature is broken for some cards' rather than as a falsy-zero
    slip. Absent and zero are different facts here as everywhere else in this model."""
    ns = _fns()
    env = _envelope([{"a": 1}], state_ref="baseline", state_version=0)
    got = ns["_project_planning_archetype"]("INTERVAL_TIMELINE", env, "X", None)
    assert "state_version" in got, "a zero version was dropped as falsy"
    assert got["state_version"] == 0


def test_a_producer_that_sends_no_version_makes_no_claim():
    """Absent-means-silent, the same contract `value_unit` follows. A card whose producer
    never stamped a version must not be given one here — a synthesised version would say the
    plan is at a state this projection cannot know."""
    ns = _fns()
    got = ns["_project_planning_archetype"]("INTERVAL_TIMELINE", _envelope([{"a": 1}]), "X", None)
    assert "state_version" not in got
    assert "state_ref" not in got


# ── CANVAS_SEED — the orchestration arm ─────────────────────────────────────
#
# Its payload is a list of ARTIFACT IDS (strings), not row objects, and the
# shape is DECLARED BY THE RECEIVER, not by us. cortex's canvasSeedFromArtifact
# (src/lib/canvasSeedFromAnswer.ts) reads:
#
#     { archetype: "CANVAS_SEED", canvas_type?: string, name?: string,
#       artifact_ids: string[] }
#
# The two halves were written in different lanes and a mechanical comparison of
# literal bytes is what caught the last mismatch before either shipped — a
# delivery-path disagreement that would have passed both suites while the phrase
# did nothing. These arms pin our half of that comparison.

def test_CANVAS_SEED_projects_ids_from_the_orchestration_response():
    """A measure verb answers under `structured_data`; an ORCHESTRATION answers
    under its own key. The seed returns {"artifact_ids": [...]} at the top
    level, and a projector looking only for structured_data would read that as
    an empty answer and degrade a perfectly good seed into "nothing to draw"."""
    ns = _fns()
    ids = ["urn:a", "urn:b", "urn:c", "urn:d", "urn:e"]
    env = [{"persona": "PORTFOLIO_LEAD",
            "expert_response": {"summary": "s", "artifact_ids": ids,
                                "name": "Q3 Portfolio Review"}}]
    got = ns["_project_planning_archetype"]("CANVAS_SEED", env, "PORTFOLIO_LEAD", None)
    assert got is not None, "the seed response did not project"
    assert got["archetype"] == "CANVAS_SEED"
    assert got["artifact_ids"] == ids, "ids were not carried verbatim"
    assert got["name"] == "Q3 Portfolio Review"


def test_CANVAS_SEED_preserves_ORDER_because_order_is_the_declaration():
    """Position 0 lands in the full-width anchor. The client never sorts, so a
    projection that reordered would move the schedule out of the anchor and
    produce a board that renders perfectly and is wrong."""
    ns = _fns()
    ids = ["gantt", "cost", "load", "gap", "matrix"]
    env = [{"persona": "X", "expert_response": {"artifact_ids": list(ids)}}]
    got = ns["_project_planning_archetype"]("CANVAS_SEED", env, "X", None)
    assert got["artifact_ids"] == ids, "the seeder's slot order was not preserved"


def test_CANVAS_SEED_omits_name_when_the_producer_did_not_send_one():
    """`name` is optional and the receiver defaults it to "Portfolio Planning".
    Inventing one here would put a title on a board no verb asserted."""
    ns = _fns()
    env = [{"persona": "X", "expert_response": {"artifact_ids": ["urn:a"]}}]
    got = ns["_project_planning_archetype"]("CANVAS_SEED", env, "X", None)
    assert "name" not in got


def test_an_EMPTY_seed_degrades_rather_than_projecting_a_seed_with_no_ids():
    """cortex treats an ids-less component as "not a seed answer" and creates
    nothing. Projecting one anyway would send it a component it must then
    reject — an empty board's worth of round trip, and a card that claims a
    seeding produced nothing rather than that it failed."""
    ns = _fns()
    for payload in ([], None):
        env = [{"persona": "X", "expert_response": {"artifact_ids": payload}}]
        assert ns["_project_planning_archetype"]("CANVAS_SEED", env, "X", None) is None


def test_CANVAS_SEED_carries_canvas_type_when_the_producer_states_it():
    """A CARRIER, NOT AN ASSERTION — and the distinction is why nothing emits this today.

    `canvas_type` is declared `required: false` in cortex's CanvasSeed.contract.ts and is
    NOT READ by anything: canvasSeedFromArtifact's return type is literally
    `{ ids: string[]; name?: string }` (checked 2026-08-29). So the producer deliberately
    does not send it — a producer-side write with no consumer is the same orphan species as
    a consumer-side read with no producer, just pointing the other way.

    The passthrough exists anyway because it costs nothing and asserts nothing: it carries
    what a producer wrote, and there is no producer. The day cortex reads the field, the
    server side is one line away instead of a change to this table."""
    ns = _fns()
    env = [{"persona": "PORTFOLIO_LEAD",
            "expert_response": {"artifact_ids": ["urn:a", "urn:b"],
                                "canvas_type": "portfolio_planning"}}]
    got = ns["_project_planning_archetype"]("CANVAS_SEED", env, "PORTFOLIO_LEAD", None)
    assert got["canvas_type"] == "portfolio_planning"


def test_CANVAS_SEED_omits_canvas_type_when_the_producer_did_not_state_it():
    """Carrying what the producer wrote, and nothing else. A default invented here would be
    a fabricated fact wearing a producer's clothes — the same prohibition that keeps `name`
    absent on the phrase path today."""
    ns = _fns()
    env = [{"persona": "X", "expert_response": {"artifact_ids": ["urn:a"]}}]
    got = ns["_project_planning_archetype"]("CANVAS_SEED", env, "X", None)
    assert "canvas_type" not in got
    assert "name" not in got, "the two optional fields must degrade the same way"


def test_CANVAS_SEED_ids_are_strings_so_no_field_is_lifted_off_a_ROW():
    """The passthrough loop lifts a missing field off `rows[0]` when the rows are dicts —
    correct for `group_kind` on a timeline. CANVAS_SEED's payload is a list of STRINGS, so
    that branch must never fire; a string has no `.get`, and reaching for one would turn an
    absent optional field into a crash on the demo's opening beat."""
    ns = _fns()
    env = [{"persona": "X", "expert_response": {"artifact_ids": ["urn:a", "urn:b"]}}]
    got = ns["_project_planning_archetype"]("CANVAS_SEED", env, "X", None)
    assert got["artifact_ids"] == ["urn:a", "urn:b"]
