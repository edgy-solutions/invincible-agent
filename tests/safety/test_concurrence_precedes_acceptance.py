"""ADR-0051 §5.1 — a Serious or High hazard cannot reach an acceptance without a `concurred` first.

**THE SEAL MOVED, AND THIS IS IT RE-PROVEN AT THE NEW ADDRESS.** It used to assert this property
over engine code: `_CONCURRENCE_LEVELS` held the level set and branched on it, and
`acceptance_request_after_concurrence` refused to build an acceptance until a disposed `concurred`
existed. Both are gone — ADR-0039's amendment applied to its own first consumer, *an engine computes
facts and never chooses what happens next* — so the property now lives in the **composed decision
tables**, and a seal left pointed at the removed functions would have gone red for the right reason
and been "fixed" by deletion.

A seal that moves and is not re-proven has only been relocated. The mutations at the bottom rewrite
the composed YAML and re-run the assertions against it, so what is shown discriminating is the
instrument in its new position rather than the one it replaced.

── THE PROPERTY, RESTATED AS REACHABILITY ──────────────────────────────────────────────────────
MIL-STD-882E §4.3.7 requires the user representative's formal concurrence BEFORE every Serious and
High acceptance. On this rail that is not a guard anyone could forget — it is a fact about which
definitions are reachable from where:

    selection   Serious/High  -> safety_concurrence          (never the acceptance)
                Medium/Low    -> safety_acceptance_direct
    chaining    concurred     -> safety_acceptance_direct
                not_concurred / returned_for_rework -> safety_redraft

So for those two levels the acceptance is reachable ONLY through a `concurred` row. **Both halves
are load-bearing and they fail differently**: break the first and the concurrence is skipped
outright; break the second and a REFUSAL still reaches a signature, which is §4.3.7 satisfied on
paper and defeated in fact — the exact behaviour the two-act definition was deleted for.

── WHAT IS ASSERTED ABOUT THE ENGINE ───────────────────────────────────────────────────────────
That it no longer decides this. Stated as an assertion rather than left to a reader's memory of a
commit, because the failure mode of the constant coming back is not a duplicate — it is the choice
living in two places that disagree silently, with the engine's copy winning because it runs first.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[2]
# COMPOSED, not read from one directory (ADR-0036). The seed layer carries no safety tables today;
# reading only the overlay would be right by accident and would stop being right the moment a seed
# table appeared — and full-replacement-by-key means the seed's copy would be the one NOT running.
_DECISION_DIRS = (
    _REPO / "policy" / "decisions",
    _REPO / "policy" / "overlays" / "sample" / "decisions",
)
_WORKFLOWS = _REPO / "policy" / "workflows"

_SELECTION = "safety_acceptance_selection.yaml"
_CHAINING = "safety_concurrence_chaining.yaml"

_ACCEPTANCE = "safety_acceptance_direct"
_CONCURRENCE = "safety_concurrence"
_REDRAFT = "safety_redraft"

#: The levels §4.3.7 names. Held here as the SEAL'S OWN expectation of the standard — deliberately
#: not read from the table, because a seal taking its expectation from its subject would agree with
#: any tailoring, including one that removed the requirement entirely.
_LEVELS_REQUIRING_CONCURRENCE = ("High", "Serious")
_LEVELS_WITHOUT = ("Medium", "Low")


def _dirs() -> tuple[Path, ...]:
    """Indirected so a mutation can point the whole seal at a rewritten copy of the real tables."""
    return _DECISION_DIRS


def _point_at(monkeypatch, dirs: tuple[Path, ...]) -> None:
    """Redirect every reader in this file at `dirs`.

    Takes the tuple ALREADY BUILT rather than a factory, and the first version did the opposite:
    `lambda: _mutated_dirs(...)`. `_dirs()` is called once per assertion, so the mutation was
    rebuilt on every call — the second `mkdir` raised FileExistsError and the reds came from the
    harness rather than from the edit under test. **A fixture whose cost is paid per read is a
    different fixture on the second read.**
    """
    monkeypatch.setattr(sys.modules[__name__], "_dirs", lambda: dirs)


def _composed(filename: str) -> dict:
    """The table as it composes: a later layer REPLACES the earlier one wholesale, by key."""
    out: dict = {}
    for d in _dirs():
        p = d / filename
        if p.is_file():
            out = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return out


def _routes(filename: str, attribute: str) -> dict:
    """`when[attribute]` -> `then`, over the composed table."""
    return {r["when"][attribute]: r["then"] for r in (_composed(filename).get("rows") or [])}


# ---------------------------------------------------------------------------
# THE SUBJECT MUST BE THERE
# ---------------------------------------------------------------------------

def test_the_subject_exists_so_nothing_below_is_vacuous():
    """A relocated seal's characteristic failure is passing over a subject that moved out from
    under it — every dict empty, every membership test trivially satisfied."""
    assert _routes(_SELECTION, "level"), "the composed selection table yielded no rows"
    assert _routes(_CHAINING, "outcome"), "the composed chaining table yielded no rows"
    for d in (_ACCEPTANCE, _CONCURRENCE, _REDRAFT):
        assert (_WORKFLOWS / f"{d}.yaml").is_file(), f"{d} is not authored — the route ends nowhere"


# ---------------------------------------------------------------------------
# HALF ONE — THE LEVEL IS ROUTED AWAY FROM THE ACCEPTANCE
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("level", _LEVELS_REQUIRING_CONCURRENCE)
def test_a_concurrence_level_is_not_routed_straight_to_an_acceptance(level):
    """If selection sent Serious or High to the acceptance, the concurrence would be skippable no
    matter what any later row said — the standard's "before" defeated at the first hop."""
    selected = _routes(_SELECTION, "level").get(level)
    assert selected is not None, (
        f"{level} falls through with no definition selected — the acceptance of a {level} risk "
        "would be due and nothing would open"
    )
    assert selected != _ACCEPTANCE, (
        f"{level} is routed straight to {_ACCEPTANCE!r}; §4.3.7 requires the user representative's "
        "concurrence FIRST"
    )
    assert selected == _CONCURRENCE, (
        f"{level} selects {selected!r} rather than {_CONCURRENCE!r} — routed away from the "
        "acceptance but not to the act the standard requires"
    )


@pytest.mark.parametrize("level", _LEVELS_WITHOUT)
def test_the_control_medium_and_low_still_reach_an_acceptance_in_one_act(level):
    """THE CONTROL. Without it this file passes on a table that routed EVERY level through a
    concurrence — which is its own defect: §4.3.7 names Serious and High, and inventing a step
    where none is required is as wrong as omitting one where it is."""
    assert _routes(_SELECTION, "level").get(level) == _ACCEPTANCE, (
        f"{level} was given a concurrence step the standard does not require"
    )


# ---------------------------------------------------------------------------
# HALF TWO — EXACTLY ONE WAY BACK, AND IT IS `concurred`
# ---------------------------------------------------------------------------

def test_the_acceptance_is_reachable_from_the_concurrence_ONLY_via_concurred():
    routes = _routes(_CHAINING, "outcome")
    reaching = sorted(k for k, v in routes.items() if v == _ACCEPTANCE)
    assert reaching == ["concurred"], (
        f"the acceptance is reachable from concurrence outcome(s) {reaching} — it must be reachable "
        "from `concurred` and from nothing else, or a refusal still reaches a signature"
    )


@pytest.mark.parametrize("refusal", ["not_concurred", "returned_for_rework"])
def test_a_refusal_goes_back_to_the_author_and_not_onward(refusal):
    """Stated separately from the row above because it fails differently and reads differently in
    a report: that one is an over-broad route, this names the act being prevented."""
    routes = _routes(_CHAINING, "outcome")
    assert refusal in routes, f"{refusal} has no chaining row — a disposed refusal routes nowhere"
    assert routes[refusal] != _ACCEPTANCE, (
        f"`{refusal}` routes to the acceptance — the user representative's refusal would be "
        "recorded and then ignored"
    )
    assert routes[refusal] == _REDRAFT


def test_the_two_halves_compose_into_the_property_itself():
    """Asserted as one statement, because each half alone is satisfiable by a configuration that
    violates the requirement — and it is the CONJUNCTION that ADR-0051 §5.1 claims."""
    selection = _routes(_SELECTION, "level")
    chaining = _routes(_CHAINING, "outcome")
    for level in _LEVELS_REQUIRING_CONCURRENCE:
        first = selection.get(level)
        assert first != _ACCEPTANCE, f"{level} reaches an acceptance in one act"
        onward = (
            {k for k, v in chaining.items() if v == _ACCEPTANCE}
            if first == _CONCURRENCE
            else set()
        )
        assert onward == {"concurred"}, (
            f"for {level} the only path to an acceptance is via {sorted(onward) or 'NOTHING'} — "
            "§5.1 requires it to be exactly `concurred`"
        )


# ---------------------------------------------------------------------------
# THE MUTATIONS — RUN, AGAINST THE COMPOSED TABLE
# ---------------------------------------------------------------------------

def _mutated_dirs(tmp_path, filename, replacements):
    """Copy the REAL composed tables, rewrite one, and return dirs pointing at the copy.

    The mutation goes through the same YAML parse and the same composition the seal uses, so what
    is shown discriminating is the whole instrument — not a stubbed reader standing in for it. Each
    anchor is asserted present first: a replacement that matched nothing would make the mutation a
    no-op, and a no-op mutation that "fails to be caught" is a fixture result, not a finding.
    """
    dst = tmp_path / "decisions"
    dst.mkdir()
    for d in _DECISION_DIRS:
        if d.is_dir():
            for p in d.glob("*.yaml"):
                shutil.copy2(p, dst / p.name)
    target = dst / filename
    text = target.read_text(encoding="utf-8")
    for old, new in replacements:
        assert old in text, (
            f"the mutation's anchor is not present in {filename} — the mutation would be a no-op "
            f"and the red below would mean nothing:\n{old!r}"
        )
        text = text.replace(old, new, 1)
    target.write_text(text, encoding="utf-8")
    return (dst,)


def test_mutation_routing_High_straight_to_the_acceptance_is_caught(tmp_path, monkeypatch):
    """The plausible wrong edit: a programme "simplifying" its selection table."""
    _point_at(
        monkeypatch,
        _mutated_dirs(
            tmp_path,
            _SELECTION,
            [
                (
                    "- when: {level: High}\n    then: safety_concurrence",
                    "- when: {level: High}\n    then: safety_acceptance_direct",
                )
            ],
        ),
    )
    with pytest.raises(AssertionError, match="requires the user representative"):
        test_a_concurrence_level_is_not_routed_straight_to_an_acceptance("High")
    with pytest.raises(AssertionError, match="reaches an acceptance in one act"):
        test_the_two_halves_compose_into_the_property_itself()
    # THE CONTROL STAYS GREEN under this mutation. A mutation that reddened everything would prove
    # the harness noisy rather than these assertions discriminating.
    test_the_control_medium_and_low_still_reach_an_acceptance_in_one_act("Medium")


def test_mutation_routing_a_refusal_to_the_acceptance_is_caught(tmp_path, monkeypatch):
    """The subtler wrong edit, and the one matching the deleted two-act definition's behaviour
    exactly: the refusal is disposed, recorded, and the acceptance opens anyway."""
    _point_at(
        monkeypatch,
        _mutated_dirs(
            tmp_path,
            _CHAINING,
            [
                (
                    "- when: {outcome: not_concurred}\n    then: safety_redraft",
                    "- when: {outcome: not_concurred}\n    then: safety_acceptance_direct",
                )
            ],
        ),
    )
    with pytest.raises(AssertionError, match="recorded and then ignored"):
        test_a_refusal_goes_back_to_the_author_and_not_onward("not_concurred")
    with pytest.raises(AssertionError, match="reachable from concurrence outcome"):
        test_the_acceptance_is_reachable_from_the_concurrence_ONLY_via_concurred()
    # HALF ONE IS UNTOUCHED BY THIS MUTATION, and that is precisely why both are asserted: selection
    # still routes High away from the acceptance, so a seal holding only that half would be GREEN
    # on a table where a refusal reaches a signature.
    test_a_concurrence_level_is_not_routed_straight_to_an_acceptance("High")


def test_mutation_deleting_the_High_row_entirely_is_caught(tmp_path, monkeypatch):
    """A gap rather than a wrong target. Distinct from the first mutation because a missing row
    reads as an oversight and a wrong row reads as a decision — and the seal must name the level
    either way, rather than raising KeyError somewhere without saying which level fell through."""
    _point_at(
        monkeypatch,
        _mutated_dirs(
            tmp_path,
            _SELECTION,
            [("  - when: {level: High}\n    then: safety_concurrence\n", "")],
        ),
    )
    with pytest.raises(AssertionError, match="falls through with no definition"):
        test_a_concurrence_level_is_not_routed_straight_to_an_acceptance("High")


def test_the_mutation_harness_leaves_an_unmutated_copy_green(tmp_path, monkeypatch):
    """THE CONTROL FOR THE MUTATIONS THEMSELVES. Copying and re-composing must change no verdict —
    otherwise the three reds above would be evidence about the harness, not about the edits."""
    _point_at(monkeypatch, _mutated_dirs(tmp_path, _SELECTION, [("rows:", "rows:")]))
    test_the_subject_exists_so_nothing_below_is_vacuous()
    test_a_concurrence_level_is_not_routed_straight_to_an_acceptance("High")
    test_the_acceptance_is_reachable_from_the_concurrence_ONLY_via_concurred()
    test_the_two_halves_compose_into_the_property_itself()


# ---------------------------------------------------------------------------
# THE REMOVAL, ASSERTED
# ---------------------------------------------------------------------------

def test_the_engine_no_longer_holds_this_choice():
    """`_CONCURRENCE_LEVELS` and `acceptance_request_after_concurrence` are out of the engine.

    Asserted, not remembered. If either returns, the choice is in two places at once: a table a
    programme can tailor and a constant it cannot, disagreeing silently, with the engine's copy
    winning because it runs first — and every other assertion in this file would still be green.

    Matched on the DEFINING form rather than the bare names, because the module's own comment
    records the removal by name and a substring check would flag the comment explaining the fix.
    """
    src = (_REPO / "agent_fleet" / "safety_agent" / "measures.py").read_text(encoding="utf-8")
    assert "_CONCURRENCE_LEVELS =" not in src, (
        "the engine holds the concurrence level set again — that is a decision-table row"
    )
    assert "def acceptance_request_after_concurrence" not in src, (
        "the engine gates the acceptance again — the ROUTE enforces §4.3.7, not a function"
    )
    # THE CONTROL: the file is being read at all. A path that had silently become wrong would
    # satisfy both absences above by reading an empty string.
    assert "def draft_risk_assessment" in src, (
        "measures.py is not being read — the two absences above are vacuous"
    )
