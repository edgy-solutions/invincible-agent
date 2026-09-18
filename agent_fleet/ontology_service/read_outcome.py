"""WHICH STORE ANSWERED, AND WHETHER IT ANSWERED AT ALL — the read half of the marked-result rule.

Engine-o has three reads that return `[]` for two different worlds: *nothing matched* and *the
substrate could not be asked*. A caller holding `[]` cannot tell them apart, so an outage renders
as a confident zero — the same defect as the sixty-seven BM25-only days, in a different substrate.

**THE FALLBACK CHAIN IS WHY THIS IS A LIST OF ATTEMPTS AND NOT A BOOLEAN.** `execute_sparql` tries
Fuseki and then a local rdflib graph, and today a caller cannot tell which one answered. A result
served from a file shipped beside the code is not the same claim as one served from the cluster,
so the store that answered is carried in `mode` rather than being dropped.

PURE, AND NO DRIVER IMPORTS, so the decision is unit-testable where `main.py` needs a stub harness
— the same shape `substrate_posture` and `state_sparql` already use here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from iagent_mesh.results import MeshResult

#: Re-exported so a consumer importing the DECISION gets the TYPE from the same module object.
#: Two import paths for this file would otherwise mean two `SubstrateUnavailable` classes; the
#: same reasoning applies to anything callers name in an `except` or an `isinstance`.
__all__ = ["MeshResult", "StoreAttempt", "SubstrateUnavailable", "outcome", "rows_or_refuse"]


class SubstrateUnavailable(RuntimeError):
    """The store could not be asked, or was asked and failed mid-query.

    A PLAIN EXCEPTION, NOT AN `HTTPException`, because this module must not import a web framework
    to state a fact about a database. The route translates it; the decision does not know it is
    being made inside a web server.
    """


@dataclass(frozen=True)
class StoreAttempt:
    """One store, one try. `rows is None` means IT DID NOT ANSWER — which is not the same as `[]`.

    That distinction is the entire point of the dataclass: `rows=[]` is a store that ran the query
    and matched nothing, `rows=None` is a store that never got that far. Collapsing them here would
    rebuild the defect one layer up.
    """

    store: str
    declared: bool = True
    rows: Optional[Sequence[dict]] = None
    error: Optional[str] = None
    status: Optional[int] = None

    @property
    def answered(self) -> bool:
        return self.rows is not None


def outcome(attempts: Sequence[StoreAttempt], *, what: str = "read") -> MeshResult:
    """The first store that ANSWERED decides; if none did, the reasons are the result.

    Four outcomes, and the third and fourth are the ones that do not exist today:

        answered     rows, `mode` naming the store that produced them
        empty        the query RAN and matched nothing — a real answer about the data
        failed       a store was asked and failed (non-200, a raise mid-query)
        unreachable  nothing was even configured to ask

    **NOT-DECLARED AND FAILED ARE DIFFERENT, and the split is deliberate.** An undeclared store is a
    deployment that never intended to have one; a declared store that errored is an outage. They
    want opposite responses — one is a configuration answer, the other is a page — and `[]` gave
    both the same silence.
    """
    if not attempts:
        return MeshResult.unreachable(f"{what}: no store was attempted")

    for attempt in attempts:
        if attempt.answered:
            rows = [dict(r) for r in (attempt.rows or [])]
            return (
                MeshResult.answered(rows, mode=attempt.store)
                if rows
                else MeshResult.empty(mode=attempt.store)
            )

    declared = [a for a in attempts if a.declared]
    if not declared:
        return MeshResult.unreachable(
            f"{what}: no store declared ({', '.join(a.store for a in attempts)})"
        )

    # **EVERY ATTEMPT IS REPORTED, INCLUDING THE UNDECLARED ONES**, and this cost a test to find:
    # reporting only the declared stores meant an unset `JENA_QUERY_ENDPOINT` vanished behind the
    # fallback's own error, leaving an operator holding `rdflib: AttributeError` and no way to see
    # that the cluster was never configured. The undeclared store is the ACTIONABLE half — it is a
    # line in a chart, not an outage — so it stays in the sentence while staying out of the verdict.
    reasons = []
    for a in attempts:
        if not a.declared:
            reasons.append(f"{a.store}: not declared ({a.error})" if a.error
                           else f"{a.store}: not declared")
            continue
        detail = a.error or (f"HTTP {a.status}" if a.status is not None else "no rows and no error")
        reasons.append(f"{a.store}: {detail}")
    return MeshResult.failed(f"{what}: " + "; ".join(reasons), mode=declared[-1].store)


def rows_or_refuse(result: MeshResult, *, what: str = "read") -> list[dict]:
    """The bridge for the callers that still take `list[dict]` — REFUSING instead of returning `[]`.

    Expand/contract with the consumer as the clock: `outcome()` is the interface the callers should
    move to, and until they have, this keeps the fix in force rather than parking it behind an
    adoption none of them has done. **A correct result nobody reads changes nothing**, so the
    refusal lands on the existing path and the marked result is available to whoever migrates.

    `empty` PASSES THROUGH AS `[]`, because that is the case `[]` always meant correctly.
    """
    if result.outcome in ("answered", "empty"):
        return list(result.rows or [])
    # `detail` ALREADY CARRIES `what` when it came from `outcome()`, so re-prefixing here would
    # print it twice — and a doubled prefix is how a reader learns to stop reading the message.
    detail = result.detail or result.outcome
    raise SubstrateUnavailable(detail if detail.startswith(what) else f"{what}: {detail}")
