"""The `review_request` now has a READER, and these are the joints that can be wrong silently.

R-076: `measures.py` emitted this block correctly from 2026-09-12 and nothing read it. The
consumer landed 2026-09-19 in three pieces, and each seam below is one where BOTH ends can be
right while the join is broken — which is exactly the class no per-end check can see (R-035).

    iagent_pure/acceptance_request.py              reads the block, builds the trigger
    restate_analyst/acceptance_selection.py        level -> definition id, via the table
    restate_analyst/safety_acceptance_workflow.py  loads THAT definition and runs it
    gateway.py (_dispatch_answer_artifact)         the call site, BEFORE the render

WHAT IS DELIBERATELY NOT ASSERTED HERE: that a row lands in `human_task_projection`. That needs
Postgres, Topaz and a rolled fleet, and the architect's ordering puts it after cortex's card
half draws. These are the half that can be wrong while the substrate is perfectly healthy.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest
import yaml

from ._engine_extra import requires_rdflib
from agent_fleet.safety_agent import entities, matrix, measures
from iagent_pure import acceptance_request as ar

_REPO = Path(__file__).resolve().parents[2]
_WORKFLOWS = _REPO / "policy" / "workflows"


@pytest.fixture(autouse=True)
def _clean_cache():
    matrix.reset_cache()
    yield
    matrix.reset_cache()


def _selection():
    return pytest.importorskip(
        "agent_fleet.restate_analyst.acceptance_selection",
        reason="restate_analyst extras not installed — this half is VOID, not green",
    )


def _drafts():
    for h in entities.HAZARDS:
        d = measures.draft_risk_assessment(hazard_id=h.hazard_id)
        if not d.get("refused") and "review_request" in d:
            yield h.hazard_id, d


# ---------------------------------------------------------------------------
# The floor. Every assertion below quantifies over drafts; none may be vacuous.
# ---------------------------------------------------------------------------

@requires_rdflib
def test_the_fixture_produces_drafts_to_assert_over():
    assert list(_drafts()), "no hazard produced a review request — every seal here is vacuous"


# ---------------------------------------------------------------------------
# The reader
# ---------------------------------------------------------------------------

@requires_rdflib
def test_every_draft_with_a_request_yields_one_to_the_reader():
    """The reader is ADDRESSED at `review_request`, so it must find what the engine writes."""
    for hazard_id, draft in _drafts():
        assert ar.review_request_of(draft) == draft["review_request"], hazard_id


def test_the_reader_does_not_go_hunting():
    """IT MUST NOT WALK. `walk_census._review_request` searches recursively because it reads a
    RENDERED turn and cannot know where the block rides; this reads the engine's own body, where
    the location is known. A recursive reader here would find a block nested inside some
    unrelated payload the day one appears — and would open an acceptance from it."""
    nested = {"components": [{"data": {"review_request": {"kind": "risk_acceptance_high"}}}]}
    assert ar.review_request_of(nested) == {}, (
        "the reader found a review_request nested inside an unrelated payload — it is supposed "
        "to read the engine body's own top-level key, not to hunt"
    )
    for junk in (None, [], "review_request", {"review_request": {}}, {"review_request": []}):
        assert ar.review_request_of(junk) == {}


# ---------------------------------------------------------------------------
# The trigger, and the placeholder it must bind
# ---------------------------------------------------------------------------

@requires_rdflib
def test_the_trigger_binds_every_strict_placeholder_in_the_selected_definition():
    """THE SEAL THAT MATTERS MOST, because its failure is INVISIBLE AND PERMANENT.

    `_bind` raises on an unbound STRICT placeholder — and `audience` is the strict one, because
    "a human_await registered against the literal `risk_acceptance_{level_slug}` matches no Topaz
    relation, so NOBODY can act on it and the workflow suspends forever with no error."

    So: for every draft, the definition the table selects must have every `{placeholder}` in its
    audience covered by a SCALAR key of the trigger — scalar because `_run_definition` binds from
    `{k: v for k, v in request.items() if isinstance(v, (str, int, float))}` and a value nested
    one level down fails exactly like a missing one.
    """
    import re

    sel = _selection()
    checked = 0
    for hazard_id, draft in _drafts():
        trigger = ar.acceptance_trigger(draft["review_request"])
        scalars = {k for k, v in trigger.items() if isinstance(v, (str, int, float)) and v != ""}
        definition_id = sel.select(trigger["level"])
        wf = yaml.safe_load((_WORKFLOWS / f"{definition_id}.yaml").read_text(encoding="utf-8"))
        for step in wf.get("steps") or []:
            audience = step.get("audience")
            if not audience:
                continue
            needed = set(re.findall(r"\{(\w+)\}", audience))
            missing = sorted(needed - scalars)
            assert not missing, (
                f"{hazard_id} -> {definition_id} step {step.get('id')!r}: audience {audience!r} "
                f"needs {sorted(needed)} and the trigger supplies scalars {sorted(scalars)} — "
                f"missing {missing}. The executor binds this one STRICTLY, so this registers a "
                f"task against a literal audience no Topaz relation matches and the workflow "
                f"suspends forever with no error."
            )
            checked += 1
    assert checked, "no definition declared an audience — this seal asserted nothing"


@requires_rdflib
def test_the_two_derivations_of_the_audience_agree():
    """AN INVARIANT BETWEEN TWO DECLARATIONS, which no per-declaration check can see (R-035).

    The engine resolves `acceptance_audience` from the ratified matrix TTL. The definition
    templates its own from `{level_slug}` with the compartment written into the YAML. Both are
    correct read alone, and only a check holding both at once can tell whether they agree.

    **THE TWO PATHS ARE NOT THE SAME ASSERTION, and the first version of this seal got that
    wrong — it demanded every definition audience equal the engine's and went red on HAZ-1001,
    correctly.** `safety_concurrence` carries ONE step and it is the concurrence, whose audience
    is `risk_acceptance_concurrence_<slug>` — a DIFFERENT and deliberately different queue. The
    acceptance for those levels is reached through the chaining table, not through this
    definition, which is the whole of ADR-0039's "two definitions and a selection row".

    So what must agree on BOTH paths is the LEVEL, which is the thing derived twice:

        direct       the bound audience IS the engine's acceptance_audience, exactly
        concurrence  the bound audience is the concurrence sibling of it — same level slug,
                     same compartment, different kind

    MEASURED AGREEING on the live fleet 2026-09-19 for HAZ-1003
    (`risk_acceptance_medium:SUSTAINMENT` both ways, by both derivations).
    """
    sel = _selection()
    compared = 0
    for hazard_id, draft in _drafts():
        engine_audience = draft.get("acceptance_audience")
        if not engine_audience:
            continue
        trigger = ar.acceptance_trigger(draft["review_request"])
        scalars = {k: v for k, v in trigger.items() if isinstance(v, (str, int, float))}
        definition_id = sel.select(trigger["level"])
        wf = yaml.safe_load(
            (_WORKFLOWS / f"{definition_id}.yaml").read_text(encoding="utf-8"))
        engine_kind, _, engine_compartment = engine_audience.partition(":")
        for step in wf.get("steps") or []:
            if not step.get("audience"):
                continue
            bound = step["audience"].format(**scalars)
            kind, _, compartment = bound.partition(":")
            assert compartment == engine_compartment, (
                f"{hazard_id} -> {definition_id} step {step.get('id')!r}: the definition binds "
                f"compartment {compartment!r} and the matrix TTL resolved {engine_compartment!r} "
                f"({bound!r} vs {engine_audience!r}). The task opens in a compartment the "
                f"ratified matrix never named."
            )
            # THE LEVEL IS THE VALUE DERIVED TWICE, so it is the one that must agree on both
            # paths. `risk_acceptance_serious` and `risk_acceptance_concurrence_serious` differ
            # in KIND and share the slug; a definition that bound `..._medium` for a Serious
            # hazard would route a Serious acceptance to the Medium authority and read as fine.
            assert kind.endswith(f"_{trigger['level_slug']}"), (
                f"{hazard_id} -> {definition_id} step {step.get('id')!r}: audience kind "
                f"{kind!r} does not end in the level slug {trigger['level_slug']!r} the engine "
                f"resolved. Two derivations of one level have diverged."
            )
            if step.get("id") == "acceptance":
                assert bound == engine_audience, (
                    f"{hazard_id}: the acceptance step binds {bound!r} and the matrix TTL "
                    f"resolved {engine_audience!r} — the acceptance itself must open in exactly "
                    f"the queue the matrix named."
                )
            compared += 1
    assert compared, "no draft carried an acceptance_audience — this seal asserted nothing"


@requires_rdflib
def test_both_paths_are_exercised_by_the_fixture():
    """THE SEAL ABOVE BRANCHES ON THE PATH, so a fixture reaching only one arm would make half
    of it vacuous while it read as covering both. Six hazards, and they must span both."""
    sel = _selection()
    reached = set()
    for _hazard_id, draft in _drafts():
        trigger = ar.acceptance_trigger(draft["review_request"])
        reached.add(sel.select(trigger["level"]))
    assert len(reached) >= 2, (
        f"every fixture hazard selects {reached} — the concurrence/direct distinction is "
        "asserted on one arm only, and the other could be anything"
    )


@requires_rdflib
def test_every_audience_the_selected_definition_binds_is_granted():
    """A BOUND AUDIENCE WITH NO ACTORS IS THE WORST OUTCOME IN THIS ARC.

    `register_task` raises `NoEntitledRecipients` for a zero-actor audience — so the hazard is
    drafted, the acceptance is opened, nothing appears in anyone's queue, and the system looks
    like it is waiting for a human who was never asked. The sibling file asserts this for the
    audiences the ENGINE names; this asserts it for the audiences the DEFINITION actually binds,
    which for Serious and High is a different string.
    """
    sel = _selection()
    granted = yaml.safe_load(
        (_REPO / "policy" / "task_grants.yaml").read_text(encoding="utf-8"))["audiences"]
    checked = 0
    for hazard_id, draft in _drafts():
        trigger = ar.acceptance_trigger(draft["review_request"])
        scalars = {k: v for k, v in trigger.items() if isinstance(v, (str, int, float))}
        definition_id = sel.select(trigger["level"])
        wf = yaml.safe_load(
            (_WORKFLOWS / f"{definition_id}.yaml").read_text(encoding="utf-8"))
        for step in wf.get("steps") or []:
            if not step.get("audience"):
                continue
            bound = step["audience"].format(**scalars)
            assert bound in granted, (
                f"{hazard_id} -> {definition_id} step {step.get('id')!r} binds audience "
                f"{bound!r}, which task_grants.yaml does not grant — register_task would raise "
                f"NoEntitledRecipients and the review would open into silence"
            )
            assert granted[bound].get("grant_to"), (
                f"{bound} is declared with an EMPTY grant_to — present in git and resolving to "
                "zero actors is the same outcome as absent, and harder to spot"
            )
            checked += 1
    assert checked, "no definition bound an audience — this seal asserted nothing"


@requires_rdflib
def test_an_incomplete_request_refuses_rather_than_inventing_a_slug():
    """A trigger with no `level_slug` must fail HERE, not at a queue nobody holds."""
    _, draft = next(iter(_drafts()))
    rr = {**draft["review_request"]}
    rr["payload"] = {k: v for k, v in rr["payload"].items()
                     if k not in ("risk_level", "risk_level_slug")}
    with pytest.raises(ar.AcceptanceRequestError) as exc:
        ar.acceptance_trigger(rr)
    assert "risk_level" in str(exc.value)


# ---------------------------------------------------------------------------
# The selection
# ---------------------------------------------------------------------------

def test_every_level_the_table_declares_selects_a_definition_that_exists():
    """The table is total over its declared domain AND every target is on disk.

    `test_a_decision_row_selects_a_real_definition.py` already checks reference resolution from
    the FILES. This asks the RUNTIME selector the same question, because the selector composes
    seed+overlay through the SDK and a composition that dropped the overlay would leave that
    file-side seal green and this one red — which is the distinction worth having.
    """
    sel = _selection()
    table = sel.load_table()
    declared = table["domain"]["level"]
    assert declared, "the table declares no domain for level"
    for level in declared:
        definition_id = sel.select(level)
        assert (_WORKFLOWS / f"{definition_id}.yaml").is_file(), (
            f"level {level!r} selects {definition_id!r}, which is not authored in "
            f"{_WORKFLOWS}"
        )


def test_an_undeclared_level_refuses_and_does_not_default():
    """A FALL-THROUGH IS THE FAILURE, NOT THE FALLBACK. `policy/decisions/README.md`: a
    fall-through "means NO DEFINITION WAS CHOSEN at the moment a human risk decision was due"."""
    sel = _selection()
    for bogus in ("Catastrophic", "MEDIUM", "medium", ""):
        with pytest.raises(sel.AcceptanceSelectionError):
            sel.select(bogus)


def test_the_selection_distinguishes_concurrence_from_direct():
    """THE SEAL THAT DEFENDS THE CHOICE, and without it this whole module could be one line
    returning `safety_acceptance_direct` and every other test here would still pass.

    MIL-STD-882E §4.3.7 requires the user representative's formal concurrence for Serious and
    High and says nothing about Medium or Low. If both arms selected the same definition, an
    over-escalating process and a bypassing one would be indistinguishable from the outside.
    """
    sel = _selection()
    direct = {sel.select("Low"), sel.select("Medium")}
    concurrence = {sel.select("Serious"), sel.select("High")}
    assert len(direct) == 1 and len(concurrence) == 1, (direct, concurrence)
    assert direct != concurrence, (
        f"Low/Medium and Serious/High both select {direct} — the table no longer distinguishes "
        "the levels the standard treats specially, and a High risk would be accepted without "
        "the concurrence §4.3.7 requires first."
    )


# ---------------------------------------------------------------------------
# The wiring — both ends of each join, in one assertion
# ---------------------------------------------------------------------------

def test_the_gateway_calls_the_service_the_runtime_registers():
    """THE URL IS A FROZEN CONTRACT SURFACE and it is spelled in two files.

    The gateway builds `/SafetyAcceptance/{key}/run/send` by hand, as it does for
    `/GroupedReview/...`; the runtime registers `Workflow("SafetyAcceptance")` with a handler
    named `run`. Each is correct alone; a rename on either side is a 404 at the moment a hazard
    needs an authority, and nothing else in the suite looks at both.
    """
    wf_src = (_REPO / "agent_fleet" / "restate_analyst"
              / "safety_acceptance_workflow.py").read_text(encoding="utf-8")
    gw_src = (_REPO / "src" / "iagent" / "gateway.py").read_text(encoding="utf-8")
    assert 'Workflow("SafetyAcceptance")' in wf_src
    assert "/SafetyAcceptance/" in gw_src, (
        "the gateway no longer calls SafetyAcceptance — the review_request consumer is "
        "unreachable and R-076 has recurred in the same place"
    )
    assert "/run/send" in gw_src, (
        "the gateway calls SafetyAcceptance but not through `/send` — a synchronous call would "
        "hold the user's turn open until a human disposes the acceptance, which may be days"
    )


def test_the_workflow_is_mounted_on_the_restate_app():
    """A registered SERVICE OBJECT that is never mounted is a guard that cannot fire: the
    handler exists, the import succeeds, and the ingress answers 404."""
    src = (_REPO / "agent_fleet" / "restate_analyst" / "main.py").read_text(encoding="utf-8")
    mount = next(line for line in src.splitlines() if "restate.app(services=" in line)
    assert "safety_acceptance" in mount, (
        "SafetyAcceptance is imported but not in the mounted service list — the ingress would "
        f"404 every acceptance. Mount line: {mount.strip()[:200]}"
    )


def test_the_boot_invariant_covers_every_definition_the_table_can_select():
    """`_EXPECTED_DEFINITIONS` refuses to boot when a definition it may be asked to run is not
    loadable, so its input must be the REACHABLE SET and not a sample of it.

    THIS SEAL RUNS AGAINST THE DERIVATION, NOT THE SOURCE TEXT OF `main.py`. It cannot import
    `agent_fleet.restate_analyst.main` — that module's line 633 imports `orchestrator.auth` with
    no source-layout fallback, unlike every other import in the file, so it is unimportable in
    the repo layout and a seal there could only read its text. The derivation therefore lives in
    `acceptance_selection`, where the table it derives from lives, and is checked directly.
    """
    sel = _selection()
    selectable = set(sel.selectable_definitions())
    assert selectable, "the table names no definitions — the derivation asserted nothing"
    for level in sel.load_table()["domain"]["level"]:
        assert sel.select(level) in selectable, (
            f"level {level!r} selects {sel.select(level)!r}, which the derived set does not "
            f"cover ({sorted(selectable)}) — this engine could be asked to run a process it "
            "cannot load, and would find out at first use"
        )
    for definition_id in selectable:
        assert (_WORKFLOWS / f"{definition_id}.yaml").is_file(), (
            f"the boot invariant would demand {definition_id!r} and it is not authored"
        )


def test_the_boot_invariant_is_derived_and_not_typed_beside_the_table():
    """The property above holds BY CONSTRUCTION only while `main.py` keeps deriving it. A future
    edit replacing the call with a literal tuple would restore the sample — and every assertion
    above would still pass, because they test the derivation rather than its use."""
    src = (_REPO / "agent_fleet" / "restate_analyst" / "main.py").read_text(encoding="utf-8")
    assert "selectable_definitions()" in src, (
        "main.py no longer derives _EXPECTED_DEFINITIONS from the decision table — a "
        "hand-written list is a SAMPLE of the reachable set, and a tailoring that points a "
        "level at a third definition would ship an unloadable route with the boot check green"
    )


def test_the_consumer_does_not_call_register_task_directly():
    """THE TRAP `measures.py`'s OWN COMMENT SETS.

    It says the draft "carries a request the gateway can hand to `register_task` VERBATIM", and
    the keys ARE that function's parameters — so the one-line consumer is right there and it is
    WRONG for Serious and High: `register_task` opens the acceptance immediately, bypassing the
    concurrence the route exists to enforce. The request supplies the ARGUMENTS; the table
    supplies the ORDERING.
    """
    for mod in (ar, _selection()):
        src = inspect.getsource(mod)
        assert "register_task" not in src.replace("`register_task`", ""), (
            f"{mod.__name__} calls register_task — that opens the acceptance directly and skips "
            "the concurrence chain for Serious and High"
        )
