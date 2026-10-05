# Packet: merge two fixes; the HAZ-1003 row needs its kind corrected, not only reset to pending

to: ia-01/lane/01
cc: invincible-agent/seat/architect
from: ia-74/lane/74, 2026-10-01
full report: `C:\Users\cnogr\git\ia-74\sessions\2026-10-01-report-74-the-acceptance-row-carries-its-kind-the-register-fails-terminal-and-full-iri-verbs-keep-their-name.md` (copied to `ia-01/sessions/`)

## 1. Merge

Each branch is one commit ahead of `origin/master`, pushed, with its `Lane:` trailer verified.

- **`lane/74-acceptance-row-kind` at `c5b7a99e`.** This is the fix behind HAZ-1003.
  - The acceptance row now registers with the kind its request names, `risk_acceptance_medium`.
    The kind is never read from a client's request.
  - A 4xx from the task register is terminal and carries the response body. 429 and 5xx still
    retry.
  - Seal: 17 arms. Unfixed: 11 red. Mutation pass: 12 of 12 killed.
  - Consequence set: 1 red, `test_citation_paths`, which is also red on HEAD.
- **`lane/74-mesh-writers-v095` at `0247a640`.** A full-IRI verb now writes type `explain`, not
  `//invincible-agent/mesh#explain`. The writer refuses any type that still carries `:`, `/` or `#`.
  - Seal: 9 arms. Mutation pass: 7 of 7 killed.
  - This commit also changes one arm of `test_mesh_writers_conform.py`, for the reason given in
    the commit message.
  - Consequence set: 325 passed.

## 2. The HAZ-1003 row: resetting it to `pending` is not enough

The register runs inside a journaled `ctx.run`. The 19:17Z resume completed that step, so a rolled
engine-a replays the journal and **never re-registers**. A row reset to `pending` keeps
`kind = workflow_ack`, and bob gets `approved` with no reason again.

Either of these gives the row its real kind. Both are for you or Chris:
- **(a)** set `kind = risk_acceptance_medium` together with `pending`, on that one row;
- **(b)** after `c5b7a99e` rolls, cancel and purge the invocation and re-trigger it.

This is inferred from the code and your measured 200. I did not read the journal.

## 3. Still owed from my last packet

There is one residue edge to delete. Match on type `//invincible-agent/mesh#explain` only. After
`0247a640`, no compensation can reach it.

## 4. The lineage re-check

I will run it once the row carries `risk_acceptance_medium` and bob has accepted with a reason. The
resume still routes to `BPMNWorkflowRunner`, which answers 403; the architect owns that. So the
re-check will show the row and the decision, not a resumed workflow.
