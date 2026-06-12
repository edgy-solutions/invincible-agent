"""Gateway v0.2.1 — Restate VirtualObject wrapping the saga logic.

Per ADR-0006 §Addendum and the architect's A1 (2026-06-12), the v0.2.1
follow-up wraps `v2_saga.run_registration_saga` in a Restate
VirtualObject keyed on the registration identity. The saga logic
itself is unchanged; this module is the durability + serialization
wire that the saga has always assumed it would eventually grow.

Why a VirtualObject:
  - **Per-key serialization.** Restate guarantees at most one active
    handler invocation per VirtualObject key. With the key set to
    `(verb_iri || ":" || tool_urn)`, two concurrent registrations
    against the same identity are serialized — the second waits for
    the first to complete. This is the multi-replica race the saga's
    docstring flags as the only gap the in-process synchronous path
    can't close.
  - **Crash recovery.** Each `ctx.run(...)` step is journaled. If the
    gateway pod restarts mid-saga, Restate replays from the last
    successful step rather than from scratch. The substrate writers
    are idempotent on the `(verb_iri, _tool_urn)` identity (the
    a44b9fb match-key), so replay is safe by construction.

Safety class — **unchanged** from the in-process saga. The conjunctive-
read invariant (only verbs in BOTH Neo4j AND Weaviate enter the LLM's
constrained enum) is what makes rollback safe; that property does not
depend on Restate. The VirtualObject tightens worst-case bounds but
does not change the failure model.

Key shape (`f"{verb_iri}::{tool_urn}"`):
  - The `::` separator is fine because neither side contains it in
    practice — verb IRIs use single-colon prefix form
    (`mesh:foo`, `http://invincible-agent/...`) and tool URNs use
    DataHub's `urn:li:mlModel:(...)` form with parentheses.
  - This is the pair Contract D names as "registration identity"
    (ADR-0019 §5 addendum) and what the doc-tools a44b9fb match-key
    uses on the Neo4j side.

Caller integration:
  - Today: `mesh_registrar/main.py`'s `/v1/register` calls
    `v2_saga.run_registration_saga` directly (the in-process path).
    Single-replica gateway; no race window.
  - Tomorrow: switch `/v1/register` to invoke this VirtualObject
    through Restate ingress. The in-process path stays as a fallback
    for environments without Restate (dev, isolated test clusters).
    No data-shape changes — the VirtualObject's request/response is
    the same `(manifest_kwargs, SagaOutcome)` shape.

This file is import-protected against environments where `restate-sdk`
isn't installed (CI, isolated test clusters). The VirtualObject is
only defined when the SDK is available; the rest of the module's
helpers (`_make_registration_key`) are SDK-independent and used by
unit tests that pin the wire shape.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Wire shape — pinned so tests can assert the contract without importing
# restate-sdk.
# ---------------------------------------------------------------------------

SAGA_OBJECT_NAME = "RegistrationSaga"
SAGA_HANDLER_NAME = "register"
SAGA_STEP_NAME = "run_registration_saga"


def _make_registration_key(verb_iri: str, tool_urn: str) -> str:
    """The VirtualObject key for a registration.

    Identity is the `(verb_iri, _tool_urn)` pair per ADR-0019 §5
    addendum (the dedup contract clause). The `::` separator is a
    parse-friendly choice: neither field contains it in practice.

    This function is the wire-shape contract; if you change it, the
    Neo4j a44b9fb match-key + the saga substrate writers + any test
    that pins identity must change in lockstep.
    """
    if not verb_iri or not tool_urn:
        raise ValueError(
            f"registration key requires both verb_iri and tool_urn; "
            f"got verb_iri={verb_iri!r}, tool_urn={tool_urn!r}"
        )
    return f"{verb_iri}::{tool_urn}"


# ---------------------------------------------------------------------------
# VirtualObject definition — gated on restate-sdk availability so the
# module imports cleanly in environments without the SDK (CI, dev).
# ---------------------------------------------------------------------------

try:
    from restate import VirtualObject, ObjectContext
    _RESTATE_AVAILABLE = True
except ImportError:  # pragma: no cover — exercised in restate-less envs
    VirtualObject = None  # type: ignore[assignment,misc]
    ObjectContext = None  # type: ignore[assignment,misc]
    _RESTATE_AVAILABLE = False
    logger.info(
        "restate-sdk not installed; v2_restate.registration_saga_object "
        "will not be defined. The in-process saga path "
        "(v2_saga.run_registration_saga) remains the active write path."
    )


if _RESTATE_AVAILABLE:
    # Dual import: package path for dev, bare module for container.
    try:
        from agent_fleet.mesh_registrar import v2_saga
    except ImportError:
        import v2_saga  # type: ignore[no-redef]

    registration_saga_object = VirtualObject(SAGA_OBJECT_NAME)
    """The VirtualObject that wraps `v2_saga.run_registration_saga`.

    Keyed on `_make_registration_key(verb_iri, tool_urn)`. One active
    handler per key per Restate cluster; replays from the last
    journaled step on crash.
    """

    @registration_saga_object.handler(name=SAGA_HANDLER_NAME)
    async def register(ctx: ObjectContext, request: dict) -> dict:
        """Run the registration saga under Restate durability.

        Per-key serialization is provided by the VirtualObject contract
        — Restate guarantees this handler runs at most once at a time
        per key. The `ctx.run` boundary makes the saga's outcome
        idempotent under replay: a crashed gateway replays from the
        journal rather than re-executing the substrate writers from
        scratch (the substrate writers themselves are idempotent on
        the `(verb_iri, _tool_urn)` identity, so even un-journaled
        replays would converge — the journal is the *performance*
        guarantee, not the correctness one).

        Request shape mirrors the kwargs accepted by
        `v2_saga.run_registration_saga` minus the live driver +
        weaviate_client objects (those are not serializable through
        Restate and are resolved inside this handler).
        """
        # Verify the key matches the request's identity. Defense in
        # depth: an HTTP caller that builds the key wrong (e.g. uses
        # only the verb_iri) would otherwise quietly serialize against
        # the wrong identity.
        expected_key = _make_registration_key(
            verb_iri=request["verb_iri"], tool_urn=request["tool_urn"],
        )
        if ctx.key() != expected_key:
            raise ValueError(
                f"VirtualObject key {ctx.key()!r} does not match the "
                f"request's identity {expected_key!r}. Caller built the "
                f"key wrong — registration identity is "
                f"(verb_iri, _tool_urn), see ADR-0019 §5 addendum."
            )

        # Resolve driver + weaviate client inside the handler so the
        # request shape stays JSON-serializable.
        from agent_fleet.mesh_registrar.main import (
            _get_neo4j_driver, _get_weaviate_client,
        )

        def _invoke() -> dict:
            outcome = v2_saga.run_registration_saga(
                driver=_get_neo4j_driver(),
                weaviate_client=_get_weaviate_client(),
                verb_iri=request["verb_iri"],
                input_uri=request["input_uri"],
                output_uri=request["output_uri"],
                tool_urn=request["tool_urn"],
                rel_props=request.get("rel_props", {}),
                description=request.get("description", ""),
                endpoint_url=request["endpoint_url"],
                owner_persona=request.get("owner_persona") or "",
                domains=list(request.get("domains") or []),
                cost_class=request.get("cost_class", "medium"),
                requires_human_approval=bool(
                    request.get("requires_human_approval", False)
                ),
                synonyms=list(request.get("synonyms") or []),
                anti_synonyms=list(request.get("anti_synonyms") or []),
                budget_s=request.get("budget_s"),
            )
            return {
                "status": outcome.status,
                "http_code": outcome.http_code,
                "reason": outcome.reason,
                "neo4j_written": outcome.neo4j_written,
                "weaviate_written": outcome.weaviate_written,
                "probe": outcome.probe,
                "forward_retry_attempts": outcome.forward_retry_attempts,
                "elapsed_s": outcome.elapsed_s,
            }

        return await ctx.run(SAGA_STEP_NAME, _invoke)
