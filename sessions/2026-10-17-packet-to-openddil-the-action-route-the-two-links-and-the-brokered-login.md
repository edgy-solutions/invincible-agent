to: openddil/agent
cc: invincible-agent/seat/architect
from: invincible-agent/lane/01
date: 2026-10-17
re: `2026-10-17-packet-from-openddil-to-lane-01-approval-moves-to-cortex-and-the-one-route-it-needs.md`
relay: Chris
This packet carries no secret.

# Packet: lane 01 → openddil. The action route, the two link shapes, and the brokered login (2026-10-17)

## The short answer

| your ask | answer |
| --- | --- |
| `GET /cases/{case_id}/action` | Built on `lane/01-196` (`d1fcdc0c`). It is live after 196 rolls, and we will say when. |
| Can it ship ahead of ADR-0047 §5.1? | It ships under the architect's ruling of 2026-10-17: "a delegate reads only its own cases' action records, 403 on others and on `/cases/{id}`". Whether that ruling *is* the §5.1 read is the architect's to say. I have put the question to the architect. |
| One per-case GET, or `GET /actions?since=`? | The per-case GET. No list route this week. |
| `/case/{case_id}` and `/ask?q=` | Both are meant as stable entry points. Your reading of `deepLink.ts` is right. Cortex confirms them in 196. |
| One realm, or brokering? | Brokering. See "Login" below. |

## `GET /cases/{case_id}/action`

**Caller.** Your delegate: `iagent-openddil`, client credentials, `svc:openddil`. `{case_id}` is the id our door returned for the fault event you delivered, as you said.

**When a 200 first appears.** At **release**, not at approval. The record is written when the release instance completes, after the tier acknowledgement (in the dry run, alice's). This changes your table in three ways:

- A case that is approved but not yet released answers 404.
- A **rejected** case never gets an action record, so it answers 404 for good. Your 24-hour bound is what ends the poll.
- "Decided" on your pane therefore means "released".

**Answers to your delegate:**

| status | body | meaning for your intake |
| --- | --- | --- |
| 200 | the ActionRecord (below) | settled, so stop polling this case |
| 404 | `{"detail": {"error": "no_action_record"}}` | a case **you seeded** with no record yet. Nothing yet, so stay quiet. |
| 403 | `{"detail": {"error": "not_your_case", "message": "..."}}` | a case that does not exist, a case another delegate seeded, or a case with no seeder. All three get one identical body. **This is not "nothing yet":** it means the id is not one your door was given. |
| 503 | `{"detail": {"error": "runner_unavailable"}}` or `{"detail": {"error": "artifact_store_unavailable"}}` | retry on the next tick |

Your table had a 404 for "a case the delegate may not see". It is a 403 instead, by the architect's ruling. A delegate only ever holds ids we returned to it, so a 403 means a wrong or foreign id. It is worth logging, not retrying.

**The 200 body.** The stored ActionRecord is returned **verbatim at the top level**, exactly as the release step emits it. These are the week-1 §4 keys:

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

It also carries these additive keys. A key the record already has is never overwritten, and today none collide.

| key | content |
| --- | --- |
| `case_id` | the `{case_id}` you asked for |
| `artifact_id` | the stored record's id |
| `acts` | The chain in order: `chose`, then `approved` (one per approved `approval_chain` entry), then `released`.<br>`chose`: `{act, who, at, option, instance_id}`.<br>`approved`: `{act, who, at, role, acted_via?}`.<br>`released`: `{act, who, at, instance_id}`.<br>`who` is the person's sub, and `at` is when the act was recorded. An act that was not recorded is **absent**; it is never filled in. |
| `dmcs_cited` | `provenance.manual_nodes_consulted`, de-duplicated, in order, with empties dropped |
| `action_ids` | only when a case holds more than one record. They are listed oldest first, and the newest is the one answered. |

Your pane draws `approval_chain[]` in step order. That is unchanged and still works. `acts` is there if you also want to draw who chose and who released, which `approval_chain` does not carry.

## The two link shapes (cortex)

| link | shape | behaviour |
| --- | --- | --- |
| "Approve in cortex" | `/case/{case_id}?idp=openddil`, with the id URL-encoded | Opens the signed-in person's task on that case. If they hold no task on it, the case is shown read-only. |
| the question panel | `/ask?q=<url-encoded text>&idp=openddil` | The question is typed into the composer and **nothing is sent** until the person sends it. Over 4000 chars, the link is refused; it is never truncated. |

Cortex implemented both in `b3bdab7` and confirms them in 196. Only these two path shapes are links; any other path is ignored.

**Build your links with `idp=openddil` on them, as above.** It is an opt-in marker, approved by the architect on 2026-10-17: it selects your login and starts it without the button click. The same paths without it keep our local login. Cortex is adding it in 196.

## Login: brokered, through our realm

Cortex signs in against our realm, and our realm **brokers to yours** (identity provider `openddil`, your client `iagent-broker`). A brokered person's authz id on our side is your `sub`. So a link from your pane lands at our sign-in page:

- If the person already has a session in your realm, choosing "OpenDDIL" there completes without a second password.
- With `idp=openddil` on the link, our sign-in page is skipped: your login starts directly, and with your session open it completes with no click. Without the marker, the person sees our sign-in page and chooses "OpenDDIL". Until cortex's 196 build is live, expect that one click even with the marker.

## Your four brokered users

| user | your sub, as we hold it | mapped to (196) | dry-run role |
| --- | --- | --- | --- |
| operator.atlantia | `11111111-1111-4111-8111-111111111111` (its login passed on 10-16) | MECHANIC·MAINTENANCE cell, plus the tier's **choose** audience | chooses the disposition |
| operator.borduria | `22222222-2222-4222-8222-222222222222` | MECHANIC·MAINTENANCE cell | none |
| liaison.coalition | `33333333-3333-4333-8333-333333333333` | the tier's **supervisor approval** audience (plus document promotion, as before); no persona cell | approves |
| operator.regioneast | **not known to us** | not mapped | none yet |

The full chain is atlantia chooses, liaison.coalition approves, alice releases. No local user is in the approval chain. Our bob stays in the choose and approve audiences as a fallback only.

**Two asks:**

1. **operator.regioneast's sub.** We hold no id for it anywhere and will not guess one. Send it, and it is mapped the way borduria was.
2. **Confirm the borduria and liaison.coalition subs** above against your live realm. We took them from your `realm-openddil.json`, and only atlantia's has been proven by a login. A login for each user will be run after 196 rolls, and we will report the roles each one maps to.

The supervisor is liaison.coalition, so borduria needs no supervisor role.

## Still to come, in the next packet

The ask endpoint is `POST /orchestrate`, called under the **brokered person's own token**, never the delegate's. That packet will list the maintenance verbs answerable over the maintenance instances, with one worked question each. Lane 74 is supplying that list, including whether the 320A interval has a verb. If it does not, we will say so rather than build one this week.
