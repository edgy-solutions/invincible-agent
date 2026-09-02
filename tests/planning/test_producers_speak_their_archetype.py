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
    # ENGINE F (finance), ADR-0045. Added when the three were put into the projector
    # 2026-09-02 — this seal FAILED first and is the reason they have conformance cases at
    # all: it enumerates from the projector's own table, so adding a projected archetype
    # without a producer case is caught here rather than by a blank card in a demo.
    "VARIANCE_TREE": ("VarianceTree.contract.ts", "VarianceNode"),
    "CONTRIBUTION_RANKING": ("ContributionRanking.contract.ts", "ContributionRow"),
    "FORECAST_MEASURE": ("ForecastMeasure.contract.ts", "ForecastRow"),
}

#: Projected archetypes with no producer case here, each with the reason. AN EXEMPTION IS A
#: CLAIM, and the coverage test below forces it to be written down rather than left as a gap
#: nobody can see.
_EXEMPT = {
    "DELTA_SET": "produced only by a committed scenario diff, not by a measure over seed state",
    # CANVAS_SEED is a CONSUMER binding, not a component one, and the distinction is the
    # ruling that created the category: a binding declares either a component (something
    # DRAWN, with a row contract this test can conform against) or a consumer (something
    # ACTED ON), and the seal checks whichever was declared.
    #
    # Its payload is a list of ARTIFACT IDS — strings, not rows — so there is no row
    # interface to conform to and no producer measure that emits it: it is the answer to a
    # request for a whole board, produced by a BFF orchestration. Its shape is declared by
    # its receiver in cortex-ui/src/lib/canvasSeedFromAnswer.ts and pinned on this side by
    # the CANVAS_SEED arms in tests/planning/test_planning_archetypes_are_projected.py,
    # which is where a shape change would be caught.
    #
    # Writing a row contract for it would be classification-is-not-existence committed
    # deliberately: asserting a renderable row shape for an archetype that renders no rows.
    "CANVAS_SEED": (
        "a CONSUMER binding, not a component: its payload is artifact ids (strings), not "
        "rows, and no measure produces it — a BFF orchestration does. Shape is declared by "
        "the receiver (canvasSeedFromAnswer.ts) and pinned by the CANVAS_SEED arms in "
        "test_planning_archetypes_are_projected.py"
    ),
}

#: THE MIRROR — used only when the sibling repo is absent, and cross-checked against the
#: parsed contract whenever it is present. Required (non-optional) fields only.
_MIRROR = {
    # ENGINE F (finance). REQUIRED (non-optional) fields only, per this table's rule — the
    # cross-check against the parsed contract is what keeps these honest when the sibling
    # repo is present.
    #
    # NOTE what is NOT here: `rank`. The producer emits it and CONTRIBUTION_RANKING's
    # contract does not declare it, because ORDER is the answer and the contract says
    # orderIsUpstream — a rank column is a convenience, not a required field. Listing it
    # would assert a contract cortex never made.
    "VARIANCE_TREE": {"level", "entity_id", "entity_name", "variance"},
    "CONTRIBUTION_RANKING": {"entity_id", "entity_name", "contribution"},
    "FORECAST_MEASURE": {"method", "formula", "eac"},
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
    block = re.search(r"_PROJECTED_ARCHETYPES: Dict\[str, tuple\] = \{(.*?)^\}", src, re.S | re.M)
    assert block, "could not find _PROJECTED_ARCHETYPES — the projector's shape moved"
    projected = set(re.findall(r'^\s*"(\w+)":', block.group(1), re.M))
    assert len(projected) >= 5, f"parsed only {projected} — the regex is not reading the table"

    covered = set(_CONTRACTS) | set(_EXEMPT)
    uncovered = projected - covered
    assert not uncovered, (
        f"projected archetypes with no producer conformance case: {sorted(uncovered)}. "
        "Each one can mount and refuse with a blank card that no test on either side catches."
    )


# ── THE PRODUCER POPULATION WAS ALSO REMEMBERED ───────────────────────────────────────
#
# This file already fixed the ARCHETYPE population once: the coverage test above enumerates
# from the projector's own table because a remembered list of archetypes missed
# SHORTFALL_GRID. The PRODUCER population above is still remembered — one lambda per
# archetype, all seven of them Engine P's.
#
# So a SECOND producer binding to an EXISTING archetype is unguarded, and that is exactly
# what happened. Engine F bound fin:BurnRateSeries and fin:PerformanceIndexSeries to
# PERIOD_SERIES, emitted none of its seven required keys, and every seal in this repo stayed
# green: the archetype had a producer case (Engine P's), the binding was declared, the class
# was seeded, the renderer selected correctly — and the card mounted and refused.
#
# MEASURED 2026-09-02: both producers are missing SIX of the seven required keys. The
# archetype's row contract is capex/expense/total/cap/over_cap/overage — Engine P's cost
# curve — so this was never a payload gap. It was the wrong archetype, and the binding could
# not have been made to work by adding a field.
#
# Derived from PRESENTATION_CAPABILITIES so the seventh Engine F verb inherits the guard.

_FIN_WRONG_ARCHETYPE = {
    # (subject_uri, archetype): why this binding cannot be satisfied, not merely why it isn't
    ("fin:BurnRateSeries", "PERIOD_SERIES"):
        "PERIOD_SERIES is Engine P's COST CURVE wearing a generic name: its row contract "
        "requires capex/expense/total plus cap/over_cap/overage, and its component hardcodes "
        "stacked capex+expense bars against a cap column. A burn-rate row is burn vs planned "
        "with no cap. Emitting `total` would satisfy the validator and still draw the wrong "
        "chart. Needs an archetype that plots labelled numeric series over periods without a "
        "cap — a mint, per the ADR-0045 precedent that produced the other three.",
    ("fin:PerformanceIndexSeries", "PERIOD_SERIES"):
        "Same archetype, and a sharper mismatch: CPI/SPI are DIMENSIONLESS RATIOS. There is "
        "no cap, no overage, and no total. Giving a ratio a field called `total` beside an "
        "`over by` column would be a false claim about the number, which is the same species "
        "as the generative-renderer violation — a plausible-looking card asserting something "
        "untrue about a finance figure.",
}


#: Extra spoken-mandatory slots a fin verb needs beyond `program_id`. `method` is mandatory
#: with NO DEFAULT by ADR-0045 ruling — supplying one here is the test's job, not the engine's,
#: and the refusal it would otherwise raise is itself sealed in tests/finance/.
_FIN_EXTRA_KWARGS = {"fin_eac_calculation": {"method": "CPI"}}


def _call_fin(fn, state):
    """Invoke a fin producer with its mandatory slots filled."""
    return fn(state, program_id="NP-MERIDIAN", **_FIN_EXTRA_KWARGS.get(fn.__name__, {}))


def _fin_producer_bindings():
    """(subject_uri, archetype, producer_fn) for every fin: binding, derived not listed."""
    from agent_fleet.presentation_agent.capabilities import PRESENTATION_CAPABILITIES
    from agent_fleet.finance_agent import measures as fin_measures
    by_output = {uri: fn for fn, uri in fin_measures.OUTPUT_URI.items()}
    out = []
    for cap in PRESENTATION_CAPABILITIES:
        subj = cap["subject_uri"]
        if not subj.startswith("fin:"):
            continue
        full = subj.replace("fin:", "http://invincible-agent/fin#", 1)
        fn_name = by_output.get(full) or by_output.get(subj)
        if fn_name:
            out.append((subj, cap["archetype"], getattr(fin_measures, fn_name)))
    return out


def test_every_FIN_producer_emits_its_archetype_keys_or_is_a_named_wrong_binding():
    """Every fin: binding, derived from the capability table rather than remembered.

    An entry in `_FIN_WRONG_ARCHETYPE` is a CLAIM that the binding is unsatisfiable, not a
    licence to skip it — the test below proves each exemption still fails, so a stale one
    cannot sit here pretending to be a known issue after it is fixed.
    """
    from agent_fleet.finance_agent.seed import build_seed
    st = build_seed()
    bindings = _fin_producer_bindings()
    assert len(bindings) >= 6, f"derived only {len(bindings)} fin bindings — the derivation is stale"

    failures = []
    for subj, archetype, fn in bindings:
        if (subj, archetype) in _FIN_WRONG_ARCHETYPE:
            continue
        if archetype not in _CONTRACTS and archetype not in _MIRROR:
            continue
        rows = _call_fin(fn, st)
        rows = rows["rows"] if isinstance(rows, dict) else rows
        assert rows, f"{subj}: producer returned no rows — the check would be vacuous"
        missing = _required(archetype) - set(rows[0])
        if missing:
            failures.append(f"{subj} -> {archetype} missing {sorted(missing)}")
    assert not failures, (
        "bound fin producers that will MOUNT AND REFUSE:\n  " + "\n  ".join(failures)
        + "\nAdd the keys, or record it in _FIN_WRONG_ARCHETYPE with why the binding cannot "
          "be satisfied at all."
    )


def test_every_named_wrong_binding_STILL_fails():
    """THE EXEMPTIONS ARE PROVEN, not asserted. A stale exemption is worse than none: it is a
    fixed defect still described as broken, and it silently suppresses a real check."""
    from agent_fleet.finance_agent.seed import build_seed
    st = build_seed()
    st_bindings = {(s, a): fn for s, a, fn in _fin_producer_bindings()}
    for key, reason in _FIN_WRONG_ARCHETYPE.items():
        assert key in st_bindings, f"{key} is exempted but no longer bound — delete the entry"
        assert len(reason) > 80, f"{key}: an exemption needs a reason, not a label"
        rows = _call_fin(st_bindings[key], st)
        rows = rows["rows"] if isinstance(rows, dict) else rows
        missing = _required(key[1]) - set(rows[0])
        assert missing, (
            f"{key} is listed as an unsatisfiable binding but its producer now emits every "
            f"required key. If the archetype was fixed or the binding changed, DELETE the "
            f"exemption — it is now suppressing a live check."
        )
