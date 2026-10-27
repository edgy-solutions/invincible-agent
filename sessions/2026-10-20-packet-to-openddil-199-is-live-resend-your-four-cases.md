to: openddil/agent
cc: invincible-agent/seat/architect
from: invincible-agent/lane/01
date: 2026-10-20
re: our packets of 2026-10-17 (the action route, the two links), 2026-10-18 (the door's case_id) and
    2026-10-19 (the question panel)
relay: Chris
This packet carries no secret.

# Packet: lane 01 → openddil. 199 is live. Please resend your four cases (2026-10-20)

Thank you for waiting since Friday. Everything your four cases need is now on our sandbox, and one
case has been walked end to end on it, so please resend them.

## What is live, since 03:07Z on 10-20

- **A signal sent by the case id reaches the instance that awaits it.** Measured on 199: a release
  (`tier_ack`) posted to `/cases/{case_id}/signals/tier_ack` was forwarded to that case's third
  instance and answered 200 `released`, and the case closed. The case was our own test case, not one of
  yours. You never need an instance id (`{case_id}~{n}`); the case id is enough.
- **A resent event that the case refuses now answers 409, not 502.** See the table below.
- **`GET /cases/{case_id}/action`** for your delegate, as described in our 10-17 packet and repeated below.

## Resending: `POST /ingest/events`, as before

Send each of the four fault events again, with your delegate, exactly as on Friday. Each answer means:

| answer | meaning |
| --- | --- |
| 200, `workflow.started: true` | a new case was opened. Store `workflow.case_id`. That is the id for both links and for the action route. |
| 200, `workflow.started: false` | the event joined a case already **open** on the same episode (asset, item and fault code), as a revision. `workflow.case_id` is that case's id. |
| 409 `{"detail": {"error": "revision_not_kept", "message": ...}}` | the open case refused the revision. Nothing changed. **New in 199**; it was a 502 before. |
| 422 `{"detail": {"error": "payload_refused_by_trigger", "message": ...}}` | the event does not match the trigger's shape. The message names the field. Correct it and resend. |
| 502 `{"detail": {"error": "runner_error"}}`, sometimes with a `message` | our side failed. Retry later and tell us. |

If a Friday case is still open on the same episode, the resend joins it (200, `started: false`) instead of
opening a second case.

## The two link shapes (cortex)

| link | shape | this week |
| --- | --- | --- |
| "Approve in cortex" | `/case/{case_id}?idp=openddil`, with the id URL-encoded | Opens the signed-in person's task on that case. If they hold none, the case is shown read-only. |
| the question panel | `/ask?q=<url-encoded text>&idp=openddil` | **Not this week.** Per our 10-19 packet, point the question panel at `/case/{case_id}?idp=openddil` too. `/ask` follows after the 23rd, in a packet. |

Only these two path shapes are links. `{case_id}` is always `workflow.case_id` from the door, never a
task's `subject_ref` (our 10-18 packet).

## `GET /cases/{case_id}/action`: the schema

**Caller:** your delegate (`svc:openddil`, client credentials). It reads only cases **it seeded**.

**A 200 first appears at release**, not at approval. Approved but not yet released is a 404; a
rejected case never gets a record, so it stays 404.

| status | body | meaning |
| --- | --- | --- |
| 200 | the ActionRecord (below) | settled, so stop polling |
| 404 | `{"detail": {"error": "no_action_record"}}` | a case you seeded, with no record yet |
| 403 | `{"detail": {"error": "not_your_case", "message": "..."}}` | not an id your door was given: no such case, another delegate's case, or a case with no seeder (one identical body for all three). Log it; don't retry. |
| 503 | `{"detail": {"error": "runner_unavailable"}}` or `{"detail": {"error": "artifact_store_unavailable"}}` | retry on the next tick |

**The 200 body** is the stored ActionRecord verbatim at the top level:

```json
{
  "action_id": "<the release instance id>",
  "event_id": "...", "asset_id": "...", "owning_tier": "...", "label": {"...": "..."},
  "work_order": {"option": "<chosen verb>", "readiness": "...", "task": "...",
                 "task_refs": ["..."], "parts": ["..."], "outcome": "approved"},
  "approval_chain": [
    {"step": "...", "role": "...", "approver_sub": "...", "decision": "approved",
     "decided_at": "...", "decision_record_ref": "...", "acted_via": "<only if a delegate acted>"}
  ],
  "provenance": {"case_definition": "...", "case_id": "...", "emitted_by": "maint_release",
                 "workflow_definition_id": "maint_release", "workflow_definition_version": "...",
                 "workflow_instance_id": "...",
                 "manual_nodes_consulted": ["<dmc>", "..."]}
}
```

It also carries these additive keys. A key that the record already has is never overwritten:

| key | content |
| --- | --- |
| `case_id` | the `{case_id}` you asked for |
| `artifact_id` | the stored record's id |
| `acts` | `chose`, then one `approved` per approved chain entry, then `released`; each `{act, who, at, ...}`. An act that was not recorded is absent, never filled in. |
| `dmcs_cited` | `provenance.manual_nodes_consulted`, de-duplicated, in order |
| `action_ids` | only when a case holds more than one record, oldest first; the newest is the one answered |

## What we will send back

Once your four arrive, we will tell you each one's `case_id` as we see it and its stage. As each is
released, we will also confirm that your delegate's `GET /cases/{case_id}/action` answers 200 for it.
