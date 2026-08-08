"""FastAPI app wrapping the projector apply loop.

Endpoints:
  GET /health              — readiness + liveness, returns 200 if loop alive.
  GET /projector/watermark — Decision 4 (Option C revised) liveness probe.
                             Reads cursor FROM POSTGRES, not from in-memory
                             state — so a dead loop with a stale memory
                             mirror cannot fake liveness. Per
                             [[liveness-probe-watches-advance-not-just-correctness]].
  POST /projector/poll     — force one apply batch (probes use this to
                             cut poll-interval latency on test runs).

The apply loop runs as an asyncio background task started in the
FastAPI lifespan handler. Lifespan owns startup AND shutdown so the
loop drains cleanly on SIGTERM.
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI
from iagent_mesh.transport_auth import announce as _announce_transport_auth
from iagent_mesh.transport_auth import make_transport_auth_dependency as _transport_auth

_announce_transport_auth(component="projector")

from .apply_loop import ApplyLoop, build_loop_from_env

logger = logging.getLogger(__name__)


# Per `[[optimistic-defaults-are-dishonest]]`: default is OFF. A
# forgotten env var leaves the endpoint absent — the failure-revealing
# default for an unauthenticated mutation surface. Truthy spellings
# accepted because deploy systems vary; "true"/"1"/"yes" mean enable.
_TRUTHY_ENV_VALUES = {"true", "1", "yes"}


def _force_poll_enabled() -> bool:
    """Returns True iff PROJECTOR_ENABLE_FORCE_POLL is explicitly truthy.

    The default-off behavior closes the carry-forward
    [[projector-hardening-carry-forwards]] item (b): `POST
    /projector/poll` was previously mounted unconditionally,
    exposing an unauthenticated mutation surface in every
    production deploy. Tests that NEED the affordance set the env
    in their bootstrap (Hop 2 phase suite, this file's gating
    suite); production never sets it.
    """
    raw = os.environ.get("PROJECTOR_ENABLE_FORCE_POLL", "").strip().lower()
    return raw in _TRUTHY_ENV_VALUES


def create_app(loop: Optional[ApplyLoop] = None) -> FastAPI:
    """Build the FastAPI app. The `loop` arg is for tests; production
    uses `build_loop_from_env()`.
    """
    _loop: Optional[ApplyLoop] = loop
    _task: Optional[asyncio.Task] = None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal _loop, _task
        if _loop is None:
            _loop = build_loop_from_env()
        # Stash so the endpoints can reach it.
        app.state.loop = _loop
        _task = asyncio.create_task(_loop.run_forever())
        logger.info("projector app started; apply loop scheduled")
        try:
            yield
        finally:
            logger.info("projector app shutting down; stopping loop")
            _loop.close()
            if _task is not None:
                try:
                    await asyncio.wait_for(_task, timeout=5.0)
                except asyncio.TimeoutError:
                    _task.cancel()

    # Inbound transport auth (OBSERVE by default) — the SDK's ONE implementation, applied as an
    # app-level dependency so it covers every route below. The projector was outside the
    # "fleet-wide" claim until 2026-08-07 purely because the applied-everywhere test derived its
    # population from `agent_fleet/*/main.py`: the GLOB was the boundary, not a decision.
    app = FastAPI(
        lifespan=lifespan,
        title="iagent-projector",
        dependencies=[Depends(_transport_auth("projector"))],
    )

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/projector/watermark")
    def watermark():
        """Decision 4's liveness probe. Reads the cursor FROM
        POSTGRES; a dead loop with a stale in-memory copy CANNOT
        report a fresh value here. Probes call this twice with a write
        between, assert the second > the first.
        """
        loop: ApplyLoop = app.state.loop
        state = loop.get_cursor_state()
        return {
            "last_applied_watermark": state.last_applied_watermark,
            "last_apply_at_ms": state.last_apply_at_ms,
            "apply_count": state.apply_count,
        }

    # POST /projector/poll is registered ONLY when PROJECTOR_ENABLE_FORCE_POLL
    # is explicitly truthy. When unset, FastAPI returns 404 — the
    # honest-default per [[optimistic-defaults-are-dishonest]] for an
    # unauthenticated mutation surface. Test bootstraps that need the
    # affordance set the env explicitly.
    if _force_poll_enabled():
        @app.post("/projector/poll")
        async def force_poll():
            """Force one apply batch. Test affordance — production polls on
            the configured interval. The probe suite uses this to cut the
            poll-interval wait down to near-zero so phase probes don't
            spend 500ms-per-step idle.

            Uses apply_once_async so the run_forever interval loop's
            concurrent apply cannot race this one — both callers grab
            ApplyLoop._apply_lock. See item (b) closure in
            [[projector-hardening-carry-forwards]].
            """
            loop: ApplyLoop = app.state.loop
            applied = await loop.apply_once_async()
            return {"applied": applied}
        logger.info(
            "projector: POST /projector/poll mounted "
            "(PROJECTOR_ENABLE_FORCE_POLL=true)"
        )
    else:
        logger.info(
            "projector: POST /projector/poll NOT mounted "
            "(PROJECTOR_ENABLE_FORCE_POLL unset/false; default-off)"
        )

    return app


# Module-level app for `uvicorn iagent.projector.app:app` style.
# Production deployments instantiate this; tests use `create_app(loop)`
# with an injected loop and lifespan.
app = create_app()
