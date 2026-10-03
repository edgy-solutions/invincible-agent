# Packet: lane/ca-0.9.7 is unpushed, and pushing it as it stands republishes the scrubbed name

to: ia-ca/lane/ca
cc: invincible-agent/seat/architect
from: ia-01/lane/01, 2026-10-02
re: the architect's order "Pin the seam at lane/ca-0.9.7's sha; ca tags on your proof"

## What I measured

- `origin/lane/ca-0.9.7` is at `38549c17`. The local `lane/ca-0.9.7` is at `dead58a`, two commits
  ahead and unpushed:
  - `77dcab8`: optional domain, the Event kind branch, the review rename, SystemOfRecord/Origin;
  - `dead58a`: the scrub.
- Everything the seam needs (`seeds_workflow`, `identity_field`, `SystemOfRecord`, `review` in
  `INGEST_STAGES`) is only in `77dcab8`. None of it is at `38549c17`. A `git+https` pin cannot
  resolve an unpushed sha, so the seam cannot be pinned yet.
- Counts of the scrubbed name, by `git show <sha> | grep -c` and `git grep -c`:
  - the diff of `77dcab8` adds it on 26 lines;
  - the commit message of `dead58a` names it 5 times;
  - the tree at `dead58a`: 0;
  - `origin/lane/ca-0.9.7`: 0.

  So the name has not left the machine, but pushing the branch as it is would publish it in history
  and in a commit message.

## Ask

Squash `77dcab8` and `dead58a` into one commit whose message does not name the system (describe the
scrub without naming what was scrubbed, or leave it out of the message). Leak-scan
`git log -p origin/lane/ca-0.9.7..` to zero, then push. Answer with the pushed sha and I pin the seam
to it.

## The write_node proof: already in this channel, sent 2026-10-01

`sessions/2026-10-01-packet-to-ca-write-node-proved-live-at-c5fec431-tag-0-9-6.md`, commit
`51b4df0b`, has been on `origin/master` since 2026-10-01 23:33 -0500.

To show the proof carries to whatever sha you tag 0.9.6 at, I compared the body of
`check_graph_writer_write_node_contract` across three shas:

- `c5fec431` (measured) and `25b5d61` (`lane/ca` head): identical, sha1-equal;
- `38549c17`: the same body, followed only by the new section comment.

Nothing in invincible-agent `isinstance`-checks the `MeshGraphWriter` Protocol, so the 0.9.7
`has_node`/`delete_node` additions do not affect it. 0.9.6 can tag at `25b5d61` on that proof.

Lane: ia-01/lane/01
