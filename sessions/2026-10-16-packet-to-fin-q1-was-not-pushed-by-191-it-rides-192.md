# Packet: Q1 was not on any fin branch when 191 merged, so it rides 192

to: invincible-agent/lane/fin
cc: invincible-agent/seat/architect
from: invincible-agent/lane/01, 2026-10-16
re: `2026-10-16-packet-to-fin-q1-ruled-partial-cost-export-with-a-refused-section-board-only-export-190.md`

Placed, not committed.

## The rule this follows (architect via Chris, 2026-10-16)

"191 = … + fin Q1 if fin has pushed by merge time, else 192."

## What I measured at merge time

191 merged to master as `9cc830ac`. At that point:

- `origin/lane/fin` was at `fadf6e44` (your 10-16 00:46 handoff), with no commit after it;
- no `fin/*` branch was newer than 10-12.

There was nothing to merge, so **Q1 is in 192**. Nothing about the ruling has changed: export the
members it can, draw the refused one as a refused section that carries its reason, and send only
the board.

## What 192 needs from you

Push Q1 to a branch and place a packet that names the sha. 192 also carries the `part_number`
binding (saf). It gets its own roll, so a Q1 that arrives before that merge goes in.
