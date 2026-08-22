"""Gateway v0.2 registration saga.

Per ADR-0006 §Addendum (2026-06-13): bounded forward-retry on each
step, durable compensation on exhausted retries, atomic from the
substrate's perspective once the saga completes.

**This file ships the saga LOGIC. The Restate VirtualObject wiring is
a v0.2.1 follow-up.** The architectural decision in the ADR addendum
specifies Restate as the durability layer for two reasons: forward-
retry semantics and virtual-object serialization on (verb_iri,
_tool_urn). The first is replicable in plain Python (this module);
the second is currently a single-process limitation (the FastAPI
process handles registrations serially within itself, but two gateway
replicas could race). The conjunctive-read invariant — which is what
makes rollback safe — does not depend on Restate; it depends on the
substrate writes being structured so a partial state is unrouted by
the routing layer. The Restate integration tightens the worst-case
bounds (gateway crash mid-saga, multi-replica races) but does not
change the safety class.

Sequence per request:
  1. Contract D check (read-only; the existing function).
  2. Neo4j MERGE.
  3. Weaviate upsert.
  4. Read-back probe against BOTH stores.
  5. (Async, fire-and-forget) DataHub MCP emit for governance history.
  6. Return 200.

On any step #2-4 failing:
  - Restart that step with exponential backoff up to the saga budget
    (REGISTER_SAGA_BUDGET_S env, default 15s).
  - On exhausted retries, compensate: best-effort DELETE of whatever
    wrote, in reverse order. Compensation failures log loudly but
    don't fail-the-fail — orphan half-writes are benign under the
    conjunctive-read invariant (an orphan Neo4j edge without its
    Weaviate row is not in the LLM's constrained enum, so it doesn't
    route).
  - Return 5xx so the caller retries against a clean (or benignly-
    orphan'd) substrate.

The saga is sequenced and synchronous from the caller's perspective.
It is reentrant on the same `(verb_iri, _tool_urn)` identity: the
substrate writers use deterministic identities and idempotent upserts,
so a retried registration sees the same end state.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Optional

# Dual import: container layout has v2_substrate as a sibling module
# (no package context); dev uses the full package path.
try:
    from agent_fleet.mesh_registrar import v2_substrate as substrate
except ImportError:
    import v2_substrate as substrate  # type: ignore[no-redef]

logger = logging.getLogger(__name__)


REGISTER_SAGA_BUDGET_S = float(os.getenv("REGISTER_SAGA_BUDGET_S", "15"))
"""Total wall-clock budget for a single registration's forward-retry
phase. Past this, the saga compensates and returns 5xx. Tuned per the
cluster's observed transient-blip floor; raise via the helm value
``meshRegistrar.registerSagaBudgetSeconds`` if exhaustion becomes
non-rare without an underlying-blip root cause."""

REGISTER_SAGA_STEP_INITIAL_BACKOFF_S = 0.2
REGISTER_SAGA_STEP_MAX_BACKOFF_S = 2.0


# ---------------------------------------------------------------------------
# Saga step result + retry harness
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SagaOutcome:
    """What the saga did. Returned to the gateway HTTP handler."""

    status: str  # "registered" | "compensated" | "rejected_contract_d"
    http_code: int
    reason: str
    neo4j_written: bool
    weaviate_written: bool
    probe: dict | None
    forward_retry_attempts: int
    elapsed_s: float


def _now() -> float:
    return time.monotonic()


def _retry_step(
    *,
    name: str,
    step_fn: Callable[[], None],
    deadline: float,
) -> int:
    """Run ``step_fn`` with bounded forward-retry up to ``deadline``.

    Returns the attempt count on success. Raises the last exception on
    exhausted retries. ``step_fn`` MUST be idempotent: a retried run
    of an already-successful step is a no-op via the substrate's
    deterministic identity.
    """
    backoff = REGISTER_SAGA_STEP_INITIAL_BACKOFF_S
    attempts = 0
    last_exc: Exception | None = None
    while _now() < deadline:
        attempts += 1
        try:
            step_fn()
            return attempts
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            remaining = deadline - _now()
            if remaining <= 0:
                break
            sleep_for = min(backoff, max(remaining * 0.5, 0.05))
            logger.warning(
                "saga step %r attempt %d failed (%s: %s); retrying in %.2fs "
                "(remaining budget %.2fs)",
                name, attempts, type(exc).__name__, exc, sleep_for, remaining,
            )
            time.sleep(sleep_for)
            backoff = min(backoff * 2, REGISTER_SAGA_STEP_MAX_BACKOFF_S)
    # Exhausted
    assert last_exc is not None
    logger.error(
        "saga step %r EXHAUSTED retries after %d attempts: %s: %s",
        name, attempts, type(last_exc).__name__, last_exc,
    )
    raise last_exc


# ---------------------------------------------------------------------------
# The saga itself
# ---------------------------------------------------------------------------


def run_registration_saga(
    *,
    driver: Any,
    weaviate_client: Any,
    verb_iri: str,
    input_uri: str,
    output_uri: str,
    tool_urn: str,
    rel_props: dict,
    description: str,
    endpoint_url: str,
    owner_persona: str,
    domains: list[str],
    cost_class: str,
    requires_human_approval: bool,
    synonyms: list[str],
    anti_synonyms: list[str],
    # SECOND SPECIES PAYLOAD, defaulted so every existing caller is unchanged.
    # A presentation row needs more than the triple: whose menu it is on, what
    # archetype to name, which fields that archetype needs, and whether it
    # recomputes. Without them the row carries the edge and not the MENU.
    tool_kind: str = "Engine",
    frontend_id: str = "",
    archetype: str = "",
    expected_fields: list[str] | None = None,
    recomputes: bool | None = None,
    budget_s: float | None = None,
) -> SagaOutcome:
    """Execute the v0.2 atomic registration saga end-to-end.

    Caller (the FastAPI ``/v1/register`` handler) is responsible for:
      - Contract D check BEFORE invoking this (already implemented at
        ``mesh_registrar/main.py``).
      - Building ``rel_props`` from the manifest's customProperties.
      - Awaiting the SagaOutcome and translating it into HTTP.
      - Enqueuing the DataHub MCP emit out-of-band (governance history
        is decorrelated from the substrate outcome per the priors).
    """
    budget = budget_s if budget_s is not None else REGISTER_SAGA_BUDGET_S
    started = _now()
    deadline = started + budget

    neo4j_written = False
    weaviate_written = False
    forward_retry_attempts = 0
    probe_result: dict | None = None

    # Step: Neo4j MERGE -----------------------------------------------------
    try:
        attempts = _retry_step(
            name="merge_neo4j_predicate_edge",
            step_fn=lambda: substrate.merge_neo4j_predicate_edge(
                driver=driver,
                verb_iri=verb_iri,
                input_uri=input_uri,
                output_uri=output_uri,
                tool_urn=tool_urn,
                rel_props=rel_props,
            ),
            deadline=deadline,
        )
        forward_retry_attempts += attempts
        neo4j_written = True
    except Exception as exc:  # noqa: BLE001
        # Nothing wrote (or N partially wrote but the retry harness
        # treated it as failure — apoc.merge.relationship is atomic per
        # transaction, so this is unambiguous). No compensation needed.
        return SagaOutcome(
            status="compensated",
            http_code=503,
            reason=(
                f"Neo4j merge failed: {type(exc).__name__}: {exc}. "
                f"No substrate write landed; caller can retry."
            ),
            neo4j_written=False,
            weaviate_written=False,
            probe=None,
            forward_retry_attempts=forward_retry_attempts,
            elapsed_s=_now() - started,
        )

    # Step: Weaviate upsert -------------------------------------------------
    try:
        attempts = _retry_step(
            name="upsert_weaviate_predicate_row",
            step_fn=lambda: substrate.upsert_weaviate_predicate_row(
                weaviate_client=weaviate_client,
                verb_iri=verb_iri,
                input_uri=input_uri,
                output_uri=output_uri,
                description=description,
                endpoint_url=endpoint_url,
                owner_persona=owner_persona,
                domains=domains,
                cost_class=cost_class,
                requires_human_approval=requires_human_approval,
                synonyms=synonyms,
                anti_synonyms=anti_synonyms,
                tool_urn=tool_urn,
                tool_kind=tool_kind,
                frontend_id=frontend_id,
                archetype=archetype,
                expected_fields=expected_fields,
                recomputes=recomputes,
            ),
            deadline=deadline,
        )
        forward_retry_attempts += attempts
        weaviate_written = True
    except Exception as exc:  # noqa: BLE001
        # Compensation: DELETE the Neo4j edge we just wrote so the
        # substrate returns to its empty state.
        _compensate_neo4j_best_effort(
            driver=driver,
            verb_iri=verb_iri,
            input_uri=input_uri,
            output_uri=output_uri,
            tool_urn=tool_urn,
        )
        return SagaOutcome(
            status="compensated",
            http_code=503,
            reason=(
                f"Weaviate upsert failed after Neo4j merge succeeded: "
                f"{type(exc).__name__}: {exc}. Neo4j edge compensated; "
                f"caller can retry against clean substrate."
            ),
            neo4j_written=False,  # compensation attempted; orphan is benign under invariant
            weaviate_written=False,
            probe=None,
            forward_retry_attempts=forward_retry_attempts,
            elapsed_s=_now() - started,
        )

    # Step: Compensate-on-rescope sweep -------------------------------------
    # Runs after the upsert succeeded — surgically deletes the engine's
    # OWN rename-stale rows (same tool_urn, same verb_iri, different
    # canonical input_uri). Cross-engine isolation is structural: the
    # tool_urn match prevents touching any other engine's records.
    # Failure here MUST NOT roll back the registration — the new row
    # is already in. Logged at WARNING; the dedup guard catches the
    # residue. See tests/test_compensate_on_rescope_sweep.py for the
    # surgical-scope assertions against the live contamination shape.
    try:
        deleted = substrate.sweep_stale_weaviate_predicate_rows(
            weaviate_client=weaviate_client,
            verb_iri=verb_iri,
            current_input_uri=input_uri,
            tool_urn=tool_urn,
        )
        if deleted:
            print(
                f"[saga] sweep_stale_weaviate_predicate_rows: "
                f"tool_urn={tool_urn} verb_iri={verb_iri} "
                f"deleted {len(deleted)} stale row(s): "
                f"{[d['input_uri'] for d in deleted]}"
            )
    except Exception as sweep_exc:  # noqa: BLE001
        print(
            f"[saga] WARNING sweep_stale_weaviate_predicate_rows failed "
            f"(non-fatal — registration succeeded; dedup guard will "
            f"surface residual duplicates): "
            f"tool_urn={tool_urn} verb_iri={verb_iri} "
            f"err={type(sweep_exc).__name__}: {sweep_exc}"
        )

    # Step: Read-back probe -------------------------------------------------
    try:
        attempts = _retry_step(
            name="probe_both_stores",
            step_fn=lambda: _capture_probe(
                box=lambda r: setattr(_probe_box, "value", r),
                fn=lambda: substrate.probe_both_stores(
                    driver=driver,
                    weaviate_client=weaviate_client,
                    verb_iri=verb_iri,
                    input_uri=input_uri,
                    output_uri=output_uri,
                    tool_urn=tool_urn,
                    frontend_id=frontend_id,
                    archetype=archetype,
                ),
            ),
            deadline=deadline,
        )
        forward_retry_attempts += attempts
        probe_result = _probe_box.value
    except Exception as exc:  # noqa: BLE001
        # Compensation: BOTH writes claimed success but the probe
        # disagrees. Roll both back.
        _compensate_weaviate_best_effort(
            weaviate_client=weaviate_client,
            verb_iri=verb_iri,
            input_uri=input_uri,
            frontend_id=frontend_id,
            archetype=archetype,
        )
        _compensate_neo4j_best_effort(
            driver=driver,
            verb_iri=verb_iri,
            input_uri=input_uri,
            output_uri=output_uri,
            tool_urn=tool_urn,
        )
        return SagaOutcome(
            status="compensated",
            http_code=503,
            reason=(
                f"Read-back probe failed after both writes claimed "
                f"success: {type(exc).__name__}: {exc}. Both stores "
                f"compensated; caller can retry."
            ),
            neo4j_written=False,
            weaviate_written=False,
            probe=None,
            forward_retry_attempts=forward_retry_attempts,
            elapsed_s=_now() - started,
        )

    # ── COMMIT POINT. The probe has confirmed BOTH stores; only now is this
    # registration COMPLETE, and only now may a single-store reader trust the
    # row. Stamped as the saga's final act so the field can never mean "a write
    # landed" — it means "this finished".
    #
    # Best-effort by design: the registration genuinely succeeded, and failing
    # the whole thing because the marker did not stick would compensate a good
    # write for a bookkeeping miss. An unmarked row is treated as incomplete by
    # readers, so the failure mode is a capability that is INVISIBLE until the
    # next registration — degraded and self-healing, never wrong.
    try:
        _marked = substrate.mark_registration_complete(
            weaviate_client=weaviate_client,
            verb_iri=verb_iri,
            input_uri=input_uri,
            frontend_id=frontend_id,
            archetype=archetype,
        )
        if not _marked:
            logger.warning(
                "registration completed but the row could not be marked complete "
                "(verb_iri=%r input_uri=%r frontend_id=%r): readers will treat it "
                "as incomplete until the next registration.",
                verb_iri, input_uri, frontend_id,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "registration completed but marking failed (%s: %s); the capability "
            "stays invisible to readers until re-registered.",
            type(exc).__name__, exc,
        )

    return SagaOutcome(
        status="registered",
        http_code=200,
        reason="ok",
        neo4j_written=True,
        weaviate_written=True,
        probe=probe_result,
        forward_retry_attempts=forward_retry_attempts,
        elapsed_s=_now() - started,
    )


# ---------------------------------------------------------------------------
# Best-effort compensation — orphan half-writes are benign under the
# conjunctive-read invariant, so compensation failures log loudly but
# don't fail-the-fail.
# ---------------------------------------------------------------------------


def _compensate_neo4j_best_effort(
    *,
    driver: Any,
    verb_iri: str,
    input_uri: str,
    output_uri: str,
    tool_urn: str,
) -> None:
    try:
        deleted = substrate.compensate_neo4j_predicate_edge(
            driver=driver,
            verb_iri=verb_iri,
            input_uri=input_uri,
            output_uri=output_uri,
            tool_urn=tool_urn,
        )
        logger.info(
            "saga compensation: DELETE Neo4j edge for verb_iri=%r tool_urn=%r "
            "(deleted=%d)",
            verb_iri, tool_urn, deleted,
        )
    except Exception as exc:  # noqa: BLE001
        # ADR-0006 §Addendum: orphan half-writes are benign under the
        # conjunctive-read invariant. Log loudly and continue — the
        # next reconciliation cycle (or a future re-registration) will
        # converge the substrate.
        logger.error(
            "saga compensation FAILED to DELETE Neo4j edge for "
            "verb_iri=%r tool_urn=%r: %s: %s. Orphan is benign under "
            "the conjunctive-read invariant (unrouted because Weaviate "
            "has no row); reconciliation will clean it up.",
            verb_iri, tool_urn, type(exc).__name__, exc,
        )


def _compensate_weaviate_best_effort(
    *, weaviate_client: Any, verb_iri: str, input_uri: str,
    frontend_id: str = "", archetype: str = "",
) -> None:
    try:
        deleted = substrate.compensate_weaviate_predicate_row(
            weaviate_client=weaviate_client,
            verb_iri=verb_iri,
            input_uri=input_uri,
            frontend_id=frontend_id,
            archetype=archetype,
        )
        logger.info(
            "saga compensation: DELETE Weaviate Predicate row for "
            "verb_iri=%r input_uri=%r (deleted=%s)",
            verb_iri, input_uri, deleted,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "saga compensation FAILED to DELETE Weaviate Predicate row "
            "for verb_iri=%r input_uri=%r: %s: %s. Orphan is benign "
            "under the conjunctive-read invariant (unrouted because "
            "Neo4j has no compat edge); reconciliation will clean it up.",
            verb_iri, input_uri, type(exc).__name__, exc,
        )


# ---------------------------------------------------------------------------
# Probe-capture box — gives _retry_step a way to return a value
# ---------------------------------------------------------------------------


class _ProbeBox:
    value: dict | None = None


_probe_box = _ProbeBox()


def _capture_probe(*, box: Callable[[dict], None], fn: Callable[[], dict]) -> None:
    """Run fn, capture its return into box. Wrapper to fit ``_retry_step``'s
    signature (which takes a void callable)."""
    result = fn()
    box(result)
