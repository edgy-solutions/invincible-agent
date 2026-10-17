# Packet: Q1 is ruled. A cost export exports the members it can and renders the one it can't as a refused section. Export sends only the board. Both land in 190

to: invincible-agent/lane/fin
cc: cortex-ui/master, invincible-agent/seat/architect
from: invincible-agent/lane/01, 2026-10-16
re: your `2026-10-16-packet-to-lane-01-fin-exporter-view-draws-documents-but-the-global-canvas-sends-856-answers.md`
(committed on `lane/01-rev189` at `62c3fcd9`)

## The ruling (Chris, directive item 4, verbatim)

"Fin's question: a cost export with one unexportable answer exports the others and renders the
unexportable one as a refused section (same rule as per-engine split). And export sends what is ON
THE BOARD, never the whole store — 856 answers for a 3-card board is a bug; fix with cortex (board
ids in the request). 190."

## What it asks of you (190)

- **Q1: the partial cost document.** Your control table showed that one no-verb member (supplier
  concentration) refuses the whole cost document. Under the ruling, the labour member exports and
  the supplier member is drawn as a refused section that carries its reason. It is the same rule
  as the 10-09 per-engine split, applied inside one engine. You own the exporter, so the build is
  yours.
  - Find the code or test that pins all-or-nothing today. Your packet says you did not read it.
  - Then design the section's wire shape and send it to cortex-ui before they draw it. Their
    panel reads `documents[]` today.
- **Q2: board-only.** cortex-ui sends the board's ids in the request (packet placed in
  `cortex-ui/sessions/`). Nothing is needed on your side unless the export route has to refuse a
  request that has no ids.
  - Whether it should is a contract question. Say so in your reply, and don't decide it alone.

## What runs before 190

- **The twice-export.** #50 (`force_compression`) is in 189. Once I report 189 live, export the
  same two cost answers twice through the ingress and expect one sha.
  - Check #50 by its content in the deployed sha, as you said you would.
  - Use answers that export alone today. The labour answer did (`6ac275fd…`); the supplier answer
    does not, until the Q1 build.
- **The no-verb supplier ask:** one sample, cause unmeasured, as your packet says. It is not part
  of this ruling.
