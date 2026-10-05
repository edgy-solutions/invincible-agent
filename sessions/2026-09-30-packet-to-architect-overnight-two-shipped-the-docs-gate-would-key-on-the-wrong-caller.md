# Packet: overnight, two shipped for roll #8, item 3 measured and needs two rulings

to: invincible-agent/seat/architect
from: ia-74/lane/74, 2026-09-30 00:15 CDT
full report: `C:\Users\cnogr\git\ia-74\sessions\2026-09-29-report-74-overnight-safety-and-docs-two-shipped-and-the-docs-gate-would-key-on-the-wrong-caller.md`

No store writes, no row inserted, no turn fired, nothing on Mesh*. All branches are pushed and merge
cleanly onto `90fabab4`.

## Ready for roll #8

- **1 SAFETY**: `lane/74-overnight-safety-docs` `3ec5b3b0`. Rolls cortex-bff and dagster.
  - The producer carries `review_request`; the census reads the SSE stream, which drops it.
  - The consumer now reads the engine's body on the ordinary path.
  - The e2e seal is written and not fired.
  - The census row stays `drawn` until an SSE event carries the block (cortex's).
- **2 DOCS**: `lane/74-docs-subject-pool` `b4012650`. Rolls engine-o only.
  - Both questions bind their pages and reach `mesh:explain`.
  - 34 arms; mutation 19/19 killed.
  - Also fixed: the executor's graph-scope skip matched the substring "GRAPH".

## Item 3: not built, needs your rulings

A serve-time cell check today would never fire, because `agenticAuth: false`. If it did fire, it
would decide for `svc:supervisor`, because `explain` is not dispatched as the caller. And it would
deny every verb target, because mesh verbs have no object in Topaz. Your calls:

- **(a)** Should `explain` join `_CALLER_IDENTITY_VERBS`?
- **(b)** What decides a verb target: mesh verbs entering the `capability` namespace, or a cell
  check on the verb's serving domain?
- **(c)** Does serve time add to ADR-0037's nomination-time filter, or replace it?

## Correction

The census `drawn` I cited unchecked on 09-29 is now measured: true of the stream, false of the
engine. It is corrected in `9287c4d8` (on `lane/74-acceptance-and-docs-subject`) and in the placed
09-29 packet, under the claim.

## Scan

This packet, the 09-29 packet and the report all parse as `seat` / `architect` under the
seat-aware parser (`8d6ea46d`, on `origin/lane/74`). **Master's `lane_packets` reads all three as
`addressee=None`**, because the seat form is not merged. Until `lane/74` merges, the census cannot
see mail sent to this seat, so an empty census for this seat does not mean there is no mail.
