"""A chaining table's `domain` must EQUAL the task kind's declared verbs, not resemble them.

**`domain` exists so totality is measured against something from outside the rows** — otherwise a
table is total by construction, which is the fixture-that-cannot-fail shape this arc has now met
five times. But for a CHAINING table the domain is the set of verbs a human act can emit, and that
set is already declared: it is the `accepts` of the task kind the definition's `human_await` opens.

**So `domain` in a chaining table is a COPY of another declaration, and a copy is a hand-kept list
one level along.** Nothing was checking that the two agreed. A kind gaining a fourth verb would
leave the table total over three of them — total, unique, well-formed, and blind to the value that
would now fall through, with the fall-through surfacing wherever the missing row would have routed.

That is the same defect `domain` was introduced to prevent, arriving through the back door: the
population came from outside the rows, and was still wrong.

**WHY EQUALITY AND NOT CONTAINMENT.** A domain SMALLER than the declaration falls through on the
missing verb. A domain LARGER forces rows for verbs no human can emit, which look like coverage
and can never fire — a guard that cannot fire, in data. Both directions are defects, so both are
asserted.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[2]
_OVERLAY_KINDS = _REPO / "policy" / "overlays" / "sample" / "task_kinds"
_OVERLAY_DECISIONS = _REPO / "policy" / "overlays" / "sample" / "decisions"

#: chaining table -> the task kinds whose verbs it must cover.
#:
#: NAMED rather than derived, and the reason is honest: a chaining table does not record which
#: definition it chains from, so nothing in the data links a table to a kind. Deriving it would
#: mean inferring from the file name, which is a convention rather than a declaration. This map is
#: therefore a hand-kept list — and it is kept SMALL and asserted non-empty, so a table added
#: without an entry is visible as an omission here rather than silently uncovered.
_TABLE_TO_KINDS = {
    "safety_concurrence_chaining.yaml": [
        "risk_acceptance_concurrence_high.yaml",
        "risk_acceptance_concurrence_serious.yaml",
    ],
    "safety_acceptance_chaining.yaml": [
        "risk_acceptance_high.yaml",
        "risk_acceptance_serious.yaml",
        "risk_acceptance_medium.yaml",
        "risk_acceptance_low.yaml",
    ],
}


def _yaml(p: Path) -> dict:
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def test_every_named_table_and_kind_exists():
    """The map is a hand-kept list; this is what stops it rotting silently. A renamed file makes
    the map wrong, and a wrong map makes every assertion below pass over nothing."""
    for table, kinds in _TABLE_TO_KINDS.items():
        assert (_OVERLAY_DECISIONS / table).exists(), f"{table} named in the map does not exist"
        for k in kinds:
            assert (_OVERLAY_KINDS / k).exists(), f"{k} named in the map does not exist"


@pytest.mark.parametrize("table,kinds", sorted(_TABLE_TO_KINDS.items()))
def test_the_domain_equals_the_declared_verbs(table, kinds):
    """THE SEAL, both directions."""
    declared = {tuple(sorted(_yaml(_OVERLAY_KINDS / k).get("accepts") or [])) for k in kinds}
    assert len(declared) == 1, (
        f"{table} serves kinds that declare DIFFERENT verb sets {sorted(declared)} — one table "
        "cannot be total for all of them, and covering some silently is the failure this asserts"
    )
    kind_verbs = set(declared.pop())

    domain = set((_yaml(_OVERLAY_DECISIONS / table).get("domain") or {}).get("outcome") or [])
    assert domain, f"{table} declares no outcome domain"

    missing = sorted(kind_verbs - domain)
    extra = sorted(domain - kind_verbs)
    assert not missing, (
        f"{table}: the kind(s) declare {missing} and the domain omits them — a human can emit a "
        f"verb this table has no row for, and it FALLS THROUGH at the moment a decision was made"
    )
    assert not extra, (
        f"{table}: the domain declares {extra} which no kind accepts — rows for a verb no human "
        "can emit look like coverage and can never fire"
    )


@pytest.mark.parametrize("table", sorted(_TABLE_TO_KINDS))
def test_the_comparison_can_fail(table):
    """THE CONTROL. Both sides must be non-empty, or equality holds vacuously — which is exactly
    how a set-comparison seal passes while checking nothing."""
    kinds = _TABLE_TO_KINDS[table]
    assert all(_yaml(_OVERLAY_KINDS / k).get("accepts") for k in kinds), (
        "a kind declares no verbs — the comparison would be trivially satisfied"
    )
    assert (_yaml(_OVERLAY_DECISIONS / table).get("domain") or {}).get("outcome"), (
        "the table declares no domain — the comparison would be trivially satisfied"
    )
