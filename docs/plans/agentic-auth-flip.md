---
id:         agentic-auth-flip
status:     open
owner:      agent
blocked-on: transport-flip, which is itself open/agent (2 decodes + 2 sweeps). Nothing is awaited from the human until that lands; the flip act is then theirs.
closed-by:
repo:       invincible-agent
summary:    ENABLE_AGENTIC_AUTH — the CONTENT-authz flip. Turns three Topaz asks on at once and deletes the fallbacks. Downstream of the transport flip.
---

# `ENABLE_AGENTIC_AUTH` — the content-authz flip

**Split out 2026-08-10.** This item was invisible: one board line carried a `transport-flip` id
and summary while pointing at a packet largely written for *this* flag. So the board said nothing
about an irreversible content-authz change still being owed — **two items in one home, on the
highest-stakes line**, which is the inverse of the two-homes defect and just as costly.

The detailed history, the corrected enforcement-point census, and the `core/authz.py` retirement
live in [`enable-agentic-auth-flip-packet.md`](enable-agentic-auth-flip-packet.md). This packet
is the board's handle on the flip itself.

## What this flag does

Governs **three data-plane Topaz asks**, all at once by design:

| site | ask |
|---|---|
| `datahub_wrapper/main.py` | `query_metadata` → `can_view` |
| `weaviate_expert/service.py` | per-chunk `can_read` before synthesis |
| `neo4j_expert/service.py` | per-result `can_read` (`_can_read_document`) |

One flag over three points is deliberate: the system can never occupy a **partial enforcement
state** — catalog asked but chunks unfiltered — which is the multiple-heads configuration
ADR-0025 exists to kill.

## Why it is downstream of the transport flip, in one sentence

`can_view` / `can_read` answers are **only as trustworthy as the identity they are asked about**,
and until `REQUIRE_TRANSPORT_AUTH` is REQUIRE the caller identity is unverified — so enforcing
content authorization first would be authorizing on an unauthenticated subject, which produces
real, logged, auditable and meaningless decisions.

The flip packet states this at line 97: *"the two flips are independent and ordered."* **That
ordering was prose in a packet and is now each item's `blocked-on`** — which is the whole reason
this split exists. Burying an ordering dependency in a paragraph is how the second flip stayed
invisible for the length of the arc.

## Why it is the irreversible one

The transport flip is a posture change on a credential check; a caller that breaks gets a 401 and
the fix is to mint. **This flip turns content gates on and retires the fallbacks that made their
absence survivable.** Rolling it back does not restore the fallbacks — they are deleted in the
same arc, per *coupled interim mechanisms retire together*. Treat it accordingly.

## Preconditions

1. `REQUIRE_TRANSPORT_AUTH` is REQUIRE and the fleet is stable under it.
2. ITEM 0 of the flip packet: adjudicate the gating manifest against the code — every listed
   enforcement point verified live, every expected endpoint checked for a gate at all.
3. The DA read-path convergence (lock 2), verified against the **work** realm's claim shape —
   see `work-deploy`.

## Not this packet

`REQUIRE_TRANSPORT_AUTH` — see `enable-agentic-auth-flip-packet.md`, whose `id` is
`transport-flip` and whose blocker is the unminted-caller enumeration.
