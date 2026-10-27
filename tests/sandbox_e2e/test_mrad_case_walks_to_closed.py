# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx>=0.27"]
# ///
"""A maintenance-fault case renders, is decided, and walks to closed (live sandbox).

The e2e step behind "a case renders": the `maint_fault_propose` template's `render` step (not
the walk) is what builds the options, and only a live case can show a case reaching the
`decide` task through `walk` and `options`. lane/74's walk of 2026-10-17 (`MRAD-ARR-0417
walked live to closed`, case 712382d7-00c2-5610-a3cf-0e1c9ef5ea70) is the record of the first
flip; this step repeats that walk through product routes only, as three people:

  initiator  POST /ingest/events (cm_discrepancy, MRAD-ARR-0417 on dis:1:1:1008), then reads
             GET /cases/{id}
  decider    POST /human_tasks/{instance}:decide/act  -> replace_now
             POST /human_tasks/{instance}:review/act  -> approved   (the supervisor review)
  releaser   POST /cases/{case_id}/signals/tier_ack  -> released, BY THE CASE ID (D1)

WHAT THE PROJECTION CAN SHOW. `GET /cases/{id}` always projects `options: []` (see
`case_projection`), so the options themselves are not readable here. "A case renders" is
therefore asserted as what the projection does show: instance 1 is `maint_fault_propose`,
its definition carries the `walk`, `options` and `decide` steps, and a `decide` approval is
PENDING, i.e. the case ran through `walk` and `options` and reached the `decide` task.

This WRITES to the live sandbox. It is not a unit test (no pytest function in this file, so a
unit run collects nothing) and is run by hand after a roll:

    kubectl -n sandbox port-forward svc/iagent-cortex-bff 18090:8090 &
    uv run tests/sandbox_e2e/test_mrad_case_walks_to_closed.py \\
        --initiator-token erin.jwt --decider-token bob.jwt --releaser-token alice.jwt

Tokens are read from files and never printed (only length and the first 8 hex of the sha256).
TLS: httpx honours SSL_CERT_FILE; never disable verification.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time
import uuid
from pathlib import Path

import httpx

FAULT = "MRAD-ARR-0417"
PLATFORM = "dis:1:1:1008"
POLL_S = 5.0
POLL_MAX_S = 120.0


class Fail(Exception):
    def __init__(self, step: str, status, body):
        super().__init__(step)
        self.step, self.status, self.body = step, status, str(body)[:300]


def _token(path: str) -> tuple[str, str]:
    tok = Path(path).read_text(encoding="utf-8").strip()
    return tok, f"len={len(tok)} sha256={hashlib.sha256(tok.encode()).hexdigest()[:8]}"


def _event(event_id: str) -> dict:
    """A MaintenanceEvent in the shape `policy/overlays/openddil-lab/triggers/
    maintenance_fault.yaml` requires. mission_essential is true so the supervisor review
    runs, as in the lane/74 walk. The item is the walk's (`tr_module`): the episode is
    asset + item + fault code, so an OPEN case on that episode would take this event instead of
    opening a new one -- close or wait out any open MRAD-0417 case on dis:1:1:1008 first."""
    return {
        "event_id": event_id, "kind": "cm_discrepancy", "asset_id": PLATFORM,
        "owning_tier": "edge-01",
        "fault": {"item": "tr_module", "fault_code": FAULT,
                  "observed_at": "2026-10-17T00:00:00Z"},
        "sources": [{"system": "bit"}],
        "picture": {"readiness": "PMC", "factors": ["array"], "lifecycle": "in_service",
                    "spares": [], "nearest_spare": None,
                    "battle_condition": {
                        "mission_essential": True,
                        "basis": {"rule": "readiness-rollup:edge-01",
                                  "observed_at": "2026-10-17T00:00:00Z"}}},
        "label": {"originator_nation": "US", "releasable_to": ["US"]},
        "provenance": [],
    }


class Walk:
    def __init__(self, base: str, tokens: dict[str, str]):
        self.base, self.tokens = base.rstrip("/"), tokens
        self.http = httpx.Client(timeout=30.0)

    def call(self, who: str, method: str, path: str, step: str, ok=(200,), **kw):
        r = self.http.request(method, f"{self.base}{path}", **kw,
                              headers={"Authorization": f"Bearer {self.tokens[who]}"})
        if r.status_code not in ok:
            raise Fail(step, r.status_code, r.text)
        return r

    def case(self, case_id: str, step: str, ok=(200,)):
        return self.call("initiator", "GET", f"/cases/{case_id}", step, ok=ok)

    def wait(self, case_id: str, step: str, pred):
        """Poll GET /cases/{id} (as the initiator) until `pred(payload)`; 404 early is
        'not there yet'. Bounded: POLL_MAX_S at POLL_S."""
        deadline = time.monotonic() + POLL_MAX_S
        last = None
        while time.monotonic() < deadline:
            r = self.case(case_id, step, ok=(200, 404))
            last = r.text
            if r.status_code == 200 and pred(r.json()):
                return r.json()
            time.sleep(POLL_S)
        raise Fail(step, "timeout", last)


def _pending(payload: dict, step_id: str):
    return next((a for a in payload.get("approvals") or []
                 if a.get("step_id") == step_id and a.get("status") == "pending"), None)


def _renders(payload: dict) -> bool:
    insts = payload.get("instances") or []
    if not insts or insts[0]["definition"]["id"] != "maint_fault_propose":
        return False
    steps = [s["id"] for s in insts[0]["definition"]["steps"]]
    return steps[:3] == ["walk", "options", "decide"] and _pending(payload, "decide") is not None


def walk(w: Walk, initiator_id: str | None) -> None:
    if not initiator_id:
        ent = w.call("initiator", "GET", "/me/entitlements", "initiator identity").json()
        initiator_id = ent.get("email")  # in the sandbox authz_id == email
    event_id = f"e2e-mrad-{uuid.uuid4().hex[:8]}"
    r = w.call("initiator", "POST", "/ingest/events", "ingest the fault event", json={
        "content_kind": "maintenance-fault-event", "on_behalf_of": initiator_id,
        "payload": _event(event_id)})
    case_id = ((r.json().get("workflow") or {}).get("case_id"))
    if not case_id:
        raise Fail("find the case id", r.status_code, r.text)
    print(f"event {event_id}; case id from POST /ingest/events workflow.case_id: {case_id}")

    p = w.wait(case_id, "a case renders (walk, options, decide pending)", _renders)
    inst1 = p["instances"][0]["workflow_id"]
    print(f"PASS a case renders: {inst1} reached its pending `decide` task")

    w.call("decider", "POST", f"/human_tasks/{inst1}:decide/act", "decider chooses replace_now",
           json={"decision": "replace_now"})
    print("PASS decide -> replace_now")

    p = w.wait(case_id, "supervisor review is pending", lambda x: _pending(x, "review"))
    review = _pending(p, "review")["workflow_id"]
    w.call("decider", "POST", f"/human_tasks/{review}:review/act", "supervisor review approved",
           json={"decision": "approved"})
    print("PASS review -> approved")

    # The release instance journals the awaited signal a moment after the review resumes it, so
    # a 403 "is awaited" is retried (bounded); any other refusal is a failure.
    deadline = time.monotonic() + POLL_MAX_S
    while True:
        r = w.call("releaser", "POST", f"/cases/{case_id}/signals/tier_ack",
                   "release by the CASE ID (D1)", ok=(200, 403), json={"status": "released"})
        if r.status_code == 200:
            break
        if "awaited" not in r.text or time.monotonic() > deadline:
            raise Fail("release by the CASE ID (D1)", r.status_code, r.text)
        time.sleep(POLL_S)
    print(f"PASS tier_ack by case id -> 200, instance {r.json().get('instance_id')}")

    def closed(x):
        h = x.get("history") or []
        return bool(h) and h[-1].get("stage") == "closed"
    w.wait(case_id, "the case is closed", closed)
    print(f"PASS case {case_id} closed")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--bff-url", default=os.getenv("BFF_URL", "http://localhost:18090"))
    ap.add_argument("--initiator-token", required=True, help="file holding erin's bearer token")
    ap.add_argument("--decider-token", required=True, help="file holding bob's bearer token")
    ap.add_argument("--releaser-token", required=True, help="file holding alice's bearer token")
    ap.add_argument("--initiator-authz-id", default=None,
                    help="on_behalf_of for the event; default: the initiator's email from "
                         "/me/entitlements (authz_id == email in the sandbox)")
    a = ap.parse_args()
    tokens = {}
    for who in ("initiator", "decider", "releaser"):
        tokens[who], desc = _token(getattr(a, f"{who}_token"))
        print(f"{who} token: {desc}")
    try:
        walk(Walk(a.bff_url, tokens), a.initiator_authz_id)
    except Fail as f:
        print(f"FAIL {f.step}: HTTP {f.status}: {f.body}")
        return 1
    except httpx.HTTPError as e:
        print(f"FAIL transport: {type(e).__name__}: {str(e)[:300]}")
        return 1
    print("ALL STEPS HELD")
    return 0


if __name__ == "__main__":
    sys.exit(main())
