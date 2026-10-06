"""R-076 end to end: a real "Draft a risk assessment for HAZ-1003" turn opens ONE acceptance.

RUN AFTER THE ROLL THAT DEPLOYS THE ORDINARY-PATH CONSUMER, never before: on a fleet without it
the right answer is zero rows, and this script would report that as the defect it seals.

    BFF_URL / KEYCLOAK_URL   as mesh_client (port-forwards, see README)
    HITL_POSTGRES_DSN        the projection's DSN. The session is READ ONLY
                             (default_transaction_read_only=on); this script inserts nothing.
    HITL_READ_POD            OR a workload that already holds the DSN in its own env
                             (`deploy/iagent-cortex-bff`, DATABASE_URL): the same read-only
                             query runs inside it via `kubectl exec`, so the credential never
                             leaves the pod and only the counts come back. Namespace from
                             HITL_READ_NAMESPACE (default sandbox), kube context from
                             KUBECTL_CONTEXT if set. One of the two is required; neither is
                             defaulted, and no credential, host or context is committed.

    uv run tests/sandbox_e2e/_seal_haz1003_acceptance.py

A SCRIPT, NOT A test_ MODULE, like its neighbours. `pytest tests/` collects this directory, and
a test function here would fire a real turn and write a real task in Lane 1's full suite.

WHAT PASSES. After the turn:
  1. the stream carries no `pipeline_error` with cause `acceptance_not_opened`;
  2. `human_task_projection` holds exactly ONE logical task (one distinct `task_id`) of kind
     `risk_acceptance_<level>` under a CHILD of the case `acceptance_workflow_id(HAZ-1003,
     level)`: `{case}~{n}`, the separator imported from the runner's `case_routing.CHILD_SEP`.
     One logical task fans out to one row per authorized recipient, so a ROW count is reported
     beside it but asserting it would assert the audience's size, not the dispatch;
  3. VIA THE DISPATCH PATH: since 9ae5861f (ADR-0039) safety acceptance runs as a case through
     WorkflowRunner, and each definition is its own instance keyed `{case}~{n}`; the task row
     names that instance. A row under the BARE key was written by the retired SafetyAcceptance
     path; it is printed as STRANDED and does not count as this dispatch. A workflow_id of
     neither form fails;
  4. IDEMPOTENT: if the task already existed before the turn, the turn added no second one.
The expected kind and key are DERIVED from the engine's own draft code, not typed here.

THE CALLER is the census row's (bob, SAFETY_ENGINEER, SUSTAINMENT), pinned in CALLER. Fired as
mesh_client's default agent-user the turn never reaches safety, and every arm reads the
projection's prior state rather than anything the turn did.
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
#: The census row's caller (walk-census.yaml, safety-haz-1003-risk-assessment): bob,
#: SAFETY_ENGINEER, SUSTAINMENT. mesh_client defaults to agent-user, whose domains do not
#: include SUSTAINMENT -- fired as that user the turn is refused upstream and the seal
#: measures nothing about acceptance. Pinned here, not left to KC_USER in the environment.
CALLER = ("bob", "bob")
CHILD_MARK = "~"  # display only; _partition imports the runner's own CHILD_SEP


def _expected() -> dict:
    """Kind and workflow key the fleet will produce, from the same code it runs."""
    from agent_fleet.safety_agent import measures
    from iagent_pure import acceptance_request as ar
    rr = ar.review_request_of(measures.draft_risk_assessment(hazard_id=HAZARD))
    if not rr:
        raise SystemExit(f"FIXTURE VOID: the local {HAZARD} draft asks for no review")
    # Only the kind and the key are read here, and the requester changes neither.
    trig = ar.acceptance_trigger(rr, authz_id=CALLER[0])
    return {"kind": trig["kind"],
            "workflow_id": ar.acceptance_workflow_id(trig["hazard_id"], trig["level_slug"])}


#: Runs INSIDE the HITL_READ_POD workload: argv = kind, workflow_id pattern; prints counts only.
_IN_POD = r"""
import json, os, sys, psycopg2
dsn = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://", 1)
with psycopg2.connect(dsn, options="-c default_transaction_read_only=on") as conn:
    cur = conn.cursor()
    cur.execute("SHOW default_transaction_read_only")
    assert cur.fetchone()[0] == "on", "refusing to run: the session is not read-only"
    cur.execute("SELECT count(*), count(DISTINCT task_id), array_agg(DISTINCT workflow_id) "
                "FROM human_task_projection WHERE kind = %s AND workflow_id LIKE %s",
                (sys.argv[1], sys.argv[2]))
    rows, tasks, wfs = cur.fetchone()
    cur.execute("SELECT workflow_id, min(created_at), count(*), count(DISTINCT task_id), "
                "array_agg(DISTINCT status) FROM human_task_projection "
                "WHERE kind = %s AND workflow_id LIKE %s GROUP BY workflow_id ORDER BY 2",
                (sys.argv[1], sys.argv[2]))
    first_seen = {w: {"created_at": c, "rows": n, "tasks": t, "status": sorted(st or [])}
                  for w, c, n, t, st in cur.fetchall()}
print(json.dumps({"rows": rows, "tasks": tasks,
                  "workflow_ids": sorted(w for w in (wfs or []) if w),
                  "first_seen": first_seen}))
"""


def _read_in_pod(pod: str, exp: dict) -> dict:
    import subprocess
    cmd = ["kubectl"]
    if os.environ.get("KUBECTL_CONTEXT"):
        cmd += ["--context", os.environ["KUBECTL_CONTEXT"]]
    cmd += ["-n", os.environ.get("HITL_READ_NAMESPACE", "sandbox"), "exec", pod, "--",
            "python", "-c", _IN_POD, exp["kind"], f"risk-acceptance-{HAZARD}-%"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise SystemExit(f"in-pod read failed (exit {r.returncode}): {r.stderr[-400:]}")
    return json.loads(r.stdout.strip().splitlines()[-1])


def _read(dsn: str, exp: dict) -> dict:
    if dsn.startswith("pod:"):
        return _read_in_pod(dsn[len("pod:"):], exp)
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
            cur.execute(
                "SELECT workflow_id, min(created_at), count(*), count(DISTINCT task_id), "
                "array_agg(DISTINCT status) FROM human_task_projection "
                "WHERE kind = %s AND workflow_id LIKE %s GROUP BY workflow_id ORDER BY 2",
                (exp["kind"], f"risk-acceptance-{HAZARD}-%"),
            )
            first_seen = {w: {"created_at": c, "rows": n, "tasks": t, "status": sorted(st or [])}
                          for w, c, n, t, st in cur.fetchall()}
    return {"rows": rows, "tasks": tasks, "workflow_ids": sorted(w for w in (wfs or []) if w),
            "first_seen": first_seen}


def _partition(read: dict, key: str) -> tuple:
    """(case child tasks, bare-key tasks, other) by workflow_id FORM, never by position.

    ADR-0039 (9ae5861f): the case runner keys each definition's instance ``{case}~{n}``, and the
    task row names that instance. A row under the bare key was written by the retired
    SafetyAcceptance path and is a stranded pre-migration task, not this dispatch.
    """
    from agent_fleet.restate_analyst.case_routing import CHILD_SEP
    child, bare, other = {}, {}, {}
    for wf, info in (read.get("first_seen") or {}).items():
        head, sep, n = wf.partition(CHILD_SEP)
        if wf == key:
            bare[wf] = info
        elif head == key and sep and n.isdigit():
            child[wf] = info
        else:
            other[wf] = info
    return child, bare, other


def _errors(result: dict) -> list:
    out = []
    for ev in result.get("events") or []:
        blob = json.dumps(ev, default=str)
        if "acceptance_not_opened" in blob:
            out.append(blob[:400])
    return out


async def main() -> int:
    dsn = os.environ.get("HITL_POSTGRES_DSN") or (
        "pod:" + os.environ["HITL_READ_POD"] if os.environ.get("HITL_READ_POD") else "")
    if not dsn:
        print("neither HITL_POSTGRES_DSN nor HITL_READ_POD is set: nothing measured (NOT a pass)")
        return 2
    import mesh_client as mc

    exp = _expected()
    print(f"expected kind={exp['kind']} workflow_id={exp['workflow_id']}")
    before = _read(dsn, exp)
    print(f"before: {before}")

    mc.USERNAME, mc.PASSWORD = CALLER
    result = await mc.fire(QUESTION, session_prefix="seal-haz1003-acceptance")
    after = _read(dsn, exp)
    print(f"after:  {after}")

    fails = []
    errs = _errors(result)
    if errs:
        fails.append(f"the stream reports the acceptance NOT opened: {errs}")
    child, bare, other = _partition(after, exp["workflow_id"])
    case_tasks = sum(i["tasks"] for i in child.values())
    if case_tasks != 1:
        fails.append(f"{case_tasks} logical tasks under the case {exp['workflow_id']}"
                     f"{CHILD_MARK}n, expected exactly 1: {sorted(child)}")
    if other:
        fails.append(f"workflow_ids of neither form: {sorted(other)}")
    if before["tasks"] and after["tasks"] != before["tasks"]:
        fails.append("the task already existed and the turn added another: not idempotent")
    for wf, info in bare.items():
        print(f"STRANDED (not this dispatch): {wf} {info} -- written by the retired "
              f"SafetyAcceptance path before 9ae5861f; resolving it is a human's live write")

    if fails:
        print("FAIL\n  " + "\n  ".join(fails))
        return 1
    print(f"PASS: one {exp['kind']} task under {sorted(child)} "
          f"({after['rows']} recipient rows; before the turn: {before['tasks']} tasks)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
