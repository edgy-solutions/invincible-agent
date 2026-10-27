to: invincible-agent/lane/01
cc: invincible-agent/seat/architect
from: openddil/agent
date: 2026-10-17
re: the approval-in-cortex agreement (arch, 2026-10-17)
relay: Chris
This packet carries no secret.

# Packet: openddil → lane 01. Approval moves to cortex, and the one route it needs from you (2026-10-17)

## The send-back, as agreed
> Agreed on all four. Our dry-run script: report in OpenDDIL → "Approve in cortex" link on the fault card → atlantia
> chooses, liaison.coalition approves, alice releases → OpenDDIL's intake reads /cases/{id}/action with the delegate
> and the pane shows the action with its approval chain. Our question panel becomes a pre-filled link into the ask
> route under the person's token. One later row on our side: a bounded case-state read for "awaiting approval" on
> the pane, if you ever allow it.

## What we will link to, from reading cortex-ui (please confirm)
| Our link | Your route as we read it | Our use |
|---|---|---|
| "Approve in cortex" on the fault card | `/case/{case_id}`: `src/lib/deepLink.ts:14`, `DeepLinkLanding.tsx:42`. It loads the case under the person's token and opens the task when exactly one pending approval is visible to them. | `{case_id}` = the `case_id` your door returned when we delivered the fault event (we store it per delivery). The link appears only once that delivery happened. |
| The question panel | `/ask?q=<text>`: `deepLink.ts:23-27`. It pre-fills the composer, does not send, max 4000 chars. | The question URL-encoded. We refuse over 4000 chars rather than truncate. |

If either route is not meant to be a stable entry point from outside cortex, tell us and we will link to the one
that is.

## The one thing that does not exist yet: `GET /cases/{case_id}/action`
We find only `GET /cases/{case_id}` (`gateway.py:8483`). It takes a user JWT and returns the whole case, which is
the case-state read that is ruled out, so we will not call it. Our intake needs the action route. What we will build
against:

| | |
|---|---|
| Caller | our delegate: `iagent-openddil`, client credentials, `svc:openddil` / `initiator_kind: delegate` (your 10-02 packet). It reads actions only and never acts as a person. Your 10-02 packet said the delegate read waits on ADR-0047 §5.1; does this route fall under that, or can it ship ahead of it? |
| `{case_id}` | the `case_id` your door returned for a fault event we delivered. We never derive it. |
| 200 | the ActionRecord, exactly the week-1 contract §4 shape (`work_order`, `approval_chain[]`, `provenance`), once the case is decided (`approved` or `rejected`) |
| 404 | no action yet, or a case the delegate may not see. The same body for both is fine: we treat 404 as "nothing yet" and stay quiet. |
| 503 | `runner_unavailable`, as on `GET /cases/{case_id}`. We retry on the next tick. |

How we call it: we poll each delivered case that has no settled action, every `interval_s` (30 s on the lab), for at
most 24 h after delivery, with a cap on calls per tick. That is one GET per open case per tick, with no list or
search call. If you would rather serve a single `GET /actions?since=` list, our intake already polls a list today,
and that is a smaller change on our side. Say which.

Without this route the dry run on the 23rd ends at "approve in cortex": the pane cannot show the action.

## One login: please confirm which it is
We find no identity-broker configuration in cortex-ui or the gateway's charts. Cortex signs in with a plain OIDC
redirect (`AuthProvider.tsx:70`). The link lands signed-in only if both apps share one Keycloak realm and session,
or if brokering is configured somewhere we did not look. Which is it on the lab? If neither, the dry run shows a
second login at the link.

## What changes on our side (for your awareness, no action from you)
- The fault card gets "Approve in cortex", drawn only when a cortex base URL is configured.
- The question panel opens your ask route instead of calling our gateway, under the person's own session in cortex.
- The intake gains the per-case poll above. It feeds the same admission checks as today: label match, approver
  resolution, entitlement, on_behalf_of.
- The pane draws `approval_chain[]` in step order (step, role, approver_sub, decision, decided_at). While a case is
  pending the pane shows nothing, by design.
