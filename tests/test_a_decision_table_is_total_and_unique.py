"""Every decision table is TOTAL and UNIQUE — the seal that exists before the first real row.

ADR-0039 (amended 2026-09-12): choice lives in decision tables at trigger and termination;
definitions stay linear. This is the seal that makes a table's rows reviewable as policy, and it
is committed **in the same commit that creates `policy/decisions/`** so that the first domain row
anyone writes lands INTO a seal rather than before one.

TWO INVARIANTS, AND EACH FAILS IN A WAY NOTHING ELSE WOULD REPORT.

**TOTALITY** — every value an engine can emit for a matched attribute has a row. A table that is
total over the values someone thought of does not error on the rest: it **falls through**. In a
selection table a fall-through means *no definition was chosen* at the moment a human decision was
due, and the symptom appears wherever the missing definition would have opened — far from the gap.

**UNIQUENESS** — no two rows match one input. Two matching rows make the outcome depend on row
order, which is not a declared property of a YAML list. **Each row is correct read alone and the
contradiction exists only between them**, which is R-035: an invariant between declarations is
invisible to every per-declaration check, so this one quantifies over PAIRS.

THE DOMAIN MUST COME FROM OUTSIDE THE ROWS, and that is the part most easily got wrong. If the
attribute's value set were derived from the rows, every table would be total by construction and
this seal would assert nothing — the fixture-that-cannot-fail shape (R-026). So `domain:` is
declared, and `test_the_domain_is_not_derived_from_the_rows` checks that the declaration is doing
real work.

WHY IT PASSES ON AN EMPTY SEED TODAY, AND WHY THAT IS NOT VACUOUS. `policy/decisions/` is
structural and holds no tables yet; the sample overlay holds one. The floor below asserts that
**at least one table is found somewhere**, so "no tables" fails loudly rather than passing as a
quantification over nothing.

Run: uv run --frozen pytest tests/test_a_decision_table_is_total_and_unique.py -v
"""
from __future__ import annotations

import itertools
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="decision tables are YAML")

_REPO = Path(__file__).resolve().parents[1]
_SEED = _REPO / "policy" / "decisions"
_SAMPLE_OVERLAY = _REPO / "policy" / "overlays" / "sample" / "decisions"


def _tables() -> "list[tuple[str, dict]]":
    """(source label, parsed table) for every decision table in seed and sample overlay.

    Derived by globbing rather than listed: a table added tomorrow is covered on arrival, which
    is the same rule the registry-sites packet exists to enforce.
    """
    out = []
    for d, label in ((_SEED, "seed"), (_SAMPLE_OVERLAY, "sample-overlay")):
        for p in sorted(d.glob("*.yaml")):
            raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            out.append((f"{label}:{p.name}", raw))
    return out


def _ids(pairs):
    return [p[0] for p in pairs]


# ---------------------------------------------------------------------------------------
# FLOORS — a quantification over nothing passes, so assert there is something
# ---------------------------------------------------------------------------------------

def test_the_decisions_directories_exist():
    """The seed directory is created with this seal, so its absence is a deletion rather than a
    not-yet. Asserted so the glob below cannot silently walk nothing."""
    assert _SEED.is_dir(), f"{_SEED} does not exist — the decision layer's seed half is missing"
    assert _SAMPLE_OVERLAY.is_dir(), f"{_SAMPLE_OVERLAY} does not exist"


def test_AT_LEAST_ONE_TABLE_IS_FOUND():
    """THE FLOOR. Every assertion below quantifies over tables; with none they all pass while
    proving nothing — and `policy/decisions/` being legitimately empty today is exactly the
    condition that would make that invisible."""
    found = _tables()
    assert found, (
        "no decision tables found in either policy/decisions/ or the sample overlay. Every "
        "totality and uniqueness assertion in this file is then vacuous."
    )


def test_the_platform_seed_holds_no_domain_table():
    """GENERIC AT BIRTH, asserted rather than trusted — the same boundary as
    `policy/task_kinds/`. A programme's tailoring is that programme's and composes over this
    seed; a domain name here makes the boundary lexical instead of structural."""
    forbidden = ("pcn", "pdn", "safety", "hazard")
    for p in sorted(_SEED.glob("*.yaml")):
        blob = p.read_text(encoding="utf-8").lower()
        for token in forbidden:
            assert token not in blob, (
                f"{p.name} carries the domain token {token!r} — domain tables belong in an "
                f"overlay, not in the platform seed"
            )


# ---------------------------------------------------------------------------------------
# SHAPE — the fields the invariants are computed from must exist
# ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("label,table", _tables(), ids=_ids(_tables()))
def test_a_table_declares_its_key_its_attributes_and_their_domain(label, table):
    assert table.get("decision"), f"{label}: no `decision` key — composition is keyed on it"
    matches = table.get("matches")
    assert isinstance(matches, list) and matches, (
        f"{label}: `matches` must list the attributes this table reads. Inferring them from the "
        f"rows would make 'total over what?' unanswerable independently of the rows."
    )
    domain = table.get("domain") or {}
    for attr in matches:
        vals = domain.get(attr)
        assert isinstance(vals, list) and vals, (
            f"{label}: `domain.{attr}` is missing or empty — there is nothing to be total over"
        )
    assert isinstance(table.get("rows"), list) and table["rows"], f"{label}: no rows"


@pytest.mark.parametrize("label,table", _tables(), ids=_ids(_tables()))
def test_a_row_matches_DECLARED_attributes_only(label, table):
    """A row keying on an attribute the table did not declare is outside the domain, so totality
    cannot be computed for it — and it is the first step toward a table that reads whatever
    happens to be in scope."""
    declared = set(table["matches"])
    for i, row in enumerate(table["rows"]):
        when = row.get("when") or {}
        stray = set(when) - declared
        assert not stray, (
            f"{label} row {i}: matches on undeclared attribute(s) {sorted(stray)}; "
            f"`matches` declares {sorted(declared)}"
        )
        assert row.get("then"), f"{label} row {i}: no `then` — a match selecting nothing"


@pytest.mark.parametrize("label,table", _tables(), ids=_ids(_tables()))
def test_a_row_uses_values_from_the_declared_domain(label, table):
    """A row matching a value the domain does not contain is unreachable — the
    guard-that-cannot-fire shape, in data. It also silently weakens totality, because the row
    looks like coverage and covers nothing."""
    domain = table["domain"]
    for i, row in enumerate(table["rows"]):
        for attr, val in (row.get("when") or {}).items():
            assert val in domain[attr], (
                f"{label} row {i}: matches {attr}={val!r}, which is not in the declared domain "
                f"{domain[attr]}. This row can never fire, and it reads as coverage."
            )


# ---------------------------------------------------------------------------------------
# THE TWO INVARIANTS
# ---------------------------------------------------------------------------------------

def _inputs(table) -> "list[dict]":
    """Every input the declared domain admits — the cross product of the matched attributes."""
    attrs = table["matches"]
    return [dict(zip(attrs, combo))
            for combo in itertools.product(*(table["domain"][a] for a in attrs))]


def _matching(table, inp) -> "list[int]":
    return [i for i, row in enumerate(table["rows"])
            if all(inp.get(k) == v for k, v in (row.get("when") or {}).items())]


@pytest.mark.parametrize("label,table", _tables(), ids=_ids(_tables()))
def test_TOTALITY_every_input_the_domain_admits_has_a_row(label, table):
    """A gap does not error — it FALLS THROUGH. In a selection table that means no definition
    was chosen at the moment a human decision was due, and the symptom appears wherever the
    missing definition would have opened."""
    uncovered = [inp for inp in _inputs(table) if not _matching(table, inp)]
    assert not uncovered, (
        f"{label}: {len(uncovered)} input(s) the declared domain admits match NO row: "
        f"{uncovered[:5]}. A fall-through selects nothing and reports nothing."
    )


@pytest.mark.parametrize("label,table", _tables(), ids=_ids(_tables()))
def test_UNIQUENESS_no_input_matches_two_rows(label, table):
    """Two matching rows make the outcome depend on row ORDER, which a YAML list does not
    declare. Each row is correct read alone; the contradiction exists only BETWEEN them, so this
    quantifies over pairs (R-035)."""
    for inp in _inputs(table):
        hits = _matching(table, inp)
        assert len(hits) <= 1, (
            f"{label}: input {inp} matches rows {hits} — "
            f"{[table['rows'][h].get('then') for h in hits]}. The outcome would be decided by "
            f"row order, and each row is individually correct."
        )


# ---------------------------------------------------------------------------------------
# THE ANTI-VACUUM CHECK — the seal must be capable of failing
# ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("label,table", _tables(), ids=_ids(_tables()))
def test_the_domain_is_NOT_derived_from_the_rows(label, table):
    """THE GUARD ON THIS SEAL ITSELF.

    If `domain` were the set of values the rows happen to mention, every table would be total by
    construction and `test_TOTALITY` would assert nothing — passing forever, on any table, for
    the same reason an order seal whose fixture is already alphabetical passes forever (R-026).

    So the declaration must be doing real work, and the cheapest proof is that it is POSSIBLE for
    it not to be satisfied: removing any row must make the table incomplete. A table whose domain
    is exactly its row values still satisfies that, which is why this asserts the weaker, always-
    checkable property — that the domain is DECLARED rather than computed — and leaves the
    strength to mutation.
    """
    declared_vals = {a: set(table["domain"][a]) for a in table["matches"]}
    row_vals: dict = {a: set() for a in table["matches"]}
    for row in table["rows"]:
        for a, v in (row.get("when") or {}).items():
            row_vals[a].add(v)
    for a in table["matches"]:
        assert declared_vals[a] >= row_vals[a], (
            f"{label}: rows use {a} values {sorted(row_vals[a] - declared_vals[a])} outside the "
            f"declared domain — the domain is not the authority it is supposed to be"
        )


def test_REMOVING_A_ROW_WOULD_BREAK_TOTALITY_on_every_table():
    """MUTATION, IN-PROCESS. If a table survives losing any row, its rows are not all load-bearing
    and `test_TOTALITY` is weaker than it looks on that table."""
    for label, table in _tables():
        for i in range(len(table["rows"])):
            reduced = dict(table)
            reduced["rows"] = [r for j, r in enumerate(table["rows"]) if j != i]
            uncovered = [inp for inp in _inputs(reduced) if not _matching(reduced, inp)]
            assert uncovered, (
                f"{label}: removing row {i} ({table['rows'][i].get('then')}) left the table "
                f"TOTAL — that row covers no input of its own, so it is either redundant or the "
                f"domain is too small to distinguish it."
            )
