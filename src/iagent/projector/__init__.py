"""Hop 2 of the projector build plan — Neo4j → Postgres projector.

Standalone service shape (Decision 4, permanent): poll loop + cursor +
FastAPI endpoint, deployed as its own pod (`iagent-projector`). Mirrors
cortex-bff's deployment shape so a future operator who reads frontend.yaml
can read projector.yaml the same way.

INTERIM mechanisms (per [[coupled-interim-mechanisms-retire-together]] —
this plan is the first banked instance of that rule):
    - The 500ms poll loop (Decision 1) — retires when the Restate+topic
      successor lands; the projector becomes a topic consumer.
    - The watermark COLUMN (Decision 3 Option C) — retires when the
      topic offset becomes the position.
    - The durability_status field (Decision 0 sub-decision) — retires
      when the Restate durable handler replaces the recorded-state
      mechanism with a journal step.

All three retire together at the same trigger (cortex-bff's Redpanda
emit landing for independent reasons). Inline comments at each interim
mechanism cite this rule explicitly.

Public surface:
    from iagent.projector.apply_loop import ApplyLoop
    from iagent.projector.app import create_app

Run as a process:
    python -m iagent.projector
"""
from .apply_loop import ApplyLoop, CursorState

__all__ = ["ApplyLoop", "CursorState"]
