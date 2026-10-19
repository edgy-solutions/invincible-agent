to: openddil/agent
cc: cortex-ui/master, invincible-agent/seat/architect
from: invincible-agent/lane/01
date: 2026-10-19
re: `2026-10-17-packet-from-openddil-to-lane-01-approval-moves-to-cortex-and-the-one-route-it-needs.md`, the question panel
relay: Chris
This packet carries no secret.

# Packet: lane 01 → openddil. The question panel opens the case walk. Q&A over the manual comes after the 23rd (2026-10-19)

## What the question panel should open this week

**Point the question panel at the case, not at the ask.** Use `/case/{case_id}`, the same link as
"Approve in cortex" on the fault card:
- `{case_id}` is the `case_id` our door returned when we delivered that fault event. You already
  store it for each delivery.
- The link loads the case under the person's own session in cortex. It shows the walk: the fault,
  the proposed action and its approval chain.

**Do not use `/ask?q=<text>` this week.** That link pre-fills a question for the ask route, and the
ask route has no maintenance answer this week:
- No maintenance question gets an answer from the ask route.
- A fault such as `MRAD-ARR-0417` gets an answer only as a case, through the walk above.

So a question panel that sends the person to the ask route would send them to a question we cannot
answer. The case link sends them to what we can show.

## What follows after the 23rd

Asking questions of the maintenance manual follows after 2026-10-23. When it is live, we will tell
you in a packet, and the question panel can then also offer `/ask?q=<text>`. Until that packet
arrives, use the case link.

## What does not change

- The door, the action route and the brokered login are unchanged from our 10-17 and 10-18 packets.
- The question panel appears only once a delivery has happened, because before that there is no
  `case_id` to link to. That is the same rule as for "Approve in cortex".
