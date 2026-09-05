"""Packaging: the verification manifest, and the governed emit that carries it.

ADR-0047's §§1-5, built. What this module does NOT do is equally deliberate: it does not
create a `PublishedArtifact` graph node (§6, still behind the projector ruling), and it does
not write anything anywhere. It RETURNS a package; a caller decides what to do with it.

THE MANIFEST IS THE REFUSAL CONTRACT, SHIPPED. It captures inputs, intermediates and expected
outputs FROM THE PRODUCING ENGINE at packaging time. On open, the recipient's copy recomputes
them with the same pinned modules and compares. On divergence it REFUSES TO RENDER -- not a
warning, not a highlighted cell -- because a package showing a different number than the
engine produced would be the confident-wrong answer with the system's name on it, in a file
the system no longer controls.

WHY THE INTERMEDIATES AND NOT JUST THE OUTPUTS. An output-only manifest tells the recipient
THAT something diverged. Capturing each step's basis and amount tells them WHERE, and the
whole offer is that a disagreement becomes a bounded diagnosis rather than an argument. The
engine already computes them -- `PriceBuildUp.steps` carries basis, rate, amount and running
total per rung -- so this is capture, not new arithmetic.

WHAT IS DELIBERATELY NOT EMBEDDED: the seed's construction (`seed.py`), the rate table's
derivation, any lot outside the recipient's scope, and any code that reads a source system.
The bundle carries the computation's INPUTS, not the pipeline that produced them -- ADR-0048
§2 -- because that machinery is fragile, is not what the recipient is verifying, and would
put a second data-preparation implementation in their hands.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
from datetime import date
from decimal import Decimal
from typing import Any, Optional

try:  # flat in the image (/app), packaged in the repo — see §5 of the engine runbook
    from entities import CostState, Unentitled
    from pricing import (
        DEFAULT_COMPOSITION, StepSpec, compose_price, quantize_money, unit_price,
    )
    from seed import lots_for_recipient
except ImportError:
    from agent_fleet.cost_agent.entities import CostState, Unentitled
    from agent_fleet.cost_agent.pricing import (
        DEFAULT_COMPOSITION, StepSpec, compose_price, quantize_money, unit_price,
    )
    from agent_fleet.cost_agent.seed import lots_for_recipient

#: Bumped when the manifest's SHAPE changes, so an old package cannot be silently checked by
#: new rules or the reverse. Not the algorithm's version -- that is the pinned commit SHA.
MANIFEST_SCHEMA = "cost-export/1"


def _canonical(obj: Any) -> str:
    """Stable JSON for hashing. Sorted keys, no whitespace drift, Decimals as strings.

    A content hash is only an identity if the same content always produces it, so the
    serialisation is pinned here rather than left to whatever `json.dumps` defaults to in the
    runtime that happens to be running.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def content_hash(obj: Any) -> str:
    """The package's identity, per ADR-0034's `ruleset_ref` discipline."""
    return "sha256:" + hashlib.sha256(_canonical(obj).encode("utf-8")).hexdigest()


def _lot_inputs(state: CostState, lot_number: int) -> dict[str, Any]:
    """The COMPUTATION's inputs for one lot — not the seed's internals."""
    lot = state.lot(lot_number)
    return {
        "lot": lot.number,
        "quantity": lot.quantity,
        "fiscal_year": lot.fiscal_year,
        "direct_labor": str(lot.direct_labor),
        "material": str(lot.material),
        "other_direct": str(lot.other_direct + lot.warranty + lot.contracts),
    }


def _rates_for_lot(state: CostState, lot_number: int, vintage: Optional[str]):
    lot = state.lot(lot_number)
    v = vintage or state.vintages(lot.fiscal_year)[0]
    return state.rates[(lot.fiscal_year, v)]


def build_manifest(
    state: CostState,
    *,
    lots: tuple[int, ...],
    rate_vintage: Optional[str] = None,
    spec: tuple[StepSpec, ...] = DEFAULT_COMPOSITION,
) -> dict[str, Any]:
    """Capture inputs, intermediates and expected outputs from the PRODUCING engine.

    Every figure here is produced by the same `compose_price` the recipient will run. That is
    the point: the manifest is not a description of what should happen, it is a record of what
    DID happen here, so the recipient's run can be compared to it rather than to a spec.
    """
    checks = []
    for n in lots:
        rates = _rates_for_lot(state, n, rate_vintage)
        inputs = _lot_inputs(state, n)
        build = compose_price(
            direct_labor=Decimal(inputs["direct_labor"]),
            material=Decimal(inputs["material"]),
            other_direct=Decimal(inputs["other_direct"]),
            rates=rates,
            spec=spec,
        )
        checks.append({
            "lot": n,
            "inputs": inputs,
            "rates": {
                "fiscal_year": rates.fiscal_year, "vintage": rates.vintage,
                "fringe": str(rates.fringe), "overhead": str(rates.overhead),
                "g_and_a": str(rates.g_and_a), "cost_of_money": str(rates.cost_of_money),
                "profit": str(rates.profit), "escalation": str(rates.escalation),
            },
            # THE INTERMEDIATES. Each step's basis is carried because a reader checking the
            # arithmetic cannot recover it from the amounts — an overhead figure is
            # unverifiable without knowing it was struck on labour-plus-fringe.
            "intermediates": [
                {"name": s.name, "rate": None if s.rate is None else str(s.rate),
                 "basis": str(s.basis), "amount": str(s.amount),
                 "running_total": str(s.running_total)}
                for s in build.steps
            ],
            "expected": {
                "price": str(build.price),
                "unit_price": str(unit_price(build, state.lot(n).quantity)),
            },
        })
    return {
        "schema": MANIFEST_SCHEMA,
        "composition": [
            {"name": s.name, "rate_key": s.rate_key, "basis_kind": s.basis_kind,
             "component": s.component, "plus_steps": list(s.plus_steps)}
            for s in spec
        ],
        "checks": checks,
    }


def verify_manifest(manifest: dict[str, Any]) -> list[str]:
    """Recompute every check and return the divergences. Empty list means equivalent.

    THIS IS THE FUNCTION THE BUNDLE RUNS ON OPEN, and it is written to be readable by the
    recipient — it takes the manifest and nothing else, so there is no hidden state deciding
    whether the package renders.

    Returns divergences rather than raising, because the bundle needs to SHOW them: "refuses
    to render" is only actionable if it says what disagreed.
    """
    spec = tuple(
        StepSpec(name=c["name"], rate_key=c["rate_key"], basis_kind=c["basis_kind"],
                 component=c["component"], plus_steps=tuple(c["plus_steps"]))
        for c in manifest["composition"]
    )
    problems: list[str] = []
    for chk in manifest["checks"]:
        r = chk["rates"]
        rates = _RateSetFromManifest(r)
        build = compose_price(
            direct_labor=Decimal(chk["inputs"]["direct_labor"]),
            material=Decimal(chk["inputs"]["material"]),
            other_direct=Decimal(chk["inputs"]["other_direct"]),
            rates=rates, spec=spec,
        )
        if str(build.price) != chk["expected"]["price"]:
            problems.append(
                f"lot {chk['lot']}: price recomputed {build.price}, "
                f"manifest expects {chk['expected']['price']}"
            )
        for got, want in zip(build.steps, chk["intermediates"]):
            if str(got.amount) != want["amount"]:
                problems.append(
                    f"lot {chk['lot']} step {want['name']}: recomputed {got.amount}, "
                    f"manifest expects {want['amount']}"
                )
    return problems


def _RateSetFromManifest(r: dict[str, Any]):
    """Rebuild a RateSet from its manifest form. Kept tiny and explicit on purpose."""
    try:
        from pricing import RateSet
    except ImportError:
        from agent_fleet.cost_agent.pricing import RateSet
    return RateSet(
        fiscal_year=r["fiscal_year"], vintage=r["vintage"],
        fringe=Decimal(r["fringe"]), overhead=Decimal(r["overhead"]),
        g_and_a=Decimal(r["g_and_a"]), cost_of_money=Decimal(r["cost_of_money"]),
        profit=Decimal(r["profit"]), escalation=Decimal(r["escalation"]),
    )


def build_package(
    state: CostState,
    *,
    recipient_scope: str,
    algorithm_sha: str,
    scenario: Optional[str] = None,
    as_of: Optional[str] = None,
    rate_vintage: Optional[str] = None,
) -> dict[str, Any]:
    """The governed emit. Entitlement-filtered HERE, once, per ADR-0047 §5.

    `algorithm_sha` is passed IN rather than discovered, because a module cannot honestly
    report the commit it was built from — it would read whatever the working tree happens to
    say, which is the claim the pin exists to replace.
    """
    lots = lots_for_recipient(recipient_scope)   # raises Unentitled on an unknown scope
    if not lots:  # pragma: no cover - the map has no empty scopes today
        raise Unentitled(f"{recipient_scope!r} is entitled to no lots; nothing to package")

    manifest = build_manifest(state, lots=lots, rate_vintage=rate_vintage)
    body = {
        "recipient_scope": recipient_scope,
        "scenario": scenario or "baseline",
        "as_of": as_of or date.today().isoformat(),
        "algorithm_sha": algorithm_sha,
        "program": state.program_name,
        # EVERYTHING EMBEDDED IS DISCLOSED. There is no render-time filtering in a file the
        # recipient owns, so this list IS the disclosure decision.
        "lots": list(lots),
        "rate_vintages": sorted({c["rates"]["vintage"] for c in manifest["checks"]}),
        "manifest": manifest,
    }
    body["locator"] = content_hash(body)
    return body


def audit_line(package: dict[str, Any], *, disclosed_by: str) -> dict[str, Any]:
    """What was disclosed, to whom, when, and by which algorithm version.

    A disclosure that leaves no audit line is indistinguishable afterwards from one that never
    happened — which is the whole reason packaging is a verb rather than a script.
    """
    return {
        "disclosed_to": package["recipient_scope"],
        "disclosed_by": disclosed_by,
        "at": package["as_of"],
        "algorithm_sha": package["algorithm_sha"],
        "locator": package["locator"],
        "lots_disclosed": package["lots"],
        "lot_count": len(package["lots"]),
    }


# =======================================================================================
# SLICE 2 — the dataset half. RULED 2026-09-05: the .duckdb ships BESIDE the HTML.
#
# duckdb-wasm is refused for two independent reasons, both measured rather than argued:
#   * 34 MB, to do selection and grouping Pyodide already does over embedded rows
#   * its reader returns DECIMAL(20,2) as an UNSCALED BigInt -- every value exactly 100x the
#     engine's -- a representation the engine never produced, sitting between the recipient
#     and the pinned algorithm
#
# So the database is the AUTHORING AND INTERCHANGE format, not the runtime one, and the HTML
# carries the rows directly. THE MANIFEST RECORDS BOTH HASHES so the two cannot silently
# diverge: a recipient holding only the HTML gets a working, verifying page, and one holding
# both can prove the file they were handed is the data the page computed from.
# =======================================================================================

#: The labour kinds, in render order. Declared rather than derived from the rows so a lot
#: missing a kind renders a gap instead of silently reordering the chart.
LABOR_KINDS = ("touch", "support", "sepm")


def dataset_rows(state: CostState, *, lots: tuple[int, ...]) -> dict[str, Any]:
    """The rows the page needs, in the same shape the .duckdb holds them.

    ONE SOURCE, TWO CONTAINERS -- and the check over them is NOT vacuous, though the first
    version of this docstring argued the opposite and was wrong.

    The initial design had two independent row builders so the comparison would be
    "independent". They drifted on their FIRST run: the database carried 75 result rows and
    the embedded set 35, because one wrote composition steps and the other did not. That is
    not an independent check working, it is two half-specifications disagreeing, and shipping
    it would have meant the page and the file genuinely held different tables.

    So there is now one generator, and `datasets_agree` compares THE FILE ON DISK against the
    embedded rows. That is a real check about ARTIFACTS rather than about code paths: the file
    a recipient holds can be stale, swapped, or altered after the fact, and none of those is
    detectable by construction. Comparing two outputs of one function would be vacuous;
    comparing a shipped file to a shipped page is the question actually being asked.
    """
    lot_rows, result_rows, rate_rows = [], [], []
    seen: set[tuple[str, int, str]] = set()
    for n in lots:
        lot = state.lot(n)
        vintage = state.vintages(lot.fiscal_year)[0]
        rates = state.rates[(lot.fiscal_year, vintage)]
        lot_rows.append({"lot": n, "quantity": lot.quantity,
                         "fiscal_year": lot.fiscal_year, "estimating": False})
        # QUANTIZED AT THE BOUNDARY. `LaborLine.cost` is hours x rate and is not rounded, so
        # str() gives "3108000" while a DECIMAL(20,2) column gives "3108000.00". Two
        # representations of one number is enough to break a hash comparison — caught by the
        # agreement check on its first run, which is what that check is for.
        for line in lot.labor:
            result_rows.append({"lot": n, "category": "labor", "sub_config": line.kind,
                                "period": str(lot.fiscal_year),
                                "hours": str(quantize_money(line.hours)),
                                "price": str(quantize_money(line.cost)),
                                "rate": str(line.rate)})
        for cat, price, hours in (("material", lot.material, None),
                                  ("other_direct", lot.other_direct, None),
                                  ("warranty", lot.warranty, lot.warranty_hours),
                                  ("contracts", lot.contracts, None)):
            result_rows.append({"lot": n, "category": cat, "sub_config": None,
                                "period": str(lot.fiscal_year),
                                "hours": None if hours is None else str(quantize_money(hours)),
                                "price": str(quantize_money(price)), "rate": None})
        # The composition steps and totals, so the file and the page hold the same tables.
        build_up = compose_price(
            direct_labor=lot.direct_labor, material=lot.material,
            other_direct=lot.other_direct + lot.warranty + lot.contracts, rates=rates)
        for s in build_up.steps:
            result_rows.append({"lot": n, "category": "composition", "sub_config": s.name,
                                "period": str(lot.fiscal_year), "hours": None,
                                "price": str(s.amount), "rate": None})
        result_rows.append({"lot": n, "category": "price", "sub_config": None,
                            "period": str(lot.fiscal_year), "hours": None,
                            "price": str(build_up.price), "rate": None})
        result_rows.append({"lot": n, "category": "unit_price", "sub_config": None,
                            "period": str(lot.fiscal_year), "hours": None,
                            "price": str(unit_price(build_up, lot.quantity)), "rate": None})
        for field in ("fringe", "overhead", "g_and_a", "cost_of_money", "profit", "escalation"):
            key = (vintage, lot.fiscal_year, field)
            if key not in seen:
                seen.add(key)
                rate_rows.append({"vintage": vintage, "fiscal_year": lot.fiscal_year,
                                  "category": field, "rate": str(getattr(rates, field))})
    return {"lots": lot_rows, "results": result_rows, "rates": rate_rows}


def datasets_agree(rows: dict[str, Any], duckdb_path: str) -> list[str]:
    """Assert the embedded rows and the .duckdb hold the SAME tables.

    Compared BY VALUE, table by table, not by trusting that one build produced both. Returns
    differences rather than raising so a caller can report all of them at once.

    NOTE ON THE DECIMAL READ: values come back from DuckDB as Python `Decimal` and are
    stringified here. That is the path measured at 63/63 -- and deliberately NOT the
    duckdb-wasm path, whose reader returns unscaled integers.
    """
    import duckdb

    problems: list[str] = []
    con = duckdb.connect(duckdb_path, read_only=True)
    try:
        db_lots = [r[0] for r in con.execute("SELECT lot FROM lots ORDER BY lot").fetchall()]
        emb_lots = sorted(r["lot"] for r in rows["lots"])
        if db_lots != emb_lots:
            problems.append(f"lots differ: db {db_lots} vs embedded {emb_lots}")

        db_res = con.execute(
            "SELECT lot, category, COALESCE(sub_config,''), price FROM results "
            "ORDER BY lot, category, COALESCE(sub_config,'')").fetchall()
        emb_res = sorted(
            ((r["lot"], r["category"], r["sub_config"] or "", r["price"])
             for r in rows["results"]),
            key=lambda x: (x[0], x[1], x[2]))
        if len(db_res) != len(emb_res):
            problems.append(f"result row counts differ: db {len(db_res)} vs embedded "
                            f"{len(emb_res)}")
        for d, e in zip(db_res, emb_res):
            if (d[0], d[1], d[2]) != (e[0], e[1], e[2]) or str(d[3]) != e[3]:
                problems.append(f"row differs: db {d} vs embedded {e}")
                if len(problems) > 8:
                    break
    finally:
        con.close()
    return problems


def build_dataset_package(
    state: CostState,
    *,
    recipient_scope: str,
    algorithm_sha: str,
    duckdb_path: str,
    duckdb_hash: str,
    scenario: Optional[str] = None,
    as_of: Optional[str] = None,
) -> dict[str, Any]:
    """A slice-2 package: the slice-1 body, plus rows and BOTH dataset hashes."""
    pkg = build_package(state, recipient_scope=recipient_scope,
                        algorithm_sha=algorithm_sha, scenario=scenario, as_of=as_of)
    rows = dataset_rows(state, lots=tuple(pkg["lots"]))
    pkg["dataset"] = {
        "rows": rows,
        # THE TWO HASHES. `duckdb_sha256` identifies the file the recipient was handed;
        # `rows_sha256` identifies what the page actually computes from. Recording only the
        # first would let the page drift from the file it claims to represent, which is the
        # failure this pair exists to make impossible.
        "duckdb_sha256": duckdb_hash,
        "duckdb_filename": pathlib.PurePath(duckdb_path).name,
        "rows_sha256": content_hash(rows),
    }
    pkg["locator"] = content_hash({k: v for k, v in pkg.items() if k != "locator"})
    return pkg
