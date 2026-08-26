"""Every bound producer must emit the AXIS KEYS its archetype requires.

THREE BLANK CARDS IN ONE MORNING, all the same defect and all invisible until deployed:

    plan Site Load     -> THRESHOLD_GRID  "cell is missing its subject or period"
    plan Maturity Grid -> MATRIX_GRID     "cell is missing its row or column"

The archetypes are GENERIC BY CONSTRUCTION: a threshold grid draws subject x period, a matrix
draws row x column, and neither may learn the words "site" or "capability". The producers were
emitting only domain names — `site_id`, `capability_id`, `load` — so to the component the
payload had no axes at all. Every component was RIGHT to refuse; nothing was broken except the
seam between them, and the seam had no test.

WHY THIS FAILURE MODE IS SO EXPENSIVE. It cannot be caught by any test on either side alone.
The producer's own tests pass — the rows are correct domain data. The component's own tests
pass — it refuses a payload with no axes, exactly as its contract says. Only the PAIR is wrong,
and the pair is only assembled in a browser, which is why all three were found by looking at
screenshots.

WHERE THE REQUIRED KEYS COME FROM. Read out of cortex-ui's contract files when the sibling repo
is checked out, so this cannot go stale against a contract that grows a field. When it is not,
the mirror below is used AND asserted equal to the parsed result whenever both are available —
a hand-copied list nobody checks is the second-source-of-truth problem this repo has been bitten
by before (the phantom service URL, the re-register list, the readiness probes: each was a
population someone remembered rather than enumerated).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_fleet.planning_agent import measures
from agent_fleet.planning_agent.seed import build_seed

_CORTEX = Path(__file__).resolve().parents[3] / "cortex-ui" / "src" / "components" / "planning"

#: archetype -> (contract file, TS interface holding one cell/row)
_CONTRACTS = {
    "THRESHOLD_GRID": ("ThresholdGrid.contract.ts", "ThresholdCell"),
    "MATRIX_GRID": ("MatrixGrid.contract.ts", "MatrixCell"),
    "INTERVAL_TIMELINE": ("IntervalTimeline.contract.ts", "IntervalRow"),
    "SHORTFALL_GRID": ("ShortfallGrid.contract.ts", "ShortfallCell"),
    "PERIOD_SERIES": ("PeriodSeries.contract.ts", "PeriodSeriesRow"),
}

#: Projected archetypes with no producer case here, each with the reason. AN EXEMPTION IS A
#: CLAIM, and the coverage test below forces it to be written down rather than left as a gap
#: nobody can see.
_EXEMPT = {
    "DELTA_SET": "produced only by a committed scenario diff, not by a measure over seed state",
}

#: THE MIRROR — used only when the sibling repo is absent, and cross-checked against the
#: parsed contract whenever it is present. Required (non-optional) fields only.
_MIRROR = {
    "THRESHOLD_GRID": {"subject_id", "period", "value", "threshold", "over_threshold"},
    # `assessed_at`/`assessed_by`/`assessment_count` are OPTIONAL in the contract — the
    # producer supplies all three, but a cell may honestly have no provenance. Listing them
    # here was this file's own first draft, and the cross-check below caught it, which is the
    # positive control working before the test ever ran against a real defect.
    "MATRIX_GRID": {"row_id", "column_id", "level", "target_level", "gap"},
    "SHORTFALL_GRID": {"subject_id", "subject_name", "period", "required", "committed",
                       "secured", "shortfall", "state"},
    "PERIOD_SERIES": {"period", "capex", "expense", "total", "cap", "over_cap", "overage"},
    "INTERVAL_TIMELINE": {
        "group_kind", "group_id", "group_name", "group_weight",
        "initiative_id", "initiative_name", "phase_id", "phase_name", "phase_sequence",
        "project_id", "project_name", "planned_start", "planned_end",
        "actual_start", "actual_end", "risk_flag",
    },
}


def _parse_required(archetype: str) -> set[str] | None:
    """Required field names of the archetype's cell interface, or None if unavailable."""
    fname, iface = _CONTRACTS[archetype]
    path = _CORTEX / fname
    if not path.is_file():
        return None
    src = path.read_text(encoding="utf-8")
    m = re.search(rf"export interface {iface} \{{(.*?)^\}}", src, re.S | re.M)
    if not m:
        return None
    body = re.sub(r"/\*.*?\*/", "", m.group(1), flags=re.S)      # block comments
    body = re.sub(r"//[^\n]*", "", body)                          # line comments
    # `name: type;` is required; `name?: type;` is optional.
    return {g for g in re.findall(r"^\s*(\w+)\s*:", body, re.M)}


def _required(archetype: str) -> set[str]:
    parsed = _parse_required(archetype)
    if parsed is None:
        return _MIRROR[archetype]
    assert parsed == _MIRROR[archetype], (
        f"{archetype}: the mirror in this file has drifted from cortex-ui's contract.\n"
        f"  contract has, mirror lacks: {sorted(parsed - _MIRROR[archetype])}\n"
        f"  mirror has, contract lacks: {sorted(_MIRROR[archetype] - parsed)}\n"
        "Update _MIRROR — and check whether the PRODUCERS need the new field too."
    )
    return parsed


@pytest.fixture(scope="module")
def state():
    return build_seed()


def test_the_contracts_are_actually_being_read():
    """Positive control. If the sibling repo is absent this test says so out loud rather than
    letting the whole module quietly degrade to checking a hand-written list against itself."""
    if not _CORTEX.is_dir():
        pytest.skip(f"cortex-ui not checked out beside this repo ({_CORTEX}) — mirror in use")
    for archetype in _CONTRACTS:
        assert _parse_required(archetype), f"could not parse {archetype}'s cell interface"


@pytest.mark.parametrize(
    "archetype,rows_of",
    [
        ("THRESHOLD_GRID", lambda s: measures.plan_site_load(s)),
        ("MATRIX_GRID", lambda s: measures.plan_maturity_grid(s)),
        ("INTERVAL_TIMELINE", lambda s: measures.plan_schedule(s)),
        ("INTERVAL_TIMELINE", lambda s: measures.plan_capability_path(s, capability_id="C4")["rows"]),
        ("SHORTFALL_GRID", lambda s: measures.plan_funding_gap(s, group_by="org")),
        ("SHORTFALL_GRID", lambda s: measures.plan_funding_gap(s, group_by="initiative")),
        ("PERIOD_SERIES", lambda s: measures.plan_cost_curve(s)),
    ],
    ids=["site_load", "maturity_grid", "schedule", "capability_path",
         "funding_gap_by_org", "funding_gap_by_initiative", "cost_curve"],
)
def test_the_producer_emits_every_key_its_archetype_requires(state, archetype, rows_of):
    rows = rows_of(state)
    assert rows, "producer returned no rows — the check would be vacuous"
    required = _required(archetype)
    for row in rows:
        missing = required - set(row)
        assert not missing, (
            f"{archetype}: a row is missing {sorted(missing)}.\n"
            "The component will MOUNT and REFUSE — a blank card with a contract reason, not "
            "an error. Domain names are not axis keys."
        )


def test_every_projected_archetype_has_a_producer_case():
    """THE ENUMERATION, and it is the point of this file.

    The first draft of this test covered the three archetypes I had just debugged. SHORTFALL_GRID
    was projected, bound, and broken in exactly the same way, and the test passed — because the
    list was REMEMBERED rather than enumerated. That is the same defect as the re-register list,
    the phantom service URL and the readiness probes: a fix applied to the instances someone
    could recall, not to the population that shares the cause.

    So the population is read from the projector's own table. Add an archetype there and this
    fails until it has a producer case or a written exemption.
    """
    src = (Path(__file__).resolve().parents[2] / "agent_fleet" / "presentation_agent"
           / "main.py").read_text(encoding="utf-8")
    block = re.search(r"_PLANNING_ARCHETYPES: Dict\[str, tuple\] = \{(.*?)^\}", src, re.S | re.M)
    assert block, "could not find _PLANNING_ARCHETYPES — the projector's shape moved"
    projected = set(re.findall(r'^\s*"(\w+)":', block.group(1), re.M))
    assert len(projected) >= 5, f"parsed only {projected} — the regex is not reading the table"

    covered = set(_CONTRACTS) | set(_EXEMPT)
    uncovered = projected - covered
    assert not uncovered, (
        f"projected archetypes with no producer conformance case: {sorted(uncovered)}. "
        "Each one can mount and refuse with a blank card that no test on either side catches."
    )
