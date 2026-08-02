"""Ship a decision record to the DECISIONS graph via engine-o.

ADR-0034 Phase 1. The transport half of `decision_record.emit()` — kept separate so the
record's CONTRACT stays pure and testable without a store, and so the store can change without
touching the schema.

FAILS SOFT, DELIBERATELY, AND THIS IS THE ONE ASYMMETRY IN THE ARC.
Everywhere else this codebase makes the reporting path fail LOUDER than what it reports
(`feedback_error_path_is_an_error_surface`). A decision record is the opposite case and the
difference is worth stating precisely:

  * a TRIAGE task is the ONLY route by which a refused notice reaches a human — losing it
    loses the notice, so its failure must be loud.
  * a DECISION RECORD is an OBSERVATION OF work that is happening anyway. If the graph is
    briefly unreachable, raising here would convert an audit-trail outage into a REVIEW
    outage: notices would stop being processed because we could not write down that we
    processed them. That trade is backwards — the pipeline's job survives the corpus, not the
    other way round.

So a write failure logs loudly and continues, and the MISS IS COUNTED rather than shrugged
off: a corpus with silent holes would let a promotion be computed over a sample that quietly
excluded the failures, which is precisely the bias that matters. Gaps are visible in the logs
and, once the corpus is queried, as a count that does not match the run count.

SCHEMA VIOLATIONS ARE NOT TRANSPORT FAILURES and still raise — a malformed record is a bug in
the emitter, not an outage, and it must not be normalized into a warning.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

from .decision_record import canonical_json, validate_decision_record

logger = logging.getLogger(__name__)

_ENGINE_O_URL = os.getenv("ONTOLOGY_SERVICE_URL", "http://iagent-engine-o:8084")
_TIMEOUT = float(os.getenv("DECISION_RECORD_TIMEOUT", "10"))
# Flip to "production" when the system is declared commissioned. Until then every record is
# marked commissioning, so promotion queries exclude the shakedown BY DECLARATION.
DECISION_RECORD_ERA = os.getenv("DECISION_RECORD_ERA", "commissioning").strip() or "commissioning"


def graph_writer(record: dict, *, engine_o_url: Optional[str] = None,
                 now_ms: Optional[int] = None) -> dict:
    """POST one record to engine-o's `/write_decision_record`. Raises on a malformed record
    (validate first), returns a status dict otherwise — including on transport failure."""
    import httpx
    import time

    validate_decision_record(record)          # bug, not outage -> raises
    gov = record.get("governing") or {}
    payload = {
        "record_id": record["record_id"],
        "domain": (record.get("governing") or {}).get("domain") or "SUSTAINMENT",
        "canonical": canonical_json(record),
        "format_fingerprint": record["format_fingerprint"],
        "pipeline_version": record["pipeline_version"],
        "outcome": record["outcome"],
        "admitted_by": record["admitted_by"],
        "trust_rung": record["trust_rung"],
        "era": record["era"],
        "ruleset_ref": gov.get("ruleset_ref", ""),
        "trust_table_ref": gov.get("trust_table_ref", ""),
        "emitted_at_ms": now_ms if now_ms is not None else int(time.time() * 1000),
    }
    url = f"{(engine_o_url or _ENGINE_O_URL).rstrip('/')}/write_decision_record"
    try:
        resp = httpx.post(url, json=payload, timeout=_TIMEOUT)
    except Exception as exc:  # noqa: BLE001
        logger.warning("DECISION RECORD NOT WRITTEN (transport) id=%s outcome=%s: %s — the "
                       "notice was processed; the corpus has a HOLE here",
                       record["record_id"], record["outcome"], exc)
        return {"ok": False, "reason": "unreachable", "detail": str(exc)}
    if resp.status_code == 409:
        # An immutability refusal is INFORMATION, not an error: a different record already
        # exists under this id. Surfaced so it is investigable rather than retried into noise.
        logger.warning("DECISION RECORD REFUSED (immutable) id=%s: %s",
                       record["record_id"], resp.text[:300])
        return {"ok": False, "reason": "immutable_conflict", "detail": resp.text[:300]}
    if resp.status_code != 200:
        logger.warning("DECISION RECORD NOT WRITTEN (HTTP %s) id=%s: %s — the corpus has a "
                       "HOLE here", resp.status_code, record["record_id"], resp.text[:300])
        return {"ok": False, "reason": f"http_{resp.status_code}", "detail": resp.text[:300]}
    try:
        body = resp.json()
    except Exception:  # noqa: BLE001
        body = {}
    return {"ok": True, "status": body.get("status", "appended"), "graph": body.get("graph", "")}
