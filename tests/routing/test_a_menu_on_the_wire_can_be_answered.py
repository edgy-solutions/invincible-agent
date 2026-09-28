"""AN OPTION ON THE WIRE MUST BE ANSWERABLE — `sub_query` AND `accepted_slots`, or a named gap.

THE DEFECT (lot 3, 2026-09-25). `_render_refusal_menu` emitted an ELICITATION carrying
`options` but neither `sub_query` nor `accepted_slots`. Both are declared on the archetype
(`_FLAT_ARCHETYPES["ELICITATION"]`, fields read from cortex's `Elicitation.contract.ts`) and
both are read by `answer_ask` (`src/iagent_pure/slot_disposition.py`), which reconstructs the
re-route from the CARD and nothing else:

    slot     = card["slot"]
    accepted = card["accepted_slots"]
    return Reroute(BIND, {**accepted, slot: value})

So a menu missing them renders, offers choices, and dead-ends on the pick. Nothing errors.

WHY THIS FILE IS WRITTEN AGAINST A POPULATION AND NOT A FUNCTION. The dispatch named
`_render_refusal_menu` at one line number. The property is "a producer that puts `options` on
the wire", and there were TWO such producers (`_render_refusal_menu` and
`_render_abstain_menu`) with identical exposure — the second was not in the report that found
the first. `test_every_option_bearing_producer_is_covered` is what keeps a THIRD from being
added outside this file's reach; it derives the population from the module rather than listing
it, so a new producer fails the count instead of quietly inheriting the defect.

⛔ WHAT THIS FILE DELIBERATELY DOES NOT REQUIRE: `accepted_slots` present-and-empty.

`accepted_slots` IS NOT ON THE **WRAPPER** TODAY — and the unqualified version of that sentence,
which stood here until 2026-09-27, was false. ⚠ NARROWED AFTER A LIVE READ (roll #5, revision
153): the field arrives on real cards as `{}`, by a route this measurement never looked down.

    the WRAPPER   gateway.py's `_results`, dynamic_supervisor's POST body -> sub_query, NO accepted_slots
    the ENVELOPE  slot_disposition.py:634 `dict(accepted or {})`          -> BOTH, always

`_wrapper_field` reads the wrapper, so the conditional in `_reroute_fields` is still justified
exactly as written. What was wrong was the SCOPE of the claim: "not on the wire" was read off two
callers and stated about the wire. A field reaching the card through the envelope is on the wire.

**And the envelope's `{}` is CORRECT, which is the distinction the rest of this docstring turns
on.** `slot_disposition` holds the accepted set as a parameter, so `{}` there is the informed
report that nothing was bound — true on a first ask. The value forbidden below is an UNINFORMED
`{}`, invented by a producer that cannot know. A rule about a value is a rule about a producer's
knowledge; check which producer before calling the value a defect. A seal demanding the key would be
satisfied by `accepted_slots: {}` — and an empty dict is not a missing value here, it is a
FALSE ONE: `{**accepted, slot: value}` with `accepted == {}` re-routes having silently dropped
every slot the first turn bound, which is the exact failure `slot_disposition`'s docstring says
the field exists to prevent. So the rule sealed here is CONDITIONAL — present on the wire means
present on the card — plus one arm that pins the wire gap itself so it cannot be forgotten or
silently "fixed" with a default.

Run: uv run --frozen pytest tests/routing/test_a_menu_on_the_wire_can_be_answered.py -v
"""
from __future__ import annotations

import ast
import io
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
for _p in (str(_REPO), str(_REPO / "agent_fleet" / "presentation_agent")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_PRESENTATION = _REPO / "agent_fleet" / "presentation_agent" / "main.py"


def _import_engine_f():
    """Import `presentation_agent.main` FOR REAL, with `baml_client` stubbed.

    ⛔ CALLED LAZILY, FROM INSIDE THE TESTS — NEVER AT MODULE LEVEL. This is load-bearing and it
    cost a real defect to learn. An earlier version of this file did `pf = _import_engine_f()` at
    import time, which put the stub into `sys.modules` during COLLECTION. pytest imports every
    test module before it runs any test, so the stub was in place while
    `test_response_shapes_are_not_groundable.py` and
    `test_the_cold_start_fallback_spans_mesh_and_the_callers_domains.py` were imported, and their
    `from baml_client.types import …` died with "'baml_client' is not a package". Each of the three
    files passed ALONE; the trio failed together at collection — i.e. I had measured a sample and
    read it as the population.

    `tests/conftest.py`'s `_restore_globally_stubbed_modules` exists for exactly this class and
    could not help: it is `scope="module"`, so its snapshot is taken after collection has already
    finished. Stubbing inside the tests puts the mutation back INSIDE that fixture's window, which
    is what makes the cleanup the conftest owns actually apply to this file.

    The module does `from baml_client import b` at line 41, and `baml_client` is GENERATED and
    not installed in this venv — every existing test therefore imports only
    `presentation_agent.capabilities` or parses `main.py` as text (see
    `tests/planning/test_canvas_seed_determinism.py`'s own note: "presentation_agent/main.py
    imports baml_client, which is not installed in this environment").

    A SOURCE-PARSING SEAL CANNOT TELL A PRODUCER THAT EMITS A FIELD FROM ONE THAT MENTIONS IT,
    and the defect being sealed here is a missing field in a returned dict. So the import is made
    to work rather than avoided: `b` is only awaited inside `render_ui`'s BAML paths, which no arm
    in this file calls, so a stub that satisfies the import is sufficient and cannot silently
    stand in for real behaviour anywhere these arms reach.

    NOT `importorskip`: that turned this file into `1 skipped` — a green run asserting nothing,
    which is the exact shape of guard this suite exists to refuse. A stub that fails to satisfy
    the import must ERROR here, loudly.
    """
    import types
    if "baml_client" not in sys.modules:
        _stub = types.ModuleType("baml_client")
        _stub.b = types.SimpleNamespace()
        # A PACKAGE, not a bare module. `tests/conftest.py` names "a bare ModuleType with no
        # `__path__`" as the defect shape shared by five files: a submodule import against it
        # fails with "is not a package" rather than with a missing-module error, which is a
        # far worse message to debug. An empty `__path__` costs nothing and makes this stub
        # not the sixth instance of that shape.
        _stub.__path__ = []  # type: ignore[attr-defined]
        sys.modules["baml_client"] = _stub
    import agent_fleet.presentation_agent.main as _m
    return _m


def _pf():
    """The engine-F module, imported on first use. See `_import_engine_f`'s docstring."""
    return _import_engine_f()


# ── the wrapper cortex-bff actually sends, copied from gateway.py's `_results` ──────────
def _wrapper(sub_query="which account is driving the overrun on NP-MERIDIAN", **extra):
    w = {
        "persona": "PROGRAM_FINANCE_ANALYST",
        "user_persona": "PROGRAM_FINANCE_ANALYST",
        "answerer_persona": "PROGRAM_FINANCE_ANALYST",
        "predicate_verb_iri": "fin:variance_drivers",
        "sub_query": sub_query,
        "route_status": "matched",
        "expert_response": {"refused": True, "outcome": "vintage_required",
                            "reason": "no rate set for FY2022", "slot": "vintage",
                            "available": ["2021-02-01", "2022-02-01"]},
    }
    w.update(extra)
    return [w]


_REF = {"refused": True, "outcome": "vintage_required", "reason": "no rate set for FY2022"}


def _option_bearing_cards():
    """Every ELICITATION this module can emit WITH options, one call per producer.

    Built by calling the real producers rather than by asserting on source text, so an arm
    here fails on BEHAVIOUR. Keyed by producer name for legible failure messages.
    """
    return {
        "_render_refusal_menu": _pf()._render_refusal_menu(
            _REF, ["2021-02-01", "2022-02-01"], "vintage", "PROGRAM_FINANCE_ANALYST",
            _wrapper(),
        )["components"][0],
        "_render_abstain_menu": _pf()._render_abstain_menu(
            {"message": "which of these did you mean?"},
            ["fin:variance_drivers", "fin:burn_rate"], "PROGRAM_FINANCE_ANALYST",
            _wrapper(),
        )["components"][0],
        # ── THE THIRD PRODUCER, AND THE ONE THAT ACTUALLY SERVES PRODUCTION'S ASKS ──────
        #
        # Added 2026-09-27 after roll #5: the live docs ELICITATION cards come from HERE, not
        # from the two above. It is TABLE-DRIVEN (`_FLAT_ARCHETYPES["ELICITATION"]`) rather
        # than a dict literal, which is exactly why the derivation in
        # `test_every_option_bearing_producer_is_covered` could not see it — see that arm.
        #
        # ⛔ EXERCISED WITH AN ENVELOPE THAT LACKS THE PHRASE, DELIBERATELY. Production's only
        # current envelope builder (`slot_disposition.py:619`) sets `sub_query` itself, so a
        # fixture copied from it would pass no matter what this producer did: it would control
        # the logic and not whether the logic still points at anything. The population is "an
        # envelope carrying options", and NOTHING forces a member of it to carry the phrase —
        # `cost_agent`'s refusals, measured, carry `slot` and `available` and no `sub_query` at
        # all (0 occurrences in that file). They reach a card through `_render_refusal_menu`
        # today; the day one reaches this projector instead, this fixture is that turn.
        "_project_flat_archetype": _pf()._project_flat_archetype(
            "ELICITATION",
            _wrapper(expert_response={
                "slot": "rate_vintage",
                "options": [{"value": "2021-02-01", "label": "FY2021"}],
                "option_source": "refusal",
            }),
            "PROGRAM_FINANCE_ANALYST",
        ),
    }


def test_every_option_bearing_card_carries_sub_query():
    """THE ARM THE DISPATCH ASKED FOR. An option on the wire without `sub_query` reds.

    `sub_query` IS on the wire (both callers send it), so this is unconditional — no
    "if present" escape. A producer that drops it leaves the surface unable to say which
    question the menu belongs to, and leaves the free-text arm of `answer_ask` with no phrase.
    """
    for name, card in _option_bearing_cards().items():
        assert card.get("options"), f"{name}: fixture no longer puts options on the wire"
        assert card.get("sub_query"), (
            f"{name} emitted {len(card['options'])} option(s) with no `sub_query`. "
            f"The wrapper carried one. Card keys: {sorted(card)}"
        )


def test_accepted_slots_is_carried_WHEN_the_wire_has_it():
    """The conditional half: present on the wire means present on the card.

    This is the arm that will matter the day a caller starts sending the field — it passes
    today against a synthetic wrapper, and it is what stops the producer from ignoring a real
    one. The values must survive INTACT: a re-route rebuilds `{**accepted, slot: value}`, so a
    dropped or rewritten entry is a slot the user must answer twice.
    """
    accepted = {"program_id": "NP-MERIDIAN", "period": "FY2022"}
    card = _pf()._render_refusal_menu(
        _REF, ["2021-02-01"], "vintage", "PROGRAM_FINANCE_ANALYST",
        _wrapper(accepted_slots=accepted),
    )["components"][0]
    assert card.get("accepted_slots") == accepted, (
        "the wrapper carried accepted_slots and the card did not reproduce them exactly; "
        f"got {card.get('accepted_slots')!r}"
    )


def test_accepted_slots_is_ABSENT_rather_than_EMPTY_when_the_wire_lacks_it():
    """⛔ THE ARM THAT FORBIDS THE EASY FIX, and the reason this file is not one assert longer.

    `{}` is not a weaker version of the right answer, it is a different and false one:
    `answer_ask` computes `{**accepted, slot: value}`, so `accepted == {}` produces a re-route
    that has DROPPED every previously-bound slot, silently and with no error. A card that OMITS
    the key lets a consumer refuse; a card that defaults it hands the consumer a confident lie.

    If a future change makes `accepted_slots` genuinely always available, this arm reds — and
    the correct response is to DELETE it along with the conditional in
    `_reroute_fields`, not to weaken it.
    """
    card = _pf()._render_refusal_menu(
        _REF, ["2021-02-01"], "vintage", "PROGRAM_FINANCE_ANALYST", _wrapper(),
    )["components"][0]
    assert "accepted_slots" not in card, (
        "the wrapper carried NO accepted_slots, so the card must omit the key rather than "
        f"default it to {card.get('accepted_slots')!r} — see this test's docstring."
    )


def test_the_wire_gap_is_real_and_is_PINNED_to_the_wrapper_that_feeds_it():
    """THE GAP ITSELF, asserted so it cannot be believed closed while it is open — and so the
    `_wrapper()` fixture above cannot drift away from the thing it claims to imitate.

    ANCHORED ON THE CONSTRUCT, NOT ON AN OFFSET. An earlier version of this arm took a
    fixed-size window after the `/render_ui` POST and asked whether `sub_query` was in it. It
    red against correct code: the POST body is `json={"raw_data": _results, ...}` and the
    wrapper carrying `sub_query` is built ~25 lines EARLIER, outside the window. A window is a
    position; `_results = [{` is the object. The lesson is the arm's, not the gateway's.

    Two claims, both about `gateway.py`'s `_results` wrapper — the shape `_wrapper()` above
    copies and the shape `_wrapper_field` reads:

      1. it carries `sub_query`   -> the unconditional arm is satisfiable, and the fixture is faithful
      2. it does NOT carry `accepted_slots` -> the conditional in `_reroute_fields` is justified

    When (2) stops holding, this reds. That is the notification that the conditional and
    `test_accepted_slots_is_ABSENT_rather_than_EMPTY_when_the_wire_lacks_it` can both go.
    """
    src = io.open(_REPO / "src" / "iagent" / "gateway.py", encoding="utf-8").read()
    anchor = "_results = [{"
    assert src.count(anchor) == 1, (
        f"expected exactly one `{anchor}` in gateway.py, found {src.count(anchor)} — "
        "re-derive this arm's anchor rather than picking one by position"
    )
    i = src.index(anchor)
    # the literal ends at its closing `}]`; bounded so a later unrelated dict cannot be read in
    j = src.index("}]", i)
    wrapper = src[i:j]

    assert '"sub_query"' in wrapper, (
        "gateway.py's /render_ui wrapper no longer carries `sub_query`, so "
        "test_every_option_bearing_card_carries_sub_query is asserting against a shape the "
        f"wire does not send. Wrapper literal: {wrapper}"
    )
    assert '"accepted_slots"' not in wrapper, (
        "gateway.py's /render_ui wrapper now carries `accepted_slots`. The conditional in "
        "`_reroute_fields` and the ABSENT-not-EMPTY arm exist ONLY because it did not. Make the "
        "field unconditional and delete both, then delete this assertion."
    )


def test_the_envelope_WINS_and_the_wrapper_only_fills_a_hole():
    """The precedence of the fill added to `_project_flat_archetype`, both directions.

    A FILL AND AN OVERRIDE ARE DIFFERENT CHANGES and only one of them is wanted. The producer
    that computed the ask knows more than the wrapper: `slot_disposition` sets `sub_query` from
    the sub-question it was actually resolving, which on a decomposed turn is NOT the user's
    whole message. So a wrapper value must never displace an envelope value — it may only fill
    a hole.

    Without this arm, `setdefault` -> `component[k] = v` passes every other arm in this file and
    silently replaces the sub-question with the parent phrase on every decomposed ask.
    """
    both = _pf()._project_flat_archetype(
        "ELICITATION",
        _wrapper("THE WRAPPER PHRASE", expert_response={
            "slot": "rate_vintage", "sub_query": "THE ENVELOPE PHRASE",
            "options": [{"value": "2021-02-01", "label": "FY2021"}],
        }),
        "PROGRAM_FINANCE_ANALYST",
    )
    assert both["sub_query"] == "THE ENVELOPE PHRASE", (
        "the wrapper's phrase displaced the envelope's. The fill must be a `setdefault`: on a "
        f"decomposed turn this silently swaps the sub-question for the parent. Got {both['sub_query']!r}"
    )

    hole = _pf()._project_flat_archetype(
        "ELICITATION",
        _wrapper("THE WRAPPER PHRASE", expert_response={
            "slot": "rate_vintage",
            "options": [{"value": "2021-02-01", "label": "FY2021"}],
        }),
        "PROGRAM_FINANCE_ANALYST",
    )
    assert hole["sub_query"] == "THE WRAPPER PHRASE", (
        "the envelope carried no phrase and the wrapper's did not fill the hole — the card "
        f"cannot be re-routed. Got {hole.get('sub_query')!r}"
    )

    # AND THE FILL MUST NOT REACH THE OTHER FLAT ARCHETYPE. `accepted_slots` is declared on
    # ELICITATION only; a NAMED_HOLE that acquired one would be inventing a field its contract
    # does not have, and `cortex-ui`'s registry reads these by name.
    hole_card = _pf()._project_flat_archetype(
        "NAMED_HOLE",
        _wrapper(accepted_slots={"program_id": "NP-MERIDIAN"},
                 expert_response={"disposition": "unentitled", "reason": "no grant"}),
        "PROGRAM_FINANCE_ANALYST",
    )
    assert hole_card is not None, "fixture no longer draws a NAMED_HOLE; re-derive it"
    assert "accepted_slots" not in hole_card and "sub_query" not in hole_card, (
        "the ELICITATION-only fill leaked into NAMED_HOLE: "
        f"{sorted(set(hole_card) & {'sub_query', 'accepted_slots'})}"
    )


def test_every_option_bearing_producer_is_covered():
    """DERIVE THE POPULATION, DO NOT LIST IT.

    The lot-3 report named one producer; there were two. This arm AST-walks the module for
    every function whose returned component dict literal sets `options`, and asserts the set is
    exactly what `_option_bearing_cards()` exercises. A third producer reds here rather than
    inheriting the defect in silence — which is what "an option on the wire" means as a
    population rather than as a line number.
    """
    tree = ast.parse(io.open(_PRESENTATION, encoding="utf-8").read())

    # ── SHAPE 2 FIRST: the DECLARATION TABLES that name `options` as a field ────────────
    # `_FLAT_ARCHETYPES` is one. Derived rather than named, so a second table is found the
    # same way — and an AnnAssign (`_FLAT_ARCHETYPES: Dict[str, tuple] = {...}`) is a
    # different node type from a plain Assign, which is the kind of detail that silently
    # halves a census.
    tables = set()
    for node in tree.body:
        targets = (
            node.targets if isinstance(node, ast.Assign)
            else [node.target] if isinstance(node, ast.AnnAssign) else []
        )
        if node.__class__ not in (ast.Assign, ast.AnnAssign) or node.value is None:
            continue
        if any(isinstance(c, ast.Constant) and c.value == "options"
               for c in ast.walk(node.value)):
            tables.update(t.id for t in targets if isinstance(t, ast.Name))
    assert tables, (
        "no module-level table names `options` any more. This derivation's SECOND shape has "
        "gone blind — re-derive it rather than letting it silently fall back to shape 1."
    )

    literal, tabled, calls = {}, {}, {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Dict) and any(
                isinstance(k, ast.Constant) and k.value == "options" for k in sub.keys
            ):
                literal[node.name] = node.lineno
            if isinstance(sub, ast.Name) and sub.id in tables:
                tabled[node.name] = node.lineno
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name):
                calls.setdefault(node.name, set()).add(sub.func.id)

    emitters = set(literal) | set(tabled)

    # ── THE EXEMPTION, MADE CHECKABLE RATHER THAN A LIST OF NAMES ───────────────────────
    # The old version subtracted `{"_as_options", "render_ui"}` — a literal allowlist, which is
    # the shape where one appended name retires the assertion. A FORWARDER is derivable: it
    # builds no `{"options": ...}` of its own AND it calls another derived emitter, i.e. it
    # returns somebody else's card. `_render_archetype_hardened` is one (it tests membership in
    # `_FLAT_ARCHETYPES` and delegates to `_project_flat_archetype`, main.py:1063-1064).
    forwarders = {
        n for n in emitters
        if n not in literal and (calls.get(n, set()) & emitters)
    }
    producers = emitters - forwarders

    covered = set(_option_bearing_cards())
    assert producers == covered, (
        "the set of producers that put `options` on a card has changed.\n"
        f"  shape 1, dict literal with an 'options' key : {sorted(literal)}\n"
        f"  shape 2, reads a table naming 'options'     : {sorted(tabled)}\n"
        f"  forwarders (derived, not listed)            : {sorted(forwarders)}\n"
        f"  => producers : {sorted(producers)}\n"
        f"     covered   : {sorted(covered)}\n"
        "Add the new producer to `_option_bearing_cards()` and make it carry the re-route "
        "fields, or remove the stale name."
    )

    # ⚠ THE TAIL THIS DERIVATION STILL CANNOT SEE, enumerated rather than implied. Two shapes
    # are two shapes, not all of them: a card assembled by `dict(...)`/`.update()`, one whose
    # field names arrive as a parameter, or one built in ANOTHER MODULE would all escape. That
    # is why the arms above call the real producers instead of reading source — this arm bounds
    # the population, it does not define the property. The defect that prompted the repair was
    # exactly this: "derived, not listed" still hard-codes one way of writing a producer.
    assert not (forwarders & set(literal)), (
        f"a forwarder that also builds its own options dict: {sorted(forwarders & set(literal))}. "
        "The forwarder test has stopped discriminating — it must not excuse a real producer."
    )
