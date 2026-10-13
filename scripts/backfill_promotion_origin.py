#!/usr/bin/env python
"""Backfill the origin of documents promoted before a promotion recorded one.

WHY A BACKFILL. Ruled: `document_promotion:<D>` is a domain task, and when a steward of D
promotes a drop that has no system-of-record origin, the promotion records origin = D at the
SDK's `steward` rung, citing the decision record (`steward_attestation:<record_id>` in
`origin_evidence`). Documents promoted BEFORE that change carry the promotion fact but no
origin. The promoting task's domain is on the decision record (the human_review check's
`audience`, `document_promotion:<D>`), so it is read from there -- never guessed.

ONE WRITER. The write goes through `Neo4jIngestGraph.attest_origin`, the very method the
promotion act calls, so the keep rule is the same: a node already at `record` or `steward` is
left alone, and a second run therefore writes nothing. A record whose audience is missing or
unparseable is SKIPPED and listed, never guessed. A node that does not exist is counted, never
created.

    DRY RUN (default):  uv run --frozen python scripts/backfill_promotion_origin.py
    APPLY:              uv run --frozen python scripts/backfill_promotion_origin.py --apply

Needs PROJECTOR_POSTGRES_DSN (the decision ledger) and NEO4J_URI / NEO4J_USERNAME /
NEO4J_PASSWORD. The graph write is made as the acting identity named by BACKFILL_ACTOR
(a person), as every promotion write is.

LIST OLD AUDIENCES (`--list-old-audiences`; ruling Q6, architect, 2026-10-10). Live
`document_promotion` tasks whose audience is not `document_promotion:<D>` cannot be promoted
(`promotion.domain_of` refuses them), so Lane 1 lists them during the rev-187 roll and refiles
them. This mode ONLY LISTS: it needs PROJECTOR_POSTGRES_DSN alone, touches no graph, and writes
nothing anywhere.

Exit codes:
    0  nothing to do, or applied successfully
    1  writes pending (dry run), or rows skipped as unparseable
    2  could not look (no DSN, unreachable store)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

KIND = "document_promotion"


def audience_domain(record: Any) -> str | None:
    """D from the record's `human_review` check audience (`document_promotion:<D>`), or None."""
    if isinstance(record, str):
        try:
            record = json.loads(record)
        except ValueError:
            return None
    if not isinstance(record, dict):
        return None
    for check in record.get("checks") or []:
        inputs = check.get("inputs") if isinstance(check, dict) else None
        audience = inputs.get("audience") if isinstance(inputs, dict) else None
        if isinstance(audience, str):
            prefix, _, domain = audience.partition(":")
            if prefix == KIND and domain.strip():
                return domain
    return None


def backfill(records: Iterable[dict], graph: Any, *, apply: bool = False) -> dict:
    """`records`: dicts with `record_id`, `ingest_id`, `record` (the stored record, JSON or
    dict). `graph`: `node_exists`, `origin_rung`, `attest_origin`. Pure over those two handles.
    Dry run (apply=False) reads and writes nothing."""
    out = {"written": 0, "kept_record": 0, "kept_steward": 0, "skipped_unparseable": 0,
           "node_absent": 0, "skipped_ingest_ids": [], "applied": apply}
    for row in records:
        ingest_id, record_id = row["ingest_id"], row["record_id"]
        domain = audience_domain(row.get("record"))
        if domain is None:
            out["skipped_unparseable"] += 1
            out["skipped_ingest_ids"].append(ingest_id)
            continue
        if not graph.node_exists(ingest_id):
            out["node_absent"] += 1
            continue
        if apply:
            outcome = graph.attest_origin(ingest_id, owner_domain=domain, record_id=record_id)
        else:
            rung = graph.origin_rung(ingest_id)
            outcome = {"record": "kept_record", "steward": "kept_steward"}.get(rung, "written")
        out[outcome] += 1
    return out


def _proposed(payload: Any) -> tuple[str | None, str]:
    """The domain a refiler should propose, from the payload only -- never from the audience."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            payload = None
    if not isinstance(payload, dict):
        return None, "undecided"
    for key, label in (("review_pool", "review_pool"), ("domain", "payload_domain")):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip().upper(), label
    return None, "undecided"


def old_audience_tasks(rows: Iterable[dict]) -> list[dict]:
    """Live promotion tasks whose audience `promotion.domain_of` refuses (one per task_id: keyed by
    it, so a per-recipient duplicate overwrites its twin -- they carry the same task)."""
    from src.iagent import promotion

    out: dict[str, dict] = {}
    for row in rows:
        task_id = row.get("task_id")
        audience = row.get("audience")
        try:
            promotion.domain_of(audience)
            continue
        except promotion.PromotionRefused:
            pass
        domain, source = _proposed(row.get("payload"))
        ingest_id = row.get("subject_ref") or (
            str(task_id).split(f"{KIND}:", 1)[1] if f"{KIND}:" in str(task_id) else None)
        out[task_id] = {"task_id": task_id, "ingest_id": ingest_id, "audience": audience,
                        "proposed_domain": domain, "proposed_from": source,
                        "created_at": row.get("created_at")}
    return sorted(out.values(), key=lambda r: (r["created_at"] or 0, str(r["task_id"])))


_LIST_SQL = ("SELECT DISTINCT ON (task_id) task_id, audience, subject_ref, payload, created_at "
             "FROM human_task_projection WHERE kind = 'document_promotion' "
             "AND status = 'pending' ORDER BY task_id, created_at")
_LIST_KEYS = ("task_id", "ingest_id", "audience", "proposed_domain", "proposed_from", "created_at")


def _list_old_audiences(dsn: str) -> int:
    try:
        import psycopg2

        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(_LIST_SQL)
            rows = [dict(zip(("task_id", "audience", "subject_ref", "payload", "created_at"), r))
                    for r in cur.fetchall()]
        old = old_audience_tasks(rows)
    except Exception as exc:  # noqa: BLE001
        print(f"COULD NOT LOOK (exit 2): {type(exc).__name__}: {exc}")
        return 2
    for t in old:
        print("\t".join("" if t[k] is None else str(t[k]) for k in _LIST_KEYS))
    undecided = sum(1 for t in old if t["proposed_from"] == "undecided")
    print(f"old_audience_tasks={len(old)} undecided={undecided}")
    return 1 if old else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true",
                      help="perform the writes; without it this only reports")
    mode.add_argument("--list-old-audiences", action="store_true",
                      help="list live promotion tasks with a non-domain audience; writes nothing")
    args = ap.parse_args()

    dsn = (os.getenv("PROJECTOR_POSTGRES_DSN") or "").strip()
    if not dsn:
        print("PROJECTOR_POSTGRES_DSN is unset -- COULD NOT LOOK (exit 2).")
        return 2
    if args.list_old_audiences:
        return _list_old_audiences(dsn)
    actor = (os.getenv("BACKFILL_ACTOR") or "").strip()
    if not actor:
        print("BACKFILL_ACTOR is unset -- the graph write is a person's (exit 2).")
        return 2
    try:
        import psycopg2
        from iagent_mesh.interfaces import Initiator
        from neo4j import GraphDatabase

        from src.iagent import promotion_stores

        with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("SELECT record_id, ingest_id, record FROM document_decision_record "
                        "WHERE decision = 'promoted' ORDER BY acted_at, record_id")
            rows = [{"record_id": a, "ingest_id": b, "record": c} for a, b, c in cur.fetchall()]
        driver = GraphDatabase.driver(
            os.getenv("NEO4J_URI", "bolt://neo4j:7687"),
            auth=(os.getenv("NEO4J_USERNAME", "neo4j"), os.getenv("NEO4J_PASSWORD", "")))
        graph = promotion_stores.Neo4jIngestGraph(
            driver=driver, initiator=Initiator(subject=actor, kind="person"))
        result = backfill(rows, graph, apply=args.apply)
    except Exception as exc:  # noqa: BLE001
        print(f"COULD NOT LOOK (exit 2): {type(exc).__name__}: {exc}")
        return 2

    print(f"{len(rows)} promoted record(s): " + ", ".join(
        f"{k}={result[k]}" for k in ("written", "kept_record", "kept_steward",
                                     "skipped_unparseable", "node_absent")))
    for iid in result["skipped_ingest_ids"]:
        print(f"    skipped (audience unparseable): {iid}")
    if not args.apply:
        print("DRY RUN -- nothing written. Re-run with --apply. Exit 1 means writes are "
              "PENDING or rows were skipped, not that anything failed.")
        return 1 if (result["written"] or result["skipped_unparseable"]) else 0
    return 1 if result["skipped_unparseable"] else 0


if __name__ == "__main__":
    sys.exit(main())
