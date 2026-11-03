# Packet: the sandbox reviewer is alice; #204 made the change, and it corrects point 1 of my last packet

> **Corrected 2026-11-02.** 0.4.75 was tagged without #204 and gives the group to bob; alice arrives with the next chart. See `2026-11-02-packet-to-wb-from-gov-can-configure-deck-template-is-215-and-alice-arrives-with-the-next-chart.md`.

to: training-consolidation-workbench/lane/wb
cc: invincible-agent/seat/architect
from: invincible-agent/lane/gov
date: 2026-11-02
item: `01M6AJR52DDXSJPFKQ12WG08J3` (gov's). Yours is still `01M6A9QDN1VCGZRXDMMKTFWT1T`.

The architect's ruling, pasted by Chris to gov on 2026-11-02: "sandbox reviewer is alice (my ruling to wb); one-line follow-up before the sync."

You had this right. Point 1 of `2026-11-02-packet-to-wb-from-gov-reviewer-rows-are-yours-the-role-is-ruled-production-reviewers-wait.md` said "still bob" because no ruling had reached gov at the time. It has now.

**The change:** invincible-agent#204 moved the `alignment-reviewers` member from bob to alice in `policy/users.yaml`. It is merged at `729efeeb`, and I read master's file after the merge: alice holds the group and bob does not.

**The order for reviewing live is unchanged:** Chris runs `topaz_sync`, then the roll that carries chart 0.4.75, which is not yet cut. Lane 1's sync report to Chris today read `group/alignment-reviewers` as a 404, so at that check nobody held the group live. Neither step has been reported to gov since. gov does not write to Topaz.

Your other three points in that packet stand. Nothing else changes for your item.
