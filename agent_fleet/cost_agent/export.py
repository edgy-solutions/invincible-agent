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
from datetime import date
from decimal import Decimal
from typing import Any, Optional

try:  # flat in the image (/app), packaged in the repo — see §5 of the engine runbook
    from entities import CostState, Unentitled
    from pricing import DEFAULT_COMPOSITION, StepSpec, compose_price, unit_price
    from seed import lots_for_recipient
except ImportError:
    from agent_fleet.cost_agent.entities import CostState, Unentitled
    from agent_fleet.cost_agent.pricing import (
        DEFAULT_COMPOSITION, StepSpec, compose_price, unit_price,
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
