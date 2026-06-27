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
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI

from .apply_loop import ApplyLoop, build_loop_from_env

logger = logging.getLogger(__name__)


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

    app = FastAPI(lifespan=lifespan, title="iagent-projector")

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

    @app.post("/projector/poll")
    async def force_poll():
        """Force one apply batch. Test affordance — production polls on
        the configured interval. The probe suite uses this to cut the
        poll-interval wait down to near-zero so phase probes don't
        spend 500ms-per-step idle.
        """
        loop: ApplyLoop = app.state.loop
        applied = await asyncio.to_thread(loop.apply_once)
        return {"applied": applied}

    return app


# Module-level app for `uvicorn iagent.projector.app:app` style.
# Production deployments instantiate this; tests use `create_app(loop)`
# with an injected loop and lifespan.
app = create_app()
