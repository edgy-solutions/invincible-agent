to: invincible-agent/lane/gov
from: invincible-agent/lane/gov
date: 2026-11-08
re: the 503-seal dispatch: where each of its three items stands
supersedes: 2026-11-08-handoff-lane-gov-the-lifecycle-dispatch-is-314-7f-packets-are-next.md

## Next step

Read CI on #322 (head `229f1505`). If it is red, fix it on `lane/gov-503-seal-by-form` in `C:\Users\cnogr\git\wt\gov\503-seal-by-form`. If it is green, it waits for the merger. Then check for the v0.9.17 tag:

`git -C C:/Users/cnogr/git/iagent-mesh-sdk ls-remote --tags origin 'v0.9.1*'`

## The dispatch, verbatim

"gov: 503 seal finds routes by what they call, not a fixed list (74's packet); "Answer 7f's 10-29/10-30 packets" item; v0.9.17 pin PR when ca tags it (nine-field ImpactRow)."

## Item 1: the seal is #322, open

- Seals derive their sites. Measurements are in the PR body and the architect packet.
- The PR carries one behaviour change: a defect on `/notice_parts` is now a 500. The architect is asked to approve it.
- Control run against #315 at `df74c406`: green with the catch, both seals red without it, for the right reasons. A merge of the two was clean at that sha.
- When #322 merges, remove the worktree: `git cherry origin/master <head>` shows no `+`, status is clean, `is-ancestor` holds.

## Item 2: 7f is answered, two questions open

- Packet to 7f and packet to the architect are placed untracked in the master tree's `sessions/`, both dated 2026-11-08.
- Board item `01M6A9QDN1QSSWQ74F6JV74W0B` is `blocked` on the architect's answers. That change rides #322.
- When the architect answers Q1 (the `EvidenceRef` bbox rule): if 10-31 stands, tell 7f to re-take its pin. If 10-28 stands, ca must drop the SDK default first.
- When the architect answers Q2 (who fills the kind rows): if gov, it is one PR on `policy/overlays/openddil-lab/content_kinds/`, using 7f's 10-30 table in doc-tools `sessions/`.

## Item 3: v0.9.17 pin PR, not started

ca had not tagged it at 2026-11-08 (newest is v0.9.16). Lane 1's pin procedure and the `chris:rule who moves the iagent-mesh pin` board row for v0.9.16 are the precedent to read first.
