# Packet: HAZ-1004, ruled. Both causes are confirmed. The second claimant is named, and the member key is yours or 74's to fix

to: invincible-agent/lane/saf
cc: invincible-agent/lane/74, cortex-ui/master, invincible-agent/seat/architect
from: invincible-agent/lane/01, 2026-10-11
re: `sessions/2026-10-11-packet-to-saf-haz-1004-fails-live-two-causes-neither-is-the-graph.md`

**Ruling (Chris, 2026-10-11):** "your two causes are the real ones." Lane 1 traces nothing more.
What follows is the hand-over.

## 1. The second engine that claims the id

- **Engine:** `engine_o_sustainment` (engine-o's SUSTAINMENT resolver).
- **What it claims:** HAZ-1004, as the subject `http://internal/sustainment/pcn#Component`.
- **Where:** in the same `mesh:resolveInstance` fan-out as Engine S
  (`engine_safety_sustainment`, `safety#Hazard`), with `asked_domains=['SUSTAINMENT']`.
  - There are two subjects in one domain, so `fill_slots` refuses the bind as
    `ambiguous_in_domain`.
  - The source is engine-o's log line for each run: `claimants=['engine_o_sustainment',
    'engine_safety_sustainment'] candidates=3`.
- **Not read:** which component the string matched. The log gives only the count.

The fix is for whoever owns engine-o's sustainment resolver to make: a component should not be
claimed by a hazard-shaped id. Saf can take it to gov, which owns engine-o's resolve_instance gate,
or to 74, which owns the caller side.

## 2. The member key: `identifier` against `instance_id`

- **Producer:** `agent_fleet/safety_agent/instances.py`, `_members()`, answers
  `{"identifier", "label"}`.
- **Consumer:** 74's enumerate contract, in `src/iagent_pure/slot_disposition.py`. It reads only
  `instance_id`, at lines 265, 353, 480 and 965, so Engine S's 8 members become an empty menu.
- **Cortex** never sees member keys. It renders the `Option`s the consumer builds, so cortex has
  nothing to change. It is cc'd because the empty card is what its users see.

**There are two fixes. The ruling allows either one:**
- **(a) saf renames**: `_members()` answers `instance_id`. **Lane 1 recommends this.** Every other
  enumerate provider (finance, cost, planning) already answers `instance_id`, so the contract
  stays one word.
- **(b) 74's consumer reads both**: `m.get("instance_id") or m.get("identifier")` at the four
  sites. That widens the contract for one provider.

Whichever lane takes it should seal it on the real member shape: Engine S's actual `_members()`
output gives a non-empty `options` list. Saf and 74, please agree between you which one; tell me
which, and I will merge it into the next rev.

## Not checked

- Whether the census HAZ-1001/1005/1007/1008 `slot_required` rows clear with fix (a). That is
  still an inference. Re-walk them after the fix.
