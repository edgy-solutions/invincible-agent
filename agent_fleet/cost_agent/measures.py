"""engine-cost's six verbs. Deterministic, typed, pure over `CostState`.

ADR-0030: one verb, one fixed output type. `OUTPUT_URI` below is the whole of that contract,
and every URI in it is declared in `setup/ontologies/cost_extension.ttl` — both Contract D
ends in one file, because the planning engine's split is what let its input half go missing
for twelve registrations while the engine served /health normally throughout.

WHAT THESE FUNCTIONS MUST NEVER DO — inherited verbatim from Engines P and F, each
prohibition being a defect somebody already paid for:
  * choose a view, a chart type, or an archetype        (ADR-0042 §2 — the selector's job)
  * return an empty result to mean "not in the model"   (raise NotInModel instead)
  * invent a threshold, a rate, or a VINTAGE            (see the vintage-bearing verbs)
  * emit a monetary figure without its unit             (every row carries value_unit)

AND ONE THIS ENGINE ADDS, FROM ADR-0049 RULING 4. These verbs will be INNER CALLS in an
affordability composition, so their refusals must let a composing verb tell EMPTY from
UNAVAILABLE from UNENTITLED. Three distinct exception types, never one message — a composing
verb cannot report honestly over a source that cannot say which of the three happened, and
the collapse is invisible because all three render as "no data" to a reader.

EVERY CONCEPT HERE IS PUBLIC COST-ESTIMATING PRACTICE. Nothing is derived from any real
program, supplier or rate agreement.
"""
from __future__ import annotations

import hashlib
import os
import pathlib
from decimal import Decimal
from typing import Any, Optional


def _repo_root() -> Optional[pathlib.Path]:
    """The repository checkout this module lives in, or None in a flattened image.

    DERIVED BY LOOKING FOR A MARKER, not by counting directory levels. Counting is what put
    `parents[2]` in `package_export`: correct in a checkout, an IndexError in `/app`, and
    indistinguishable between the two by reading the line. This walks upward for a tree that
    actually contains what the caller needs, and returns None when there is none.

    NONE IS A FIRST-CLASS ANSWER. "I am not in a checkout" is a true and useful statement
    about a deployed pod, and it is the input to a named refusal rather than an error.
    """
    here = pathlib.Path(__file__).resolve()
    for candidate in here.parents:
        if _can_build_a_package_here(candidate):
            return candidate
    return None


#: Where the engine is reachable from, for building artifact URIs. SAME ENV VAR THE
#: REGISTRATION USES (`main.py` passes it as `endpoint_url`'s base), so a caller that can reach
#: a verb can reach the artifact that verb produced. Naming a second variable here would let
#: the two drift into a state where the mesh routes to one host and the download link to
#: another — and the link is the half nobody tests.
_PUBLIC_BASE_ENV = "ENGINE_COST_PUBLIC_URL"
_DEFAULT_BASE = "http://iagent-engine-cost:8097"


def _artifact_uri(filename: str) -> str:
    """The fetchable URI for a produced artifact.

    A PATH IS NOT A URI. The caller is a card in a browser and a recipient outside this
    cluster; neither can open `/repo/dist/...`, and handing one over leaks the deployment's
    filesystem layout to someone with no use for it.
    """
    base = (os.getenv(_PUBLIC_BASE_ENV) or _DEFAULT_BASE).rstrip("/")
    return f"{base}/artifact/{filename}"
#: What `package_export` actually needs on disk, and therefore what "a root" means here.
#:
#: ⛔ THIS USED TO TEST FOR `scripts/` AND `agent_fleet/` — a proxy for "a developer checkout".
#: The proxy and the requirement came apart the moment the runtime was shipped INSIDE an image:
#: a flattened `/app` carrying the builder and the pinned runtime can build a package perfectly
#: well and had neither directory, so the function answered None and the engine refused work it
#: was fully able to do.
#:
#: The alternative was to create a bare `agent_fleet/` in the image so the marker would pass.
#: That is a marker built to lie — the vacuum on purpose — and it would have made this function
#: answer "yes" on the strength of an empty directory somebody added to satisfy it.
#:
#: The docstring above always said this walks upward for "a tree that actually contains what the
#: caller needs". It now does.
_BUILDER_REL = pathlib.Path("scripts") / "build_cost_package.py"
_RUNTIME_DIR = ".pyodide-cache"


def _can_build_a_package_here(root: pathlib.Path) -> bool:
    """Both halves, because either alone produces a refusal one layer later.

    The runtime FILE LIST is not re-stated here: `package_export` reads it from the builder's own
    `RUNTIME_FILES`, and a second copy would drift the day a Pyodide bump changes it. This checks
    the directory exists; the builder's list decides what must be in it, and the named refusal
    below reports exactly which files are missing.
    """
    return (root / _BUILDER_REL).is_file() and (root / _RUNTIME_DIR).is_dir()


def _baked_algorithm_sha() -> Optional[str]:
    """The commit the shipped modules come from, WITHOUT requiring git.

    `build_cost_package.algorithm_sha()` shells out to git and refuses on a dirty
    `pricing.py` — a real safeguard for a developer build, and unusable in a pod: measured,
    `shutil.which("git")` is None there and there is no working tree to be dirty.

    THE IMAGE ALREADY CARRIES AN HONEST SHA. `utils/version_endpoint` reports `IAGENT_GIT_SHA`,
    baked at build time, and the deployed engine returns a real commit for it. This is not a
    substitute for the git answer — it is the SAME CLAIM, sourced from the artifact that can
    actually attest to it, which in a pod is the stronger of the two.

    None where neither is available, so a caller refuses by name rather than shipping a
    package whose `algorithm_sha` is a guess.
    """
    baked = (os.getenv("IAGENT_GIT_SHA") or "").strip()
    return baked if baked and baked != "unknown" else None

try:  # flat in the image (/app), packaged in the repo — see §5 of the engine runbook
    from entities import (
        COST, CostState, LaborKind, NotInModel, SourceUnavailable, Unentitled, VintageRequired,
    )
    from export import audit_line, build_dataset_package, build_package
    from pricing import DEFAULT_COMPOSITION, compose_price, rates_for, unit_price
    from seed import RECIPIENT_SCOPES, lots_for_recipient, readers_for_recipient
except ImportError:
    from agent_fleet.cost_agent.entities import (
        COST, CostState, LaborKind, NotInModel, SourceUnavailable, Unentitled, VintageRequired,
    )
    from agent_fleet.cost_agent.export import (
        audit_line, build_dataset_package, build_package,
    )
    from agent_fleet.cost_agent.pricing import (
        DEFAULT_COMPOSITION, compose_price, rates_for, unit_price,
    )
    from agent_fleet.cost_agent.seed import (
        RECIPIENT_SCOPES, lots_for_recipient, readers_for_recipient,
    )

#: ONE VERB, ONE FIXED OUTPUT TYPE (ADR-0030). Read twice — by the route, to stamp the
#: response, and by the registration, to fill Contract D's output end — so the two cannot
#: disagree about what a verb produces.
OUTPUT_URI: dict[str, str] = {
    "cost_lot_breakdown":      COST + "LotCostBreakdown",
    "cost_unit_price_trend":   COST + "UnitPriceTrend",
    "cost_rate_comparison":    COST + "RateComparison",
    "cost_labor_composition":  COST + "LaborComposition",
    "cost_price_composition":  COST + "PriceComposition",
    "cost_rate_assumptions":   COST + "RateAssumptions",
    "cost_category_breakdown": COST + "CategoryBreakdown",
    "cost_supplier_concentration": COST + "SupplierConcentration",
    "package_export":              COST + "ExportPackage",
}

#: The SUBJECT each verb is asked about — Contract D's input end.
INPUT_URI: dict[str, str] = {
    "cost_lot_breakdown":      COST + "ProductionLot",
    "cost_unit_price_trend":   COST + "ProductionProgram",
    "cost_rate_comparison":    COST + "ProductionLot",
    "cost_labor_composition":  COST + "ProductionLot",
    "cost_price_composition":  COST + "ProductionLot",
    "cost_rate_assumptions":   COST + "RateTable",
    "cost_category_breakdown": COST + "CostCategory",
    "cost_supplier_concentration": COST + "Supplier",
    # THE SUBJECT IS THE RECIPIENT, not a lot. This verb is asked "what may THIS
    # party be shown", and the entitlement scope is the question rather than a
    # filter applied afterwards.
    "package_export":              COST + "DisclosureRecipient",
}

#: Money is dollars throughout. Declared per row rather than assumed, because "dollars or
#: thousands of dollars" is the one question a cost answer must never leave to convention.
VALUE_UNIT = "USD"

#: HUMAN NAMES FOR THE GENERIC AXIS. `entity_name` is what a card prints; `entity_id` stays the
#: engine's own key so a reader of the payload still sees their own vocabulary.
_CATEGORY_LABELS = {
    "labor": "Labor", "material": "Material", "other_direct": "Other direct",
    "warranty": "Warranty", "contracts": "Contracted effort",
}
_LABOR_LABELS = {"touch": "Touch labor", "support": "Support labor", "sepm": "SEPM"}
_RATE_LABELS = {
    "fringe": "Fringe", "overhead": "Overhead", "g_and_a": "G&A",
    "cost_of_money": "Cost of money", "profit": "Profit", "escalation": "Escalation",
}
HOURS_UNIT = "hours"

#: The default concentration bound, ONE QUARTER of purchased value. A round, defensible
#: figure rather than a tuned one -- and it is DISCLOSED in every answer that uses it
#: (see `cost_supplier_concentration`), because a threshold the caller cannot see makes
#: the verdict unreproducible.
DEFAULT_CONCENTRATION_THRESHOLD = Decimal("0.25")


# ---------------------------------------------------------------------------------------
# THE `method` BLOCK — how a figure was computed, travelling with the figure
#
# THE SHAPE IS THE UI's, NOT MINE. `cortex-ui/src/lib/cardExport.ts` already declares
# `MethodBlock { formula: string; inputs: {name, value}[]; bound: string | null }` and reads it
# with `readMethod`, which DROPS THE BLOCK WHOLE when `formula` is empty and runs `formatLeaf`
# over whatever `bound` holds. So `bound` is a STRING here, not the nested
# `{name, value, defaulted}` object that reads better in JSON: the nested form would arrive as a
# JSON blob printed inside the bound cell — a producer and a consumer each complete on its own
# side, disagreeing in the seam nobody asserts.
#
# WHETHER THE BOUND WAS DEFAULTED IS SAID IN WORDS, AND AGAIN AS A FLAG. The words are what the
# UI renders today; `bound_defaulted` is for a reader that needs to branch on it. Both are
# derived from the SAME argument inside this one helper, so they cannot go out of agreement —
# the only reason two statements of one fact are allowed here.
#
# `bound_defaulted` IS `None`, NEVER `False`, WHEN THERE IS NO BOUND. `False` means "there is a
# bound and the caller chose it", which is a claim about a caller who was never asked. Three of
# the four rankings have no bound at all, and a plausible-looking `false` reads as considered.
#
# THE SHA IS THE ARTIFACT's, NOT GIT's. `_baked_algorithm_sha()` reads `IAGENT_GIT_SHA` off the
# image and returns None when it is absent or the literal "unknown" — the same claim
# `package_export` attests with, and the only one available in a pod. None rather than a
# placeholder, because "unknown" is a sha-shaped string that matches no commit and a reader must
# be able to tell "not attested" from "attested as this".
# ---------------------------------------------------------------------------------------
def _input_value(value: Any) -> Any:
    """Every stated value as a string, except None.

    Decimal is not JSON and float rounds the money it is printing, so a Decimal MUST be
    stringified. Doing it to the ints and strings too keeps one column one type — a column that
    mixes them makes the card decide how to format per row, which is how two figures on one card
    come to disagree about their own precision. None stays None: absent is not the word "None".
    """
    return None if value is None else str(value)


def _method(
    *,
    formula: str,
    inputs: list[tuple[str, Any]],
    bound: Optional[str] = None,
    bound_defaulted: Optional[bool] = None,
) -> dict[str, Any]:
    """The producer's account of its own arithmetic.

    `inputs` is an ORDERED list of pairs rather than a dict, because the order is part of the
    account: the names appear in the order the formula uses them and a reader recomputing the
    figure reads down the list. `readMethod` accepts either shape; only one of them is readable.

    The bound and its flag are checked against each other rather than trusted, because the two
    ways of getting this wrong are the two that read as deliberate — a bound with no word on
    where it came from, and a defaulted flag on a measure that has no bound.
    """
    if not formula.strip():
        raise ValueError(
            "a method block with no formula is dropped WHOLE by the UI's readMethod, so an "
            "empty formula ships a card reading 'method not supplied' about a method this "
            "producer does in fact have"
        )
    if (bound is None) != (bound_defaulted is None):
        raise ValueError(
            f"bound={bound!r} and bound_defaulted={bound_defaulted!r} disagree about whether "
            "this measure has a bound; a flag without a bound, or a bound without a flag, is "
            "the half-stated disclosure this block exists to end"
        )
    return {
        "formula": formula,
        "inputs": [{"name": n, "value": _input_value(v)} for n, v in inputs],
        "bound": bound,
        "bound_defaulted": bound_defaulted,
        "producer_sha": _baked_algorithm_sha(),
    }


def _bound_text(*, name: str, value: Any, defaulted: bool) -> str:
    """The bound as one sentence, saying who chose it.

    "0.25" alone is the EAC-without-method ambiguity in another costume: a verdict against a
    bound the reader cannot attribute is unreproducible, and nothing in the figure distinguishes
    the engine's round quarter from a threshold the caller tuned.
    """
    origin = "engine default, the caller stated none" if defaulted else "stated by the caller"
    return f"{name} = {value} ({origin})"


def _require_vintage(state: CostState, fiscal_year: int, rate_vintage: Optional[str]) -> str:
    """The designed refusal: a forward-looking figure needs its assumption set NAMED.

    Analogue of Engine F's mandatory EAC method. Defaulting to the newest vintage would hand
    back a price whose basis the caller never chose and cannot see — and a caller acting on
    it could not reproduce it, which is the whole property this engine exists to provide.
    """
    if rate_vintage:
        return rate_vintage
    available = state.vintages(fiscal_year)
    raise VintageRequired(
        f"a price for fiscal year {fiscal_year} depends on which rate vintage is applied, "
        f"and the vintages for that year differ. Name one of: {', '.join(available)}",
        available=available,
    )


#: Legal values for a mandatory slot, computed from the slots the caller DID supply.
#:
#: ── WHY THIS EXISTS: THE BETTER REFUSAL WAS UNREACHABLE ──────────────────────────────────
#: `_require_vintage` above carries `available` — the two vintages, by name — precisely so the
#: caller's next question is answerable. IT CANNOT FIRE THROUGH THE HTTP ROUTE. `rate_vintage`
#: is a spoken-mandatory slot, so `/measure/{fn}` returns `slot_required` BEFORE the verb is
#: ever called, and the caller is told "needs rate_vintage" with no way to learn what a
#: vintage looks like. Measured on the wire 2026-09-11, not reasoned about: the refusal
#: carried `missing` and `declarations` and no values at all.
#:
#: A refusal that withholds the options is a dead end wearing a refusal's clothes — the walk
#: sheet's own standard, written before anyone had looked at the payload.
#:
#: KEYED ON (verb, slot) AND CONTEXT-DEPENDENT BY DESIGN. The vintages are a property of the
#: LOT's fiscal year, so there is no static enum to declare — which is exactly why this slot
#: fell through `_ENUM_VALUES` and `_REFERENT_KIND` both, and why nothing could enumerate it.
def _vintage_options(state: CostState, params: dict[str, Any]) -> Optional[list[str]]:
    lot_number = params.get("lot")
    if lot_number is None:
        return None
    try:
        return state.vintages(state.lot(int(lot_number)).fiscal_year)
    except (NotInModel, TypeError, ValueError):
        # AN UNKNOWN LOT IS NOT AN OPTIONS PROBLEM. The caller gets `slot_required` for the
        # vintage; that the lot is also wrong belongs to the lot's own refusal, and guessing
        # here would attach a second diagnosis to the first one's message.
        return None


#: Keyed on the SLOT NAME, and applied to EVERY verb that declares it.
#:
#: ⚠ THIS WAS KEYED ON (verb, slot) AND HELD ONE ENTRY, WHICH MADE THE FIX A SAMPLE.
#: `cost_rate_comparison` got its options; `cost_lot_breakdown` and `cost_price_composition`
#: declare the SAME mandatory `rate_vintage` and got none. Measured on a live card 2026-09-12:
#: the ask rendered "Which rate vintage?" as a bare text box, because the refusal it came from
#: carried no options for cortex to draw. I had fixed the verb I was looking at.
#:
#: KEYED BY SLOT BECAUSE THE SLOT IS WHAT HAS OPTIONS. A rate vintage means the same thing in
#: every verb that takes one, and the source reads `params` so it adapts to the lot in hand.
#: This is not a tidier registry — it is a registry that CANNOT be a sample: a tenth verb
#: declaring `rate_vintage` is covered by the commit that adds it, with nothing to remember.
_SLOT_OPTION_SOURCES: dict[str, Any] = {
    "rate_vintage": _vintage_options,
}


def options_for(state: CostState, fn_name: str, slot: str,
                params: dict[str, Any]) -> Optional[list[str]]:
    """Legal values for a missing slot, or None when the engine cannot compute them.

    NONE AND [] MEAN DIFFERENT THINGS and the route keeps them apart: None is "not computable
    from what you supplied"; [] would be "there are genuinely none". Collapsing them is how a
    caller reads "no vintages exist" from "you did not name a lot".

    `fn_name` is accepted and deliberately unused: the contract is per-slot, and taking the
    verb keeps the door open for a verb-specific override without changing every call site.
    """
    source = _SLOT_OPTION_SOURCES.get(slot)
    return source(state, params) if source else None


def _applied_rates(state: CostState, lot_number: int, rate_vintage: Optional[str]):
    lot = state.lot(lot_number)
    vintage = _require_vintage(state, lot.fiscal_year, rate_vintage)
    return lot, rates_for(state.rates, lot.fiscal_year, vintage)


# ---------------------------------------------------------------------------------------
# 1. cost_lot_breakdown — per-category price and hours for one lot
# ---------------------------------------------------------------------------------------
def cost_lot_breakdown(state: CostState, *, lot: int, rate_vintage: str) -> dict[str, Any]:
    """Decompose one lot's cost into its five accounting buckets."""
    lot_obj, rates = _applied_rates(state, lot, rate_vintage)
    rows = [
        {"category": "labor",        "price": lot_obj.direct_labor,
         "hours": sum((l.hours for l in lot_obj.labor), Decimal("0"))},
        {"category": "material",     "price": lot_obj.material,     "hours": None},
        {"category": "other_direct", "price": lot_obj.other_direct, "hours": None},
        {"category": "warranty",     "price": lot_obj.warranty,     "hours": lot_obj.warranty_hours},
        {"category": "contracts",    "price": lot_obj.contracts,    "hours": None},
    ]
    for r in rows:
        r["price"] = str(r["price"])
        r["hours"] = None if r["hours"] is None else str(r["hours"])
        r["value_unit"] = VALUE_UNIT
        r["hours_unit"] = HOURS_UNIT
    # THE GENERIC AXIS KEYS BESIDE THE DOMAIN ONES. A binding row alone renders nothing:
    # CONTRIBUTION_RANKING draws entity_id / entity_name / contribution, and a payload carrying
    # only `category` and `price` has, to the component, no axes at all. That is the defect
    # that produced three blank cards in one morning on the planning side — correct on both
    # sides, wrong only in the seam, and visible only in a browser.
    _total = sum(Decimal(r["price"]) for r in rows)
    for _r in rows:
        _amount = Decimal(_r["price"])
        _r["entity_id"] = _r["category"]
        _r["entity_name"] = _CATEGORY_LABELS.get(_r["category"], _r["category"])
        _r["contribution"] = float(_amount)
        # NULL WHEN THE TOTAL IS ZERO. There is no share of nothing, and the contract says it
        # renders as absent rather than as 0%.
        _r["share_of_total"] = float(_amount / _total) if _total else None
    rows.sort(key=lambda r: r["contribution"], reverse=True)
    for _i, _r in enumerate(rows, start=1):
        _r["rank"] = _i
    return {
        "output_uri": OUTPUT_URI["cost_lot_breakdown"],
        "value_label": "Cost",
        "scope_label": f"Lot {lot_obj.number}",
        "lot": lot_obj.number,
        "quantity": lot_obj.quantity,
        "fiscal_year": lot_obj.fiscal_year,
        "rate_vintage": rates.vintage,
        # THE DENOMINATOR IS AN INPUT, not a decoration. `share_of_total` cannot be checked
        # without the total, and the total appears nowhere else in this payload — a reader can
        # add the five prices back up, which is exactly the arithmetic the block exists to spare
        # them.
        "method": _method(
            formula=(
                "contribution = the lot's recorded price for the category; "
                "share_of_total = contribution / lot total (null when the total is zero); "
                "rank = position by descending contribution"
            ),
            inputs=[
                ("lot", lot_obj.number),
                ("rate_vintage", rates.vintage),
                ("fiscal_year", lot_obj.fiscal_year),
                ("lot total", _total),
                ("categories", len(rows)),
            ],
        ),
        "rows": rows,
    }


# ---------------------------------------------------------------------------------------
# 2. cost_unit_price_trend — unit price per lot across the program, by category
# ---------------------------------------------------------------------------------------
def cost_unit_price_trend(state: CostState, *, category: Optional[str] = None) -> dict[str, Any]:
    """Cost per unit at each successive lot. The ORDER is the answer, not the values.

    Takes no rate vintage: each lot is priced at the rates that were actually applied to it,
    which is what makes the series comparable across years. A single vintage imposed across
    nine fiscal years would be a counterfactual, not a trend.
    """
    points: list[dict[str, Any]] = []
    for n in state.lot_numbers:
        lot_obj = state.lot(n)
        vintage = state.vintages(lot_obj.fiscal_year)[0]
        rates = rates_for(state.rates, lot_obj.fiscal_year, vintage)
        build = compose_price(
            direct_labor=lot_obj.direct_labor,
            material=lot_obj.material,
            other_direct=lot_obj.other_direct + lot_obj.warranty + lot_obj.contracts,
            rates=rates,
        )
        points.append({
            "lot": n,
            "quantity": lot_obj.quantity,
            "fiscal_year": lot_obj.fiscal_year,
            "unit_price": str(unit_price(build, lot_obj.quantity)),
            "value_unit": VALUE_UNIT,
            "rate_vintage": rates.vintage,
        })
    # MULTI_SERIES DRAWS `rows` KEYED BY `period`, WITH `series` DECLARING WHICH KEYS CARRY
    # NUMBERS. The domain list keeps its own name (`points`); it was called `series`, which is
    # the name the archetype needs for the DECLARATION — one word meaning two things in one
    # payload is how a renderer ends up drawing the wrong half.
    _rows = [{"period": f"Lot {p['lot']}", "unit_price": float(p["unit_price"]),
              "lot": p["lot"], "fiscal_year": p["fiscal_year"], "quantity": p["quantity"],
              "rate_vintage": p["rate_vintage"]} for p in points]
    return {
        "output_uri": OUTPUT_URI["cost_unit_price_trend"],
        "rows": _rows,
        "series": [{"key": "unit_price", "label": "Unit price", "unit": VALUE_UNIT}],
        "value_label": "Cost per unit",
        "scope_label": state.program_name,
        "program": state.program_name,
        "category": category or "all",
        "points": points,
    }


# ---------------------------------------------------------------------------------------
# 3. cost_rate_comparison — applied rates against the rates assumed at estimate
# ---------------------------------------------------------------------------------------
def cost_rate_comparison(state: CostState, *, lot: int, rate_vintage: str) -> dict[str, Any]:
    """Applied versus estimating rates for one lot, factor by factor."""
    lot_obj, applied = _applied_rates(state, lot, rate_vintage)
    est = lot_obj.estimating_rates
    factors = ("fringe", "overhead", "g_and_a", "cost_of_money", "profit", "escalation")
    rows = []
    for f in factors:
        a, e = getattr(applied, f), getattr(est, f)
        rows.append({
            "factor": f,
            "applied": str(a),
            "estimating": str(e),
            "delta": str(a - e),
            # A rate is a factor, not an amount — it carries no monetary unit, and saying
            # so explicitly stops a renderer appending one.
            "value_unit": None,
        })
    # DELTA_SET, AND THE AXIS TEST IS IN ITS OWN CONTRACT'S FIRST LINE: "it renders a
    # COMPARISON, never a state." That is exactly this verb — applied against estimating,
    # factor by factor. CONTRIBUTION_RANKING was the alternative and fails concretely:
    # `entity_id` would carry a METRIC NAME (fringe is a factor, not an entity), which is the
    # borrowed-name defect that contract refuses in the other direction; `contribution` would
    # contribute to nothing, because rates do not sum to a total; `share_of_total` has no
    # meaning at all; and ORDER here is the sequence in which factors are STRUCK, not a
    # ranking — rendering it as one would assert that fringe outranks profit.
    #
    # DIRECTION AND MAGNITUDE ARE THIS MEASURE'S JUDGEMENT, not the renderer's. A higher
    # applied rate than estimated raises the price, so it is `degraded`; the contract is
    # explicit that inferring direction from the sign of a delta is the renderer's job to
    # refuse.
    #
    # `affected` NAMES THE STEPS THE FACTOR FEEDS, so it is neither empty nor invented: the
    # composition already declares which step each rate key drives. A required field with
    # nothing to put in it is the declared-but-unwired shape, and this avoids it with fact.
    _effects = []
    for _r in rows:
        _d = Decimal(_r["delta"])
        _effects.append({
            "metric": _RATE_LABELS.get(_r["factor"], _r["factor"]),
            "direction": "neutral" if _d == 0 else ("degraded" if _d > 0 else "improved"),
            "magnitude": f"{_d:+.3f} vs estimate",
            # ESCALATION IS NOT A STEP, so it has no `rate_key` and the list came out EMPTY -
            # caught by the seal that refuses an empty `affected`, not by reading. It is
            # applied to the BASE AMOUNTS before any burden is struck, so it affects the base
            # and, through it, every step that is struck on the base. Naming only "Base cost"
            # would understate it; naming every step is what actually happens.
            "affected": ([s.name for s in DEFAULT_COMPOSITION if s.rate_key == _r["factor"]]
                         or (["Base cost"] + [s.name for s in DEFAULT_COMPOSITION]
                             if _r["factor"] == "escalation" else [])),
            "delta": float(_d),
            "factor": _r["factor"],
            "applied": _r["applied"],
            "estimating": _r["estimating"],
        })
    return {
        "output_uri": OUTPUT_URI["cost_rate_comparison"],
        "effects": _effects,
        "scope_label": f"Lot {lot_obj.number} - applied vs estimating rates",
        "lot": lot_obj.number,
        "fiscal_year": lot_obj.fiscal_year,
        "applied_vintage": applied.vintage,
        "estimating_vintage": est.vintage,
        "rows": rows,
    }


# ---------------------------------------------------------------------------------------
# 4. cost_labor_composition — touch / support / SEPM split for one lot
# ---------------------------------------------------------------------------------------
def cost_labor_composition(state: CostState, *, lot: int) -> dict[str, Any]:
    """Worked effort by kind of work. No vintage: these are recorded hours and rates."""
    lot_obj = state.lot(lot)
    total = lot_obj.direct_labor
    rows = []
    for kind in ("touch", "support", "sepm"):
        line = lot_obj.labor_of(kind)  # type: ignore[arg-type]
        rows.append({
            "labor_kind": kind,
            "hours": str(line.hours),
            "rate": str(line.rate),
            "cost": str(line.cost),
            "share_of_labor": str((line.cost / total).quantize(Decimal("0.0001"))),
            "value_unit": VALUE_UNIT,
            "hours_unit": HOURS_UNIT,
        })
    for _r in rows:
        _r["entity_id"] = _r["labor_kind"]
        _r["entity_name"] = _LABOR_LABELS.get(_r["labor_kind"], _r["labor_kind"])
        _r["contribution"] = float(Decimal(_r["cost"]))
        _r["share_of_total"] = (float(Decimal(_r["share_of_labor"]))
                                if _r.get("share_of_labor") is not None else None)
    rows.sort(key=lambda r: r["contribution"], reverse=True)
    for _i, _r in enumerate(rows, start=1):
        _r["rank"] = _i
    return {
        "output_uri": OUTPUT_URI["cost_labor_composition"],
        "value_label": "Labor cost",
        "scope_label": f"Lot {lot_obj.number}",
        "lot": lot_obj.number,
        "fiscal_year": lot_obj.fiscal_year,
        "total_labor": str(total),
        "value_unit": VALUE_UNIT,
        # NO RATE VINTAGE IN THE INPUTS, and its absence is stated in the formula rather than
        # left to be noticed: these are recorded hours and applied rates, not a forward-looking
        # figure, so there is no assumption set to name. A vintage listed here would be an input
        # this verb never reads.
        "method": _method(
            formula=(
                "contribution = recorded hours x the rate applied to that kind of work; "
                "share_of_total = contribution / lot direct labor; "
                "rank = position by descending contribution. Recorded hours and applied rates, "
                "so no rate vintage is involved"
            ),
            inputs=[
                ("lot", lot_obj.number),
                ("fiscal_year", lot_obj.fiscal_year),
                ("lot direct labor", total),
                ("labor kinds", len(rows)),
            ],
        ),
        "rows": rows,
    }


# ---------------------------------------------------------------------------------------
# 5. cost_price_composition — base -> ... -> price, the full ordered stack
#
# THE VERB ADR-0047's EXPORT PACKAGE IS BUILT AROUND. Its output is the one shape no
# existing archetype renders — a waterfall — which the packet flags as a real cortex build
# rather than a binding row. The verb returns the ordered steps and does NOT flatten them:
# flattening here would be the variance-tree defect repeated, where the shape a reader needs
# is destroyed by the producer to fit an archetype that was never right.
# ---------------------------------------------------------------------------------------
def cost_price_composition(state: CostState, *, lot: int, rate_vintage: str) -> dict[str, Any]:
    """The ordered build-up from base cost to final price for one lot."""
    lot_obj, rates = _applied_rates(state, lot, rate_vintage)
    build = compose_price(
        direct_labor=lot_obj.direct_labor,
        material=lot_obj.material,
        other_direct=lot_obj.other_direct + lot_obj.warranty + lot_obj.contracts,
        rates=rates,
    )
    return {
        "output_uri": OUTPUT_URI["cost_price_composition"],
        # THE CARD'S FRAMING, and the reason `lot` and `fiscal_year` do not need carrying
        # through the projector: this says which walk the reader is looking at, in one field
        # the renderer already reads. STEP_LADDER's passthrough advertised `scope_label` and
        # this producer did not emit it — the same defect as advertising a field nothing reads,
        # pointing the other way, and the card would have drawn a build-up framed by nothing.
        "scope_label": f"Lot {lot_obj.number} at {rates.vintage} rates",
        "lot": lot_obj.number,
        "quantity": lot_obj.quantity,
        "fiscal_year": build.fiscal_year,
        "rate_vintage": build.rate_vintage,
        "price": str(build.price),
        "unit_price": str(unit_price(build, lot_obj.quantity)),
        "value_unit": VALUE_UNIT,
        # The steps are the answer. `sums` is carried so a consumer can assert the
        # invariant without re-adding — and so a card can show that it was checked.
        "sums": build.sums(),
        "steps": [
            {
                "name": s.name,
                "rate": None if s.rate is None else str(s.rate),
                # NULL, not "0", for the seed step. See CompositionStep.basis.
                "basis": None if s.basis is None else str(s.basis),
                "amount": str(s.amount),
                "running_total": str(s.running_total),
                "value_unit": VALUE_UNIT,
            }
            for s in build.steps
        ],
    }


# ---------------------------------------------------------------------------------------
# 6. cost_rate_assumptions — the rate table at a vintage
# ---------------------------------------------------------------------------------------
def cost_rate_assumptions(
    state: CostState, *, fiscal_year: Optional[int] = None, rate_vintage: Optional[str] = None
) -> dict[str, Any]:
    """The assumption set in force, so any figure elsewhere can be reproduced.

    Unlike the priced verbs this one may answer WITHOUT a vintage — listing the table is how
    a caller discovers which vintages exist, and refusing here would make the refusal
    elsewhere unanswerable. That asymmetry is deliberate and is the difference between a
    refusal that guides and one that stonewalls.
    """
    keys = sorted(state.rates)
    if fiscal_year is not None:
        keys = [k for k in keys if k[0] == fiscal_year]
        if not keys:
            raise NotInModel(
                f"fiscal year {fiscal_year} is not in the rate table; known years are "
                f"{sorted({fy for fy, _ in state.rates})}"
            )
    if rate_vintage is not None:
        keys = [k for k in keys if k[1] == rate_vintage]
        if not keys:
            raise NotInModel(f"no rate set at vintage {rate_vintage!r}")

    rows = []
    for fy, vintage in keys:
        r = state.rates[(fy, vintage)]
        rows.append({
            "fiscal_year": fy,
            "rate_vintage": vintage,
            "fringe": str(r.fringe),
            "overhead": str(r.overhead),
            "g_and_a": str(r.g_and_a),
            "cost_of_money": str(r.cost_of_money),
            "profit": str(r.profit),
            "escalation": str(r.escalation),
            "value_unit": None,          # factors, not amounts
        })
    # THE VINTAGE IS THE PERIOD. Rates are a series over the dates they were set, and the six
    # factors are the declared series — which is what a rate table IS, read as data rather
    # than as a spreadsheet.
    _factors = ("fringe", "overhead", "g_and_a", "cost_of_money", "profit", "escalation")
    _rows = [dict(r, period=r["rate_vintage"],
                  **{f: float(Decimal(r[f])) for f in _factors}) for r in rows]
    return {
        "output_uri": OUTPUT_URI["cost_rate_assumptions"],
        "rows": _rows,
        # ⚠ THIS DERIVED THE LABEL FROM THE KEY AND PUT "G And A" ON A LIVE CHART.
        # `_RATE_LABELS` already holds the human names — `cost_rate_comparison` reads it at
        # line 325 — and this series builder title-cased the key instead, so ONE verb spoke
        # the domain's vocabulary and its neighbour invented a second one for the same six
        # factors. A renderer cannot tell a derived label from an authored one; it drew
        # exactly what was sent.
        #
        # `.title()` on an identifier is the tell: it is a plausible label for every key and
        # a correct one only for keys that happen to be ordinary words.
        "series": [{"key": f, "label": _RATE_LABELS.get(f, f.replace("_", " ").title()),
                    "unit": None}
                   for f in _factors],
        "value_label": "Rate",
        "scope_label": state.program_name,
        "program": state.program_name,
        # THE DOMAIN ROWS KEEP THEIR EXACT STRINGS. `rows` above carries the same figures as
        # floats for the renderer; this is the assertion-grade copy.
        "rate_sets": rows,
    }


# ---------------------------------------------------------------------------------------
# 7. cost_category_breakdown - SHARE and MOVEMENT, not amount
#
# DELIBERATELY DISTINCT FROM cost_lot_breakdown, and the anti-synonyms carry the split:
# that verb reports what each bucket COST (absolute figures, hours, and therefore the rate
# assumptions behind them); this one reports what SHARE each bucket is and how that share
# MOVED against the preceding lot. Two lots with identical totals can divide them
# differently, and the division is the thing a reader acts on.
#
# NO rate_vintage, and that is a consequence rather than an omission: a share is a ratio of
# recorded costs, so it does not depend on which assumption set produced the amounts. A verb
# that demanded a vintage it does not use would be ceremony.
# ---------------------------------------------------------------------------------------
def cost_category_breakdown(state: CostState, *, lot: int) -> dict[str, Any]:
    """How one lot's cost divides across its buckets, and how the division moved."""
    lot_obj = state.lot(lot)
    prior = state.lots.get(lot - 1)

    def buckets(l) -> dict[str, Decimal]:
        return {
            "labor": l.direct_labor,
            "material": l.material,
            "other_direct": l.other_direct,
            "warranty": l.warranty,
            "contracts": l.contracts,
        }

    mine = buckets(lot_obj)
    total = sum(mine.values(), Decimal("0"))
    if total <= 0:  # pragma: no cover - the seed guards against it, but a share of zero
        raise NotInModel(f"lot {lot} has no recorded cost, so it has no division")
    prior_shares = None
    prior_per_unit = None
    if prior is not None:
        p = buckets(prior)
        ptotal = sum(p.values(), Decimal("0"))
        prior_shares = {k: (v / ptotal) for k, v in p.items()} if ptotal > 0 else None
        # PER UNIT, NOT PER LOT. Lot 4 is 24 units against lot 3's 18, so a bucket costing
        # more in total says nothing about whether it got better or worse. Normalising by
        # quantity is what makes the comparison a verdict rather than an observation about
        # lot size.
        if prior.quantity:
            prior_per_unit = {k: (v / prior.quantity) for k, v in p.items()}

    rows = []
    for name, amount in mine.items():
        share = (amount / total).quantize(Decimal("0.0001"))
        row = {
            "category": name,
            "share_of_total": str(share),
            "amount": str(amount),
            "value_unit": VALUE_UNIT,
            # A share is a ratio, not an amount. Saying so stops a renderer appending a
            # currency to it.
            "share_unit": None,
        }
        if prior_shares is not None:
            delta = (share - prior_shares[name]).quantize(Decimal("0.0001"))
            row["share_delta_vs_prior_lot"] = str(delta)
            # RENAMED FROM `direction`. This engine used ONE FIELD NAME FOR TWO VOCABULARIES in
            # this file: `cost_rate_comparison` emits DELTA_SET's improved/degraded/neutral,
            # and this emitted up/down/flat. Only the first happened to agree with what a
            # consumer reads, so the collision was invisible until a card tried to draw. The
            # name now says which movement it describes, and the DELTA_SET vocabulary is left
            # to mean only itself.
            row["share_direction"] = ("up" if delta > 0
                                      else ("down" if delta < 0 else "flat"))
        else:
            # FIRST LOT HAS NO PRIOR, and that is reported rather than rendered as zero
            # movement — a flat delta and an absent one mean different things.
            row["share_delta_vs_prior_lot"] = None
            row["share_direction"] = None

        # `favourable` IS THE PRODUCER'S VERDICT AND CORTEX WILL NOT INFER IT. Its contract is
        # explicit: "in cost variance a positive number is favourable; in other measures the
        # same sign is not. A renderer deciding from `contribution > 0` would be right on this
        # payload and wrong on the next one."
        #
        # SO WHAT IS THE VERDICT HERE? NOT the share movement, which is what the obvious
        # mapping (up -> degraded) would use. A share is a composition, not a cost: labor's
        # share can rise because material fell, on a lot that got cheaper overall. Calling that
        # "degraded" would be a false claim rendered in red, and the reader has no way to
        # check it.
        #
        # The honest verdict is PER-UNIT COST MOVEMENT: this bucket cost more or less per unit
        # than it did last lot. That is a real cost judgement, it is quantity-normalised, and
        # it is the question a cost reader means by "is that better or worse".
        #
        # ABSENT ON THE FIRST LOT rather than defaulted. There is no verdict without a prior,
        # and `favourable: false` would read as "this got worse".
        if prior_per_unit is not None and lot_obj.quantity:
            per_unit = amount / lot_obj.quantity
            # QUANTIZED FIRST, AND THE VERDICT READS THE QUANTIZED FIGURE. Comparing the raw
            # values would let a bucket display "0.00" and still carry a verdict, which is the
            # card disagreeing with itself on its own row.
            moved = (per_unit - prior_per_unit[name]).quantize(Decimal("0.01"))
            row["per_unit_amount"] = str(per_unit.quantize(Decimal("0.01")))
            row["per_unit_delta_vs_prior_lot"] = str(moved)
            # ABSENT WHEN NOTHING MOVED. `favourable` is a boolean in cortex's contract, and
            # False means "this got worse" — it is not a resting state. An unchanged bucket has
            # no verdict, and the first version emitted False for two of them, which would have
            # rendered an adverse tone on a row displaying 0.00.
            if moved != 0:
                row["favourable"] = moved < 0
        else:
            row["per_unit_amount"] = None
            row["per_unit_delta_vs_prior_lot"] = None
        rows.append(row)

    for _r in rows:
        _r["entity_id"] = _r["category"]
        _r["entity_name"] = _CATEGORY_LABELS.get(_r["category"], _r["category"])
        _r["contribution"] = float(Decimal(_r["amount"]))
        _r["share_of_total"] = (float(Decimal(_r["share_of_total"]))
                                if isinstance(_r.get("share_of_total"), str) else None)
    rows.sort(key=lambda r: r["contribution"], reverse=True)
    for _i, _r in enumerate(rows, start=1):
        _r["rank"] = _i
    return {
        "output_uri": OUTPUT_URI["cost_category_breakdown"],
        "value_label": "Cost",
        "scope_label": f"Lot {lot_obj.number}",
        "lot": lot_obj.number,
        "fiscal_year": lot_obj.fiscal_year,
        "total": str(total),
        "value_unit": VALUE_UNIT,
        "compared_to_lot": None if prior is None else prior.number,
        # THE FORMULA SAYS WHAT `favourable` IS ABOUT, because the obvious reading is wrong and
        # the card gives a reader no way to check. It is PER-UNIT COST MOVEMENT, not the share
        # movement beside it: a bucket's share can rise because another bucket fell, on a lot that
        # got cheaper overall, and "degraded" rendered in red over that would be a false claim.
        # The same sentence also says where the verdict is ABSENT, which is the half a reader
        # cannot infer from a card that simply does not draw one.
        "method": _method(
            formula=(
                "contribution = the lot's recorded amount for the bucket; "
                "share_of_total = amount / lot total; "
                "share_delta_vs_prior_lot = this share - the prior lot's share; "
                "per_unit_amount = amount / lot quantity; "
                "favourable = the bucket's PER-UNIT amount fell against the prior lot -- not its "
                "share, which can rise on a lot that got cheaper. Absent on the first lot, and "
                "absent when the per-unit figure did not move"
            ),
            inputs=[
                ("lot", lot_obj.number),
                ("fiscal_year", lot_obj.fiscal_year),
                ("lot total", total),
                ("lot quantity", lot_obj.quantity),
                ("compared_to_lot", None if prior is None else prior.number),
                ("prior lot quantity", None if prior is None else prior.quantity),
            ],
        ),
        "rows": rows,
    }


# ---------------------------------------------------------------------------------------
# 8. cost_supplier_concentration - exposure to any single party, against a STATED bound
#
# THE THRESHOLD IS ALWAYS DISCLOSED, INCLUDING WHEN IT WAS DEFAULTED. A verdict of
# "concentrated" against a bound the caller never saw is the EAC-without-method ambiguity in
# another costume: the number is unactionable without the assumption that produced it. So
# the parameter defaults to None and is resolved HERE, which is what lets the payload report
# `threshold_defaulted` honestly — a signature default could not tell the two apart.
# ---------------------------------------------------------------------------------------
def cost_supplier_concentration(
    state: CostState, *, lot: int, threshold: Optional[float] = None
) -> dict[str, Any]:
    """Which suppliers hold more than `threshold` of a lot's purchased value."""
    lot_obj = state.lot(lot)
    defaulted = threshold is None
    bound = DEFAULT_CONCENTRATION_THRESHOLD if defaulted else Decimal(str(threshold))
    if not (Decimal("0") < bound < Decimal("1")):
        raise NotInModel(
            f"threshold {bound} is not a share between 0 and 1; concentration is a "
            "proportion of purchased value, not an amount"
        )

    purchased = sum((s.amount for s in lot_obj.suppliers), Decimal("0"))
    if purchased <= 0:  # pragma: no cover - guarded by the seed's own consistency check
        raise NotInModel(f"lot {lot} records no purchased value to concentrate")

    ranked = sorted(lot_obj.suppliers, key=lambda s: s.amount, reverse=True)
    rows = []
    for s in ranked:
        share = (s.amount / purchased).quantize(Decimal("0.0001"))
        rows.append({
            "supplier": s.name,
            "amount": str(s.amount),
            "share_of_purchased": str(share),
            "above_threshold": share > bound,
            "value_unit": VALUE_UNIT,
        })

    above = [r for r in rows if r["above_threshold"]]
    top = Decimal(rows[0]["share_of_purchased"]) if rows else Decimal("0")
    for _i, _r in enumerate(rows, start=1):
        _r["entity_id"] = _r["supplier"]
        _r["entity_name"] = _r["supplier"]
        _r["contribution"] = float(Decimal(_r["amount"]))
        _r["share_of_total"] = float(Decimal(_r["share_of_purchased"]))
        _r["rank"] = _i          # already ranked largest-first; order IS the answer here
    return {
        "output_uri": OUTPUT_URI["cost_supplier_concentration"],
        "value_label": "Purchased value",
        "scope_label": f"Lot {lot_obj.number}",
        "lot": lot_obj.number,
        "fiscal_year": lot_obj.fiscal_year,
        "purchased_value": str(purchased),
        "value_unit": VALUE_UNIT,
        # THE BOUND TRAVELS WITH THE VERDICT, always, and says whether the caller chose it.
        "threshold": str(bound),
        "threshold_defaulted": defaulted,
        "suppliers_above_threshold": len(above),
        "largest_share": str(top),
        # THE ONE RANKING WITH A BOUND, so it is the one whose `bound` is not null. The top-level
        # `threshold`/`threshold_defaulted` pair STAYS: it is the existing wire contract, the
        # projector's allowlist names it, and cortex reads it. This block does not replace it — it
        # states the same bound where the formula that uses it can be read beside it, and both come
        # from the same two locals, so they cannot disagree.
        "method": _method(
            formula=(
                "contribution = the supplier's purchased amount in this lot; "
                "share_of_purchased = amount / total purchased value; "
                "above_threshold = share_of_purchased > threshold (strictly greater: a supplier "
                "sitting exactly ON the bound is not above it); "
                "rank = position by descending amount"
            ),
            inputs=[
                ("lot", lot_obj.number),
                ("fiscal_year", lot_obj.fiscal_year),
                ("total purchased value", purchased),
                ("suppliers", len(rows)),
            ],
            bound=_bound_text(name="threshold", value=bound, defaulted=defaulted),
            bound_defaulted=defaulted,
        ),
        "rows": rows,
    }



def package_export(
    state: CostState, *, recipient_scope: str, include_dataset: Optional[bool] = None
) -> dict[str, Any]:
    """Produce a customer-validation package for one recipient. A GOVERNED EMIT (ADR-0047).

    THIS IS WHY PACKAGING IS A VERB AND NOT A SCRIPT. A script leaves no trace: run twice, or
    run for the wrong party, and afterwards the two are indistinguishable from each other and
    from never having run at all. As a verb it is entitlement-scoped at the point of
    production, it emits an audit line naming what went to whom under which algorithm, and it
    is refusable by the same machinery that refuses every other verb.

    `recipient_scope` IS SPOKEN-MANDATORY. There is no default and no "all lots" fallback: a
    disclosure verb that can be invoked without naming its recipient is one keystroke from
    disclosing the wrong program to the wrong party, and the failure is silent because the
    output looks correct.

    IT CALLS THE SAME BUILDER THE ARTIFACT WAS BUILT WITH — `build_html`, imported, not
    reimplemented. Same-algorithm applies to the packager too: a verb that produced a
    near-identical page would make every seal in the export suite a statement about a
    different artifact than the one a recipient opens. The JavaScript gate and the manifest
    hashing are load-bearing here, and they are load-bearing because they are the same code.
    """
    scopes = sorted(RECIPIENT_SCOPES)
    if not recipient_scope or not str(recipient_scope).strip():
        raise NotInModel(
            "package_export needs a recipient scope; it is a disclosure and there is no "
            f"default party. Known scopes: {scopes}")
    scope = str(recipient_scope).strip()
    if scope not in RECIPIENT_SCOPES:
        # UNENTITLED, NOT NOT-IN-MODEL. An unknown recipient is an authorisation answer, and
        # ADR-0049 Ruling 4 keeps the two as distinct types precisely so a caller cannot read
        # "we do not disclose to you" as "we have no data".
        raise Unentitled(f"{scope!r} is not an entitled disclosure recipient; known: {scopes}")

    lots = lots_for_recipient(scope)
    # DEFAULTS OFF, and the reason is the engine's own invariant rather than convenience.
    # ADR-0048's slice-2 ruling: the database is the AUTHORING AND INTERCHANGE format, NOT the
    # runtime one — the HTML package verifies entirely on its own. This engine's dependency
    # list is deliberately thin and the deployed image has no duckdb, so defaulting ON made the
    # verb's DEFAULT PATH the one path the deployment cannot serve. A verb whose default
    # refuses is a badly specified verb, not a deployment problem.
    #
    # Asking for it explicitly still works wherever the dependency is present, and refuses BY
    # NAME where it is not.
    with_dataset = bool(include_dataset)

    import sys as _sys

    # ⚠ THIS LINE WAS `parents[2]` AND IT 500'd IN EVERY DEPLOYED POD, ALWAYS.
    #
    # The image flattens `agent_fleet/cost_agent/` to `/app`, so `/app/measures.py` has
    # exactly two parents and `parents[2]` raises IndexError. In a checkout the same
    # expression resolves to the repo root and is correct — which is why every seal is green
    # and why this was invisible until the verb was called in the pod. Measured there, live:
    #
    #     File "/app/measures.py", line 757, in package_export
    #       root = pathlib.Path(__file__).resolve().parents[2]
    #     IndexError: 2
    #
    # THE DAMAGE WAS NOT THE CRASH, IT WAS WHERE THE CRASH LANDED. Two `SourceUnavailable`
    # guards below already refuse BY NAME when the builder or the pinned runtime is absent —
    # exactly the honest answer a pod owes a caller. `parents[2]` threw BEFORE either could
    # run, converting a designed refusal into an untyped 500. Fixing the arithmetic does not
    # make the artifact buildable in a pod; it lets the engine SAY SO.
    root = _repo_root()
    if root is None:
        raise SourceUnavailable(
            "this deployment cannot build the artifact: the package builder and the pinned "
            "Pyodide runtime live in the repository checkout, and this process is running "
            "from a flattened image that carries neither. The GOVERNED half — entitlement "
            "scope, manifest, module hashes and audit line — is computed from the engine's "
            "own modules and is unaffected; ask for it with `manifest_only`."
        )
    if str(root / "scripts") not in _sys.path:
        _sys.path.insert(0, str(root / "scripts"))
    try:
        import build_cost_package as builder
    except ImportError as exc:  # pragma: no cover - packaging deps absent
        raise SourceUnavailable(f"the package builder is not importable here: {exc}") from None

    runtime = root / ".pyodide-cache"
    missing = [f for f in builder.RUNTIME_FILES + ("pyodide.js",)
               if not (runtime / f).exists()]
    if missing:
        # A DISTINCT TYPE, not an empty result. The engine is correct, entitled and willing;
        # what is absent is the pinned runtime. Reporting that as "no data" would send the
        # caller to look at the program instead of at the deployment.
        raise SourceUnavailable(
            f"the pinned Pyodide runtime is not present at {runtime.name}; "
            f"missing {missing}. The package cannot be produced without it.")

    dataset_path = None
    if with_dataset:
        # DUCKDB IS NOT AN ENGINE DEPENDENCY, and that is deliberate rather than an oversight
        # to correct here. This engine's own dependency list says it is "DELIBERATELY THIN ...
        # computes over an in-process notional model and speaks to nobody", and ADR-0048's
        # slice-2 ruling says the database is the AUTHORING AND INTERCHANGE format, not the
        # runtime one. I added this call without reading either.
        #
        # So the absence is REFUSED BY NAME rather than raised as an ImportError from three
        # frames down. The deployed image has no duckdb today, `include_dataset` defaults to
        # True, and an ImportError on a verb's DEFAULT path is the worst available failure:
        # untyped, unattributable, and nothing in the response says which dependency.
        try:
            import duckdb  # noqa: F401
        except ImportError:
            raise SourceUnavailable(
                "this deployment cannot build the .duckdb half: the `duckdb` package is not "
                "installed, and it is not among engine-cost's declared dependencies. The HTML "
                "package verifies on its own - call with include_dataset=false to produce it, "
                "or install duckdb where the dataset is authored."
            ) from None
        import build_cost_dataset as dataset_builder

        dataset_path = root / "dist" / f"cost-{scope}.duckdb"
        dataset_builder.build(scope, dataset_path)

    html = builder.build_html(scope, runtime, duckdb_path=dataset_path)
    problems = builder.check_javascript(html)
    if problems:
        # THE SAME GATE THE SCRIPT USES. A verb that skipped it could emit a package that is
        # blank on open while reporting success, which is the one failure the whole export
        # exists to make impossible.
        raise SourceUnavailable("the produced page's JavaScript does not parse: "
                                + "; ".join(problems))

    package = build_dataset_package(
        state, recipient_scope=scope, algorithm_sha=builder.algorithm_sha(),
        duckdb_path=str(dataset_path), duckdb_hash=dataset_builder.file_hash(dataset_path),
    ) if dataset_path else build_package(
        state, recipient_scope=scope, algorithm_sha=builder.algorithm_sha())

    dest = root / "dist" / f"cost-validation-{scope}.html"
    dest.parent.mkdir(parents=True, exist_ok=True)

    # ⚠ WRITE_BYTES, NOT WRITE_TEXT, AND THE ROUND-TRIP BELOW IS WHAT FOUND IT.
    #
    # `write_text` opens in TEXT MODE, which translates "\n" to the platform line ending. On
    # Windows the file on disk was therefore NEVER the bytes that were produced — measured,
    # 12 produced bytes became 14 on disk with a different sha256.
    #
    # THIS IS A REPRODUCIBILITY DEFECT IN A GOVERNED EMIT, not a cosmetic one. ADR-0047's
    # whole premise is that a recipient can verify the artifact against the manifest that
    # describes it; a hash taken over the produced string would not match the file they
    # downloaded. And the artifact became PLATFORM-DEPENDENT: the same commit, the same seed
    # and the same algorithm produce different bytes and a different hash on Linux and on
    # Windows, so "byte-identical export" was false across the only axis it needed to hold on.
    dest.write_bytes(html.encode("utf-8"))

    # ── THE ROUND TRIP. RE-READ FROM DISK AND HASH WHAT IS ACTUALLY THERE. ──────────────
    #
    # ⚠ UNTIL THIS LANDED, NO HASH OF THE ARTIFACT EXISTED AT ALL. `locator` is
    # `content_hash(body)` — a hash of the package BODY DICT, computed from state — and the
    # HTML was written separately and never hashed. Every figure in the response therefore
    # described what the engine INTENDED to write. A truncated write, a short flush, a full
    # disk: each reports success, and nothing anywhere notices.
    #
    # HASHING `html` IN MEMORY WOULD NOT BE A ROUND TRIP. It would re-state the intent in a
    # second place, and agree with itself for exactly the reason that makes it worthless. The
    # bytes have to come back off the disk, which is the only step that can disagree.
    written = dest.read_bytes()
    artifact_sha256 = "sha256:" + hashlib.sha256(written).hexdigest()
    intended_sha256 = "sha256:" + hashlib.sha256(html.encode("utf-8")).hexdigest()
    if artifact_sha256 != intended_sha256:
        # A DISTINCT REFUSAL, not a warning. The package is the artifact; if the file on disk
        # is not the one the manifest describes then the manifest is a false record, and
        # shipping it is worse than shipping nothing because it carries a hash that will
        # verify against the wrong bytes.
        raise SourceUnavailable(
            f"the written artifact does not match what was produced: wrote {len(written)} "
            f"bytes hashing {artifact_sha256}, produced content hashing {intended_sha256}. "
            f"The package has NOT been emitted."
        )

    audit = audit_line(package, disclosed_by="package_export")
    return {
        "output_uri": OUTPUT_URI["package_export"],
        "recipient_scope": scope,
        "lots_disclosed": list(lots),
        "lot_count": len(lots),
        "artifact_filename": dest.name,
        "artifact_bytes": dest.stat().st_size,
        # THE URI IS WHERE THE ARTIFACT CAN BE FETCHED, not where it happens to sit on this
        # filesystem. A card cannot open a path, and a path leaks the deployment's layout to a
        # recipient who has no use for it. Built from the engine's own public base so it is
        # correct wherever the engine is reached from.
        "artifact_uri": _artifact_uri(dest.name),
        # HASHED FROM THE FILE AS WRITTEN, re-read from disk. Distinct from `locator`, which
        # hashes the package BODY: this one answers "is the file you are about to download the
        # file this manifest describes", and nothing answered that before.
        "artifact_sha256": artifact_sha256,
        "dataset_filename": dataset_path.name if dataset_path else None,
        # BOTH HASHES AND THE COMMIT, in the answer itself. A caller that has the response has
        # everything needed to say which package this was, without opening it.
        "algorithm_sha": package["algorithm_sha"],
        "locator": package["locator"],
        "module_hashes": package["manifest"]["modules"],
        "duckdb_sha256": package["dataset"]["duckdb_sha256"] if dataset_path else None,
        "rows_sha256": package["dataset"]["rows_sha256"] if dataset_path else None,
        "as_of": package["as_of"],
        "audit": audit,
        "verified_lots": len(package["manifest"]["checks"]),
    }


#: The catalog, read ONCE and consumed twice — by the router's dispatch table and by the
#: registration. One table, so a verb cannot be servable and unregistered or the reverse.
VERBS = {
    "cost_lot_breakdown":     cost_lot_breakdown,
    "cost_unit_price_trend":  cost_unit_price_trend,
    "cost_rate_comparison":   cost_rate_comparison,
    "cost_labor_composition": cost_labor_composition,
    "cost_price_composition": cost_price_composition,
    "cost_rate_assumptions":  cost_rate_assumptions,
    "cost_category_breakdown": cost_category_breakdown,
    "cost_supplier_concentration": cost_supplier_concentration,
    "package_export":              package_export,
}
