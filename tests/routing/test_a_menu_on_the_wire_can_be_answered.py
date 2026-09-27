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

`accepted_slots` is NOT ON THE WIRE TODAY. Measured 2026-09-26: `/render_ui`'s two callers
(`src/iagent/gateway.py`'s `_results` wrapper, `src/iagent/defs/dynamic_supervisor.py`'s POST
body) both send `sub_query` and neither sends `accepted_slots`; the accepted set exists in
`direct_dispatch` only as a Dagster materialization. A seal demanding the key would be
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


def test_every_option_bearing_producer_is_covered():
    """DERIVE THE POPULATION, DO NOT LIST IT.

    The lot-3 report named one producer; there were two. This arm AST-walks the module for
    every function whose returned component dict literal sets `options`, and asserts the set is
    exactly what `_option_bearing_cards()` exercises. A third producer reds here rather than
    inheriting the defect in silence — which is what "an option on the wire" means as a
    population rather than as a line number.
    """
    tree = ast.parse(io.open(_PRESENTATION, encoding="utf-8").read())
    emitters = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Dict) and any(
                isinstance(k, ast.Constant) and k.value == "options" for k in sub.keys
            ):
                emitters.add(node.name)
                break

    covered = set(_option_bearing_cards())
    # `_as_options` builds the option list itself and emits no card; render_ui only forwards.
    emitters -= {"_as_options", "render_ui"}
    assert emitters == covered, (
        "the set of producers that put `options` on a card has changed.\n"
        f"  emit options   : {sorted(emitters)}\n"
        f"  covered here   : {sorted(covered)}\n"
        "Add the new producer to `_option_bearing_cards()` (and give it `**_reroute_fields(...)`), "
        "or remove the stale name."
    )
