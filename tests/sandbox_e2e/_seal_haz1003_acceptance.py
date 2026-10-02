"""R-076 end to end: a real "Draft a risk assessment for HAZ-1003" turn opens ONE acceptance.

RUN AFTER THE ROLL THAT DEPLOYS THE ORDINARY-PATH CONSUMER, never before: on a fleet without it
the right answer is zero rows, and this script would report that as the defect it seals.

    BFF_URL / KEYCLOAK_URL   as mesh_client (port-forwards, see README)
    HITL_POSTGRES_DSN        the projection's DSN. Required, never defaulted: no credential or
                             host is committed. The session is READ ONLY
                             (default_transaction_read_only=on); this script inserts nothing.

    uv run tests/sandbox_e2e/_seal_haz1003_acceptance.py

A SCRIPT, NOT A test_ MODULE, like its neighbours. `pytest tests/` collects this directory, and
a test function here would fire a real turn and write a real task in Lane 1's full suite.

WHAT PASSES. After the turn:
  1. the stream carries no `pipeline_error` with cause `acceptance_not_opened`;
  2. `human_task_projection` holds exactly ONE logical task (one distinct `task_id`) of kind
     `risk_acceptance_<level>` whose `workflow_id` is `acceptance_workflow_id(HAZ-1003, level)`.
     One logical task fans out to one row per authorized recipient, so a ROW count is reported
     beside it but asserting it would assert the audience's size, not the dispatch;
  3. VIA THE DISPATCH PATH: that `workflow_id` is the Restate key the gateway sends to and that
     `SafetyAcceptance` registers under (`ctx.key()`). Nothing else writes that key;
  4. IDEMPOTENT: if the task already existed before the turn, the turn added no second one.
The expected kind and key are DERIVED from the engine's own draft code, not typed here.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for p in (_ROOT, _ROOT / "src", Path(__file__).resolve().parent):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

HAZARD = "HAZ-1003"
QUESTION = f"Draft a risk assessment for {HAZARD}"


def _expected() -> dict:
    """Kind and workflow key the fleet will produce, from the same code it runs."""
    from agent_fleet.safety_agent import measures
    from iagent_pure import acceptance_request as ar
    rr = ar.review_request_of(measures.draft_risk_assessment(hazard_id=HAZARD))
    if not rr:
        raise SystemExit(f"FIXTURE VOID: the local {HAZARD} draft asks for no review")
    trig = ar.acceptance_trigger(rr)
    return {"kind": trig["kind"],
            "workflow_id": ar.acceptance_workflow_id(trig["hazard_id"], trig["level_slug"])}


def _read(dsn: str, exp: dict) -> dict:
    import psycopg
    with psycopg.connect(dsn, options="-c default_transaction_read_only=on") as conn:
        with conn.cursor() as cur:
            cur.execute("SHOW default_transaction_read_only")
            assert cur.fetchone()[0] == "on", "refusing to run: the session is not read-only"
            cur.execute(
                "SELECT count(*), count(DISTINCT task_id), array_agg(DISTINCT workflow_id) "
                "FROM human_task_projection WHERE kind = %s AND workflow_id LIKE %s",
                (exp["kind"], f"risk-acceptance-{HAZARD}-%"),
            )
            rows, tasks, wfs = cur.fetchone()
    return {"rows": rows, "tasks": tasks, "workflow_ids": sorted(w for w in (wfs or []) if w)}


def _errors(result: dict) -> list:
    out = []
    for ev in result.get("events") or []:
        blob = json.dumps(ev, default=str)
        if "acceptance_not_opened" in blob:
            out.append(blob[:400])
    return out


async def main() -> int:
    dsn = os.environ.get("HITL_POSTGRES_DSN")
    if not dsn:
        print("HITL_POSTGRES_DSN is not set: nothing measured (NOT a pass)")
        return 2
    import mesh_client as mc

    exp = _expected()
    print(f"expected kind={exp['kind']} workflow_id={exp['workflow_id']}")
    before = _read(dsn, exp)
    print(f"before: {before}")

    result = await mc.fire(QUESTION, session_prefix="seal-haz1003-acceptance")
    after = _read(dsn, exp)
    print(f"after:  {after}")

    fails = []
    errs = _errors(result)
    if errs:
        fails.append(f"the stream reports the acceptance NOT opened: {errs}")
    if after["tasks"] != 1:
        fails.append(f"{after['tasks']} logical tasks, expected exactly 1")
    if after["workflow_ids"] != [exp["workflow_id"]]:
        fails.append(f"workflow_id {after['workflow_ids']} is not the dispatch key "
                     f"{exp['workflow_id']}")
    if before["tasks"] and after["tasks"] != before["tasks"]:
        fails.append("the task already existed and the turn added another: not idempotent")

    if fails:
        print("FAIL\n  " + "\n  ".join(fails))
        return 1
    print(f"PASS: one {exp['kind']} task under {exp['workflow_id']} "
          f"({after['rows']} recipient rows; before the turn: {before['tasks']} tasks)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
