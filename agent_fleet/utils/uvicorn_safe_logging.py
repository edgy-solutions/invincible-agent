"""Loggers that survive uvicorn's startup reconfiguration.

THE DEFECT THIS EXISTS FOR. uvicorn replaces the root handler when it starts, so
every record that relies on ``logging.basicConfig`` — or on propagation to root —
is silently dropped. Not downgraded, not buffered: dropped, with the process
otherwise healthy and its access logs flowing, which is what makes it so hard to
notice. Two engines discovered this independently and each hand-rolled the same
repair on their OWN named logger:

    agent_fleet/presentation_agent/main.py   -> logger "presentation_agent"
    agent_fleet/ontology_service/main.py     -> logger "ontology_service"

Neither repair reached ``agent_fleet/utils/mesh_registration.py``, which uses its
own logger ("mesh_registration") and is the module BOTH of them delegate their
registration to. So the engines could speak and the shared module could not.

WHAT THAT COST, measured 2026-08-21: engine-f registered ten presentations
through the mesh-registrar gateway and printed NOTHING about it. Not the success
line, not the fallback line, not the three-way refusal classification built
specifically so an operator could tell "ship the image" from "fix the
registration" from "check the network". The discriminator worked perfectly into a
log nobody could read. Worse, a retirement trigger had just been written whose
condition was `kubectl logs | grep "VIA GATEWAY"` — a condition that could never
be observed, and therefore not a condition at all.

The rows in Weaviate proved the path; the log proved nothing. Verifying the
OUTCOME is what saved that diagnosis, and it should not have had to.

WHY A SHARED HELPER rather than a third hand-rolled copy: the pattern drifted
precisely because it was per-module. A module that logs must not have to
rediscover this, and the next shared module to be added must not inherit the
silence by default.
"""
from __future__ import annotations

import logging
import os
import sys

_DEFAULT_FORMAT = "%(levelname)s:%(name)s:%(message)s"


def ensure_stdout_logger(
    name: str,
    *,
    level: int | None = None,
    fmt: str = _DEFAULT_FORMAT,
) -> logging.Logger:
    """Return a logger whose records reach stdout regardless of uvicorn.

    Attaches a StreamHandler to the NAMED logger and sets ``propagate = False``,
    so the record neither depends on the root handler nor double-prints through
    uvicorn's. Idempotent: a logger that already owns a handler is left alone, so
    importing this from several modules cannot stack duplicate handlers.

    ``level`` defaults to ``LOG_LEVEL`` from the environment (INFO if unset), so
    a deployment can raise or lower verbosity without a code change — the thing
    that was impossible while the records were being dropped outright.
    """
    logger = logging.getLogger(name)

    if not any(getattr(h, "_iagent_stdout", False) for h in logger.handlers):
        handler = logging.StreamHandler(stream=sys.stdout)
        handler.setFormatter(logging.Formatter(fmt))
        # Tagged so idempotency keys on OUR handler rather than on "has any
        # handler at all" — a library that attached its own would otherwise
        # suppress this one and restore the silence.
        handler._iagent_stdout = True  # type: ignore[attr-defined]
        logger.addHandler(handler)

    if level is None:
        level_name = (os.getenv("LOG_LEVEL") or "INFO").upper()
        level = getattr(logging, level_name, logging.INFO)
    logger.setLevel(level)

    # The record is delivered by OUR handler; propagating as well would print it
    # twice under a root that is configured, and rely on a root that is not.
    logger.propagate = False
    return logger
