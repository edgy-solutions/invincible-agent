"""A NAMED_HOLE draws only for `unentitled`, and the producer enforces that rather than describing it.

THE DEFECT, and it is R-072's third kind in its purest form. `_FLAT_ARCHETYPES["NAMED_HOLE"]`
required `disposition` to be PRESENT and the projector never looked at what it SAID. Four lines
above it, a comment asserted the opposite:

    # ONLY `disposition` IS REQUIRED, and the card refuses anything but `unentitled`: an
    # unavailable verb refuses the whole board and an empty result draws its own rowless card,
    # so drawing a hole for those would erase the distinction between three different answers.

**That sentence describes the CARD.** It sat in the producer, next to code that performed none of
it, inheriting the authority of every green run in the file. A producer emitting
`disposition: "unsummarised"` would have drawn a named hole, and the only thing that would have
caught it is `validateNamedHole` in another repo at the far end of the wire.

**AND THE ONE ERROR HERE CANNOT BE TAKEN BACK.** A hole says *the caller may not invoke this
panel's verb*. Drawing one for an entitled caller tells a reader they lack access they hold.

WHY IT WENT LIVE TODAY. R-073 ruled a fourth disposition — `unsummarised`, content exists and
verdict absent — for brief rows whose verb RAN and produced an artifact but emitted no quotable
verdict. `cortex-ui-60` landed the contract half refusing it by name; lane 32 is about to start
emitting it. Until this arm, the producer would have passed it straight through.

THREE OUTCOMES NEED THREE MESSAGES, which `cortex-ui-60` found on their own side while adding the
term and is the reason this file checks messages and not only refusals:

    absent         a required field was omitted            -> fix the producer   (warning)
    NOT A HOLE     understood, another surface draws it     -> NOTHING IS WRONG  (info)
    unrecognised   means nothing to this vocabulary         -> fix the producer  (warning)

> **The middle one is not a mistake at all.** Reporting a correct routing decision in the words of
> a parse failure sends someone to fix something that is not broken.

Run: uv run --frozen pytest tests/test_a_hole_is_drawn_only_for_the_disposition_that_means_one.py -v
"""
from __future__ import annotations

import importlib.util
import logging
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_MAIN = _REPO / "agent_fleet" / "presentation_agent" / "main.py"


@pytest.fixture(scope="module")
def mod():
    """The REAL module, with its unavailable import stubbed — not its source parsed.

    `presentation_agent.main` imports `baml_client`, which is not installed here, and the
    established pattern elsewhere in this suite is to parse the table out of the source. That is
    right for asserting a table's CONTENTS and wrong for this file: the defect being sealed was a
    sentence in the source that the code did not implement, so a seal reading the source could
    have been satisfied by the very comment that was lying. The function has to run.

    The stub answers any attribute, because nothing on this path touches the model client — a
    flat projection is deterministic by contract. If that ever stops being true this fixture
    fails loudly at import rather than quietly projecting something a model decided.
    """
    import sys
    import types

    class _Any(types.ModuleType):
        def __getattr__(self, name):  # noqa: D105
            return type(name, (), {"__getattr__": lambda s, n: None})()

    installed = []
    for name in ("baml_client", "baml_client.types", "baml_client.async_client"):
        if name not in sys.modules:
            sys.modules[name] = _Any(name)
            installed.append(name)
    try:
        spec = importlib.util.spec_from_file_location("presentation_probe", _MAIN)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        yield m
    finally:
        for name in installed:
            sys.modules.pop(name, None)


def _hole(disposition: str) -> dict:
    return {"archetype": "NAMED_HOLE", "disposition": disposition, "panel_label": "Cost"}


def test_UNENTITLED_DRAWS(mod):
    """THE POSITIVE CONTROL. Without it every refusal below is satisfied by a projector that
    refuses everything, which is the same card-shaped nothing it exists to prevent."""
    out = mod._project_flat_archetype("NAMED_HOLE", _hole("unentitled"), "COST_ANALYST")
    assert out is not None, "the one disposition that MEANS a hole no longer draws one"
    assert out["archetype"] == "NAMED_HOLE"
    assert out["disposition"] == "unentitled"


@pytest.mark.parametrize("disposition", ["unavailable", "empty", "unsummarised"])
def test_EVERY_OTHER_DECLARED_DISPOSITION_IS_REFUSED(mod, disposition):
    """Each has its own surface — a whole-board refusal, a rowless card, a finding row. Drawing
    any of them as a hole tells an entitled reader they lack access."""
    assert mod._project_flat_archetype("NAMED_HOLE", _hole(disposition), "COST_ANALYST") is None


def test_AN_UNDECLARED_DISPOSITION_IS_REFUSED(mod):
    """A value nobody declared cannot be routed anywhere, so it is a producer defect rather than
    a routing outcome."""
    assert mod._project_flat_archetype("NAMED_HOLE", _hole("made_up"), "COST_ANALYST") is None


@pytest.fixture
def emitted(mod):
    """Records from the module's OWN logger.

    `presentation_agent` sets `propagate = False` on purpose, so `caplog` sees nothing — which is
    also why reading these messages out of a pod has failed before. Attaching a handler to the
    named logger measures what the module actually emits, through the path it actually uses,
    instead of asserting against a logger it does not write to.
    """
    captured: list = []

    class _Sink(logging.Handler):
        def emit(self, record):
            captured.append(record)

    target = logging.getLogger("presentation_agent")
    sink = _Sink()
    prev = target.level
    target.addHandler(sink)
    target.setLevel(logging.INFO)
    try:
        yield captured
    finally:
        target.removeHandler(sink)
        target.setLevel(prev)


def test_THE_NOT_A_HOLE_CASE_IS_NOT_REPORTED_AS_A_DEFECT(mod, emitted):
    """THE ARM WITH TEETH, and the one a refusal-only seal would miss entirely.

    `unsummarised` is understood and belongs on another surface. Refusing it is correct; calling
    that refusal a defect is not. A producer reading a warning here would go and change a payload
    that is right.
    """
    assert mod._project_flat_archetype("NAMED_HOLE", _hole("unsummarised"), "COST_ANALYST") is None
    rec = [r for r in emitted if "unsummarised" in r.getMessage()]
    assert rec, "the understood-but-elsewhere case said nothing at all"
    assert all(r.levelno < logging.WARNING for r in rec), (
        "a correct routing decision is being reported at WARNING, in the words of a parse "
        "failure — the producer will go and fix something that is not broken"
    )
    assert any("nothing to fix" in r.getMessage() for r in rec)


def test_AN_UNDECLARED_VALUE_IS_REPORTED_AS_A_DEFECT(mod, emitted):
    """The other side of the same distinction: this one IS the producer's to fix, so it must not
    be whispered at INFO beside the routing case."""
    mod._project_flat_archetype("NAMED_HOLE", _hole("made_up"), "COST_ANALYST")
    rec = [r for r in emitted if "made_up" in r.getMessage()]
    assert rec, "an undeclared disposition was refused silently"
    assert any(r.levelno >= logging.WARNING for r in rec), (
        "an undeclared disposition is reported at INFO, so a real producer defect reads like a "
        "routing note"
    )


def test_THE_VOCABULARY_IS_DECLARED_ONCE_AND_THE_HOLE_SUBSET_IS_NARROWER(mod):
    """Two names rather than one, because `which values exist` and `which values draw a hole`
    are different questions and collapsing them is how the next disposition quietly draws one."""
    assert "unsummarised" in mod._DISPOSITIONS, "R-073's disposition is not in the vocabulary"
    assert mod._HOLE_DISPOSITIONS == frozenset({"unentitled"}), (
        "the set of dispositions that may draw a hole has changed; that is a decision about "
        "what a hole MEANS, not a widening"
    )
    assert mod._HOLE_DISPOSITIONS < mod._DISPOSITIONS


def test_THE_COMMENT_NO_LONGER_DESCRIBES_A_GUARD_THIS_FILE_LACKS():
    """The original sentence was true of the card and false of the file it lived in. An arm on the
    prose, because that is precisely what had no arm."""
    src = _MAIN.read_text(encoding="utf-8")
    assert "_HOLE_DISPOSITIONS" in src, "the enforcing constant is gone; the comment is prose again"
    i = src.index("_DISPOSITIONS: frozenset")
    assert "R-072's third kind" in src[:i], (
        "the record of WHY this is enforced rather than described has been removed, and the next "
        "reader will collapse the two sets back together"
    )
