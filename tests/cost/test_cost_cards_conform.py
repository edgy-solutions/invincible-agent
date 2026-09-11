"""Every bound cost verb emits the AXIS KEYS its archetype requires.

THE DEFECT THIS EXISTS FOR cannot be caught on either side alone. The producer's own tests pass
- the rows are correct domain data. The component's own tests pass - it refuses a payload with
no axes, exactly as its contract says. Only the PAIR is wrong, and the pair is assembled in a
browser, which is why the planning side found three of these by looking at screenshots.

REQUIRED KEYS ARE READ OUT OF CORTEX-UI'S CONTRACTS when the sibling repo is checked out, so
this cannot go stale against a contract that grows a field. The mirror is used only when it is
absent, and is asserted equal to the parsed result whenever both are available.

THE POPULATION IS DERIVED from the binding table filtered to `cost:`, never listed here. A verb
bound without a case would otherwise be a gap nobody can see.
"""
from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import pytest

from agent_fleet.cost_agent import measures
from agent_fleet.cost_agent.seed import build_state
from agent_fleet.presentation_agent.capabilities import (
    PRESENTATION_CAPABILITIES, canonical_iri_for_lookup,
)

ROOT = Path(__file__).resolve().parents[2]
_CORTEX = ROOT.parent / "cortex-ui" / "src" / "components" / "planning"

_CONTRACTS = {
    "STEP_LADDER": ("StepLadder.contract.ts", "StepLadderRow"),
    "CONTRIBUTION_RANKING": ("ContributionRanking.contract.ts", "ContributionRow"),
    "MULTI_SERIES": ("MultiSeries.contract.ts", "MultiSeriesRow"),
    "DELTA_SET": ("DeltaSet.contract.ts", "DeltaEffect"),
}

_MIRROR = {
    # `rate` and `basis` are NULLABLE — the seed step is an amount, not a factor struck on
    # something — so they are optional in the contract and absent from this required set.
    "STEP_LADDER": {"name", "amount", "running_total"},
    "CONTRIBUTION_RANKING": {"entity_id", "entity_name", "contribution"},
    "MULTI_SERIES": {"period"},
    "DELTA_SET": {"metric", "direction", "magnitude", "affected"},
}

#: Where each archetype's rows live in the payload. `DELTA_SET` calls them `effects`, which is
#: its contract's word, not a synonym we chose.
_ROW_KEY = {"CONTRIBUTION_RANKING": "rows", "MULTI_SERIES": "rows", "DELTA_SET": "effects",
            "STEP_LADDER": "steps"}

#: One representative call per bound verb. Arguments only - the payload is the engine's.
_CALLS = {
    "cost_lot_breakdown": dict(lot=3, rate_vintage="2021-02-01"),
    "cost_unit_price_trend": {},
    "cost_labor_composition": dict(lot=3),
    "cost_rate_assumptions": dict(fiscal_year=2021),
    "cost_rate_comparison": dict(lot=3, rate_vintage="2021-02-01"),
    "cost_category_breakdown": dict(lot=3),
    "cost_supplier_concentration": dict(lot=3),
    "cost_price_composition": dict(lot=3, rate_vintage="2021-02-01"),
}

#: output class -> verb, derived from the engine's own table rather than restated.
_VERB_FOR = {uri.rsplit("#", 1)[-1]: fn for fn, uri in measures.OUTPUT_URI.items()}

COST_BINDINGS = [b for b in PRESENTATION_CAPABILITIES
                 if b["subject_uri"].startswith("cost:")]


def _parse_required(archetype: str) -> set[str] | None:
    fname, iface = _CONTRACTS[archetype]
    path = _CORTEX / fname
    if not path.is_file():
        return None
    src = path.read_text(encoding="utf-8")
    m = re.search(rf"export interface {iface} \{{(.*?)^\}}", src, re.S | re.M)
    if not m:
        return None
    body = re.sub(r"/\*.*?\*/", "", m.group(1), flags=re.S)
    body = re.sub(r"//.*", "", body)
    return {n for n, opt in re.findall(r"^\s*(\w+)(\??):", body, re.M) if not opt}


def required_keys(archetype: str) -> set[str]:
    parsed = _parse_required(archetype)
    if parsed is None:
        return _MIRROR[archetype]
    assert parsed == _MIRROR[archetype], (
        f"{archetype}: the contract requires {sorted(parsed)} but the mirror in this file says "
        f"{sorted(_MIRROR[archetype])} - a hand-copied list nobody checks is the "
        "second-source-of-truth problem this repo has been bitten by before")
    return parsed


@pytest.fixture(scope="module")
def state():
    return build_state()


@pytest.mark.parametrize("binding", COST_BINDINGS,
                         ids=[b["subject_uri"] for b in COST_BINDINGS])
def test_every_bound_cost_verb_emits_its_archetypes_axis_keys(binding, state):
    shape = binding["subject_uri"].split(":", 1)[1]
    fn_name = _VERB_FOR[shape]
    payload = measures.VERBS[fn_name](state, **_CALLS[fn_name])
    rows = payload[_ROW_KEY[binding["archetype"]]]
    assert rows, f"{fn_name} produced no rows to draw"
    missing = required_keys(binding["archetype"]) - set(rows[0])
    assert not missing, (
        f"{fn_name} -> {binding['archetype']}: rows are missing {sorted(missing)}. The card "
        f"renders blank; both sides' own tests pass.")


@pytest.mark.parametrize("binding", COST_BINDINGS,
                         ids=[b["subject_uri"] for b in COST_BINDINGS])
def test_the_expected_fields_on_the_row_are_ACTUALLY_EMITTED(binding, state):
    """A binding advertising a field the producer does not emit is a promise to the selector."""
    shape = binding["subject_uri"].split(":", 1)[1]
    fn_name = _VERB_FOR[shape]
    payload = measures.VERBS[fn_name](state, **_CALLS[fn_name])
    for field in binding["expected_fields"]:
        present = field in payload or field in payload[_ROW_KEY[binding["archetype"]]][0]
        assert present, f"{fn_name} advertises {field!r} and emits it nowhere"


def test_EVERY_cost_output_class_is_bound_or_REFUSED_IN_WRITING():
    """DERIVED FROM THE ENGINE'S TABLE. A verb quietly unbound renders as
    'Knowledge Document - No content available', which is indistinguishable from a verb that
    was never built - so an absence has to be a written claim, not a gap.
    """
    bound = {b["subject_uri"].split(":", 1)[1] for b in COST_BINDINGS}
    every = {uri.rsplit("#", 1)[-1] for uri in measures.OUTPUT_URI.values()}
    unbound = every - bound
    assert unbound == {"ExportPackage"}, (
        f"unbound cost shapes changed: {sorted(unbound)}. Bind it, or record the refusal here "
        "and in capabilities.py beside the rows.")
    # PriceComposition IS NOW BOUND — mesh:StepLadder resolves in the graph, verified by ASK
    # against the deployed Fuseki before the row was added. The refusal text that stood in its
    # place is gone with it: a refusal kept after the thing is bound is a stale claim, which is
    # what cortex's own exemption said about itself.


def test_the_cost_prefix_EXPANDS(binding=None):
    """Without it every row above registers, reports accepted, and never matches a payload."""
    assert canonical_iri_for_lookup("cost:LotCostBreakdown") == (
        "http://invincible-agent/cost#LotCostBreakdown")
    for b in COST_BINDINGS:
        assert canonical_iri_for_lookup(b["subject_uri"]).startswith("http://"), b["subject_uri"]


def test_the_MULTI_SERIES_declarations_appear_in_every_row(state):
    """The real guard for MULTI_SERIES is not a key list: a declared series whose key is absent
    from a row draws a line with a hole in it and no error anywhere."""
    for b in COST_BINDINGS:
        if b["archetype"] != "MULTI_SERIES":
            continue
        fn_name = _VERB_FOR[b["subject_uri"].split(":", 1)[1]]
        payload = measures.VERBS[fn_name](state, **_CALLS[fn_name])
        keys = [s["key"] for s in payload["series"]]
        assert keys, f"{fn_name} declares no series"
        for row in payload["rows"]:
            for key in keys:
                assert key in row, f"{fn_name}: row {row.get('period')} lacks declared {key!r}"
                assert isinstance(row[key], (int, float)), (
                    f"{fn_name}: {key!r} is {type(row[key]).__name__}, not a number")


def test_DELTA_SET_direction_is_the_MEASURES_judgement_not_a_sign_test(state):
    """The contract is explicit: a renderer inferring direction from the sign of `delta` would
    call a rising capability level a degradation. So the measure must state it - and must state
    something a sign test could not: `neutral` at zero."""
    out = measures.cost_rate_comparison(state, lot=3, rate_vintage="2021-02-01")
    directions = {e["direction"] for e in out["effects"]}
    assert directions <= {"improved", "degraded", "neutral"}
    for e in out["effects"]:
        if e["delta"] == 0:
            assert e["direction"] == "neutral"
        elif e["delta"] > 0:
            assert e["direction"] == "degraded", "a rate above estimate raises the price"


def test_DELTA_SET_affected_is_NOT_EMPTY_and_names_real_steps(state):
    """A required field with nothing to put in it is the declared-but-unwired shape. Every rate
    factor here feeds named composition steps, so the list is fact rather than filler."""
    from agent_fleet.cost_agent.pricing import DEFAULT_COMPOSITION

    names = {s.name for s in DEFAULT_COMPOSITION} | {'Base cost'}
    out = measures.cost_rate_comparison(state, lot=3, rate_vintage="2021-02-01")
    unwired = [e["metric"] for e in out["effects"] if not e["affected"]]
    assert not unwired, f"these factors affect nothing: {unwired}"
    for e in out["effects"]:
        assert set(e["affected"]) <= names, f"{e['metric']} names a step that does not exist"


def test_the_generic_keys_did_not_REPLACE_the_domain_names(state):
    """Engine F's rule, and its reason: renaming the domain fields to fit a renderer is the
    translation layer ADR-0045 refused at the ontology layer. An analyst reading the payload
    must still see their own vocabulary."""
    checks = [
        ("cost_lot_breakdown", dict(lot=3, rate_vintage="2021-02-01"), "rows", "category"),
        ("cost_labor_composition", dict(lot=3), "rows", "labor_kind"),
        ("cost_supplier_concentration", dict(lot=3), "rows", "supplier"),
        ("cost_category_breakdown", dict(lot=3), "rows", "share_delta_vs_prior_lot"),
        ("cost_rate_comparison", dict(lot=3, rate_vintage="2021-02-01"), "effects", "factor"),
    ]
    for fn_name, kw, row_key, domain_field in checks:
        rows = measures.VERBS[fn_name](state, **kw)[row_key]
        assert domain_field in rows[0], f"{fn_name} dropped {domain_field!r}"


def test_money_stays_EXACT_in_the_domain_field(state):
    """`contribution` is a float because the renderer needs a number. The exact Decimal string
    stays in the domain field, and the two must agree to the cent."""
    from decimal import Decimal

    out = measures.cost_lot_breakdown(state, lot=3, rate_vintage="2021-02-01")
    for row in out["rows"]:
        assert isinstance(row["price"], str), "the exact figure stopped being a string"
        assert abs(Decimal(row["price"]) - Decimal(str(row["contribution"]))) < Decimal("0.005")

# ═══════════════════════════════════════════════════════════════════════════
# THE PROJECTOR SEAM — what the card is promised against what the engine sends
# ═══════════════════════════════════════════════════════════════════════════

def _projected(archetype: str) -> tuple[str, tuple[str, ...]]:
    """Read one row of the projector's own table WITHOUT importing the app.

    `presentation_agent.main` imports baml_client, which is not installed in this environment,
    so the table is parsed from source. Parsed rather than mirrored: a copy here would be the
    second-source-of-truth problem, and this seal exists precisely because two sides disagreed.
    """
    import re

    src = (ROOT / "agent_fleet" / "presentation_agent" / "main.py").read_text(encoding="utf-8")
    m = re.search(r'"' + archetype + r'": \((.*?)\),\n', src, re.S)
    assert m, f"{archetype} has no row in _PROJECTED_ARCHETYPES"
    rows_key, passthrough = eval("(" + m.group(1) + ")")   # noqa: S307 - our own source
    return rows_key, passthrough


def test_the_STEP_LADDER_PASSTHROUGH_is_fully_emitted(state):
    """EVERY FIELD THE PROJECTOR CARRIES MUST EXIST IN THE PAYLOAD.

    The passthrough advertised `scope_label` and this producer did not emit it. That is the
    mirror of the defect the projector's own comment warns about — "a field advertised to a
    renderer that never looks at it" — pointing the other way: a field the renderer reads and
    the producer never sends. The card would have drawn a build-up framed by nothing, and
    neither side's tests could see it, because each was right about its own half.

    DERIVED FROM THE PROJECTOR'S TABLE, not from a list here, so a field added on that side
    without a producer change fails on this one.
    """
    rows_key, passthrough = _projected("STEP_LADDER")
    payload = measures.cost_price_composition(state, lot=3, rate_vintage="2021-02-01")
    assert rows_key in payload, f"the projector reads rows from {rows_key!r} and there are none"
    missing = [f for f in passthrough if f not in payload]
    assert not missing, (
        f"the projector carries {missing} and cost_price_composition emits none of them - the "
        "card is promised a field the engine never sends")


def test_the_passthrough_carries_NOTHING_THE_CARD_CANNOT_USE(state):
    """The same rule in the direction the projector's comment states it.

    `lot` and `fiscal_year` are on the envelope and deliberately NOT carried: `scope_label`
    already says which walk this is, so carrying them would advertise fields nothing reads.
    This pins that decision - if either appears in the passthrough, someone has changed their
    mind and the reason should be written down rather than inferred.
    """
    _, passthrough = _projected("STEP_LADDER")
    for field in ("lot", "fiscal_year"):
        assert field not in passthrough, (
            f"{field!r} joined the passthrough; scope_label already frames the card, so either "
            "the card now reads it or it is an advertised field nothing looks at")


def test_sums_SURVIVES_the_projector(state):
    """The card refuses to draw on `sums: false`. If the projector dropped it, the card could
    not tell a checked walk from an unchecked one and would draw a confident table either way.
    """
    _, passthrough = _projected("STEP_LADDER")
    assert "sums" in passthrough, "the reconciliation flag is not carried to the card"
    payload = measures.cost_price_composition(state, lot=3, rate_vintage="2021-02-01")
    assert payload["sums"] is True


def test_the_projector_reads_steps_not_structured_data(state):
    """A build-up's rows live under `steps`. If this ever reads `structured_data`, the card gets
    no rows at all and degrades to KNOWLEDGE_DOCUMENT - silently, which is the failure shape
    every cost verb was in before its binding row existed."""
    rows_key, _ = _projected("STEP_LADDER")
    assert rows_key == "steps"


# ═══════════════════════════════════════════════════════════════════════════
# `favourable` — the producer's verdict, which cortex refuses to infer
# ═══════════════════════════════════════════════════════════════════════════

def test_ONE_FIELD_NAME_DOES_NOT_CARRY_TWO_VOCABULARIES(state):
    """`direction` meant improved/degraded/neutral in one verb and up/down/flat in another, in
    the same file. Only the first agreed with what a consumer reads, so the collision was
    invisible until a card tried to draw.

    DERIVED: every row of every verb is scanned for a `direction` key, so a third vocabulary
    cannot be introduced under the same name without this going red.
    """
    from agent_fleet.cost_agent.pricing import DEFAULT_COMPOSITION  # noqa: F401

    seen: dict[str, set] = {}
    for fn_name, kw in _CALLS.items():
        payload = measures.VERBS[fn_name](state, **kw)
        for key in ("rows", "effects"):
            for row in payload.get(key, []) or []:
                if "direction" in row:
                    seen.setdefault(fn_name, set()).add(row["direction"])
    for fn_name, values in seen.items():
        assert values <= {"improved", "degraded", "neutral"}, (
            f"{fn_name} emits `direction` = {sorted(values)}, which is not DELTA_SET's "
            "vocabulary. One field name carrying two meanings is how the movement signal was "
            "dropped silently.")


def test_the_ranking_verdict_is_STATED_not_inferable_from_the_sign(state):
    """Cortex: 'A renderer deciding from contribution > 0 would be right on this payload and
    wrong on the next one.' So the sign and the verdict must be able to disagree — if they
    always agreed, the field would be decorative and a renderer inferring it would be correct.
    """
    rows = measures.cost_category_breakdown(state, lot=4)["rows"]
    verdicts = [(r["contribution"] > 0, r.get("favourable")) for r in rows
                if "favourable" in r]
    assert verdicts, "no row carries a verdict"
    assert any(sign != fav for sign, fav in verdicts), (
        "every verdict matches the sign of `contribution`, so the field asserts nothing a "
        "renderer could not have guessed")


def test_the_verdict_rests_on_PER_UNIT_movement_not_on_share(state):
    """A share is a composition, not a cost. Labor's share can rise on a lot that got cheaper,
    and calling that 'degraded' would be a false claim rendered in red."""
    # LOT 7, NOT LOT 4, AND THE CHOICE IS THE TEST. On lot 4 the two rules agree on every row,
    # so lot 4 cannot tell them apart — the seal would have been green and vacuous. On lot 7
    # labor's SHARE falls while its PER-UNIT COST RISES: a share-based rule calls that
    # favourable, and it got dearer. That row is the whole argument for the choice.
    rows = measures.cost_category_breakdown(state, lot=7)["rows"]
    share_rule_would_say = {r["entity_id"]: (r["share_direction"] == "down") for r in rows}
    disagreeing = [r["entity_id"] for r in rows
                   if "favourable" in r
                   and r["favourable"] != share_rule_would_say[r["entity_id"]]]
    assert disagreeing, (
        "the verdict agrees with share direction on every row of this lot, so the seal cannot "
        "tell the two rules apart - pick a lot where they diverge")
    for r in rows:
        if "favourable" in r:
            assert r["favourable"] == (
                Decimal(r["per_unit_delta_vs_prior_lot"]) < 0), r["entity_name"]


def test_NO_VERDICT_WHERE_NOTHING_MOVED(state):
    """`favourable` is a boolean in cortex's contract and False means 'this got worse' — it is
    not a resting state. The first version emitted False for two buckets whose per-unit delta
    displayed as 0.00, which would have drawn an adverse tone on an unchanged row.
    """
    rows = measures.cost_category_breakdown(state, lot=4)["rows"]
    unchanged = [r for r in rows if r["per_unit_delta_vs_prior_lot"] == "0.00"]
    assert unchanged, "no unchanged bucket on this lot - the seal has gone vacuous"
    for r in unchanged:
        assert "favourable" not in r, f"{r['entity_name']} carries a verdict on zero movement"


def test_the_FIRST_LOT_carries_NO_verdict_at_all(state):
    for r in measures.cost_category_breakdown(state, lot=1)["rows"]:
        assert "favourable" not in r, "a verdict without a prior lot to compare against"
        assert r["per_unit_delta_vs_prior_lot"] is None


def test_the_verdict_is_QUANTITY_NORMALISED(state):
    """Lot 4 is 24 units against lot 3's 18. A bucket costing more in TOTAL says nothing about
    whether it got better or worse, so a verdict read off totals would be about lot size."""
    rows = {r["entity_id"]: r for r in measures.cost_category_breakdown(state, lot=4)["rows"]}
    prior = {r["entity_id"]: r for r in measures.cost_category_breakdown(state, lot=3)["rows"]}
    misled = [k for k, r in rows.items()
              if "favourable" in r
              and r["favourable"] is True
              and Decimal(r["amount"]) > Decimal(prior[k]["amount"])]
    assert misled, (
        "no bucket is favourable per unit while costing more in total, so this seal cannot "
        "distinguish a normalised verdict from a raw one")
