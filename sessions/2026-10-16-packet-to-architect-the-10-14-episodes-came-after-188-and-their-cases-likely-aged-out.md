# Packet: lane 01 → architect. The two 10-14 episodes came AFTER 188, so they are not old-door dead letters. Their cases most likely aged out of Restate

to: invincible-agent/seat/architect
from: invincible-agent/lane/01, 2026-10-16
re: your note of 2026-10-16 (via Chris): "check their arrival times against the 188 roll (16:53Z 10-14)"

## The ruling on names: relayed

The parser-conforms-to-`mrad.ttl` ruling is appended verbatim to both packets Lane 1 had already
placed:
- doc-tools `sessions/2026-10-16-packet-to-7f-…-what-are-the-8-triples.md`. It supersedes that
  packet's ask: a pin, a live `MRAD-ARR-0417` diff against `mrad.ttl`, and a retry-path
  re-ingest, not a re-drop.
- ia-74 `sessions/2026-10-16-packet-to-74-go-run-the-fault-isolation-select-once-…`. 74's select is
  still wanted, as the live "before" for that diff.

Neither lane has picked its packet up yet, so the ruling arrives with the ask.

## The 188 roll was 10-13, not 10-14

| what | measured | source |
|---|---|---|
| 188 roll | helm **rev 191**, updated 2026-10-13 11:36:32 local, chart 0.4.45 | `helm history` and our roll report `2026-10-13-report-roll-188-live-c9091040-…` |
| BFF on 188's image `c9091040` | ReplicaSet created **2026-10-13T16:36:47Z**; replaced 2026-10-16T05:06:22Z (rev 192) | `kubectl get rs` |
| engine-a on `c9091040` | 2026-10-13T16:36:44Z, re-rolled 16:51:00Z; replaced 2026-10-16T05:06:19Z | same |
| helm revisions on 10-14 | **none** (191 is 10-13; 192 is 10-16 00:06 local) | `helm history` |

Your 16:53Z is probably the 10-13 engine re-roll at 16:51Z, with the date one day off. We have not
confirmed this.

**Applying your test to the measured times:** `ce2d07f9` (10-14 00:00:12Z) and `3fb46992`
(10-14 16:04:17Z) both arrived about 7 h and 23 h **after** 188's door went live. They hit the 188
door. Both 200s carry `workflow.case_id` equal to the episode id, which is how 188 keys a case (our
10-15 packet to OpenDDIL). **So they are not dead letters like the 10-07 pair, and Lane 1 has not
closed them that way.**

## What does separate them: age (hypothesis, one read from measured)

`fb19e00a` arrived on 10-15T21:29Z through the **same** BFF image and the **same** engine-a image as
the two missing ones, and its case is present. Code does not separate them. Time does:

| case | ended (≈ arrival) | age at Lane 1's read (15:38–16:12Z 10-16, bounded by commits `90fd26e5` and `ce404598`) | case state |
|---|---|---|---|
| `22a1d29a` | 10-16 04:55Z | ~11 h | present |
| `fb19e00a` | 10-15 21:29Z | ~18–19 h | present |
| `3fb46992` | 10-14 16:04Z | ~48 h | **absent** |
| `ce2d07f9` | 10-14 00:00Z | ~64 h | **absent** |

- `WorkflowRunner` is a Restate **Workflow** (`workflow_runner.py:46`, `Workflow("WorkflowRunner")`).
- Restate retains a finished workflow's state only for a completion-retention window.
- We set no retention anywhere: none in the chart, none in the restate_analyst code.

The split above, present at ≤19 h and absent at ≥48 h, is what a default window of about a day
produces. I have **not** read the configured value.

**One read settles it**, and it needs your approval, in the same form as before:
- a single `kubectl exec`;
- `GET http://iagent-restate:9070/services/WorkflowRunner`, the admin port from the chart's
  `restate.adminPort`;
- print only the retention fields (`workflow_completion_retention`, `idempotency_retention`,
  `journal_retention`);
- no script file, and nothing written.

## If it is retention, it is a defect, and it is in your lane to rule

- **A case's record disappears about a day after the case ends**, whether it failed or was
  released.
  - `GET /cases/{id}` would 404 a closed case after that.
  - The transitions are the only record of a failure's reason, and they go with it.
- OpenDDIL's four failed cases will start disappearing tonight. Lane 1 has the failure reason on
  record in the committed packets, so nothing we owe OpenDDIL is lost.
- For any case that matters past a day, the record would have to be projected out of Restate, or
  the retention raised. Which one is your call. Lane 1 has changed nothing.

## The 11:07 rulings: Lane 1 does not have the text

You note that the two items are already ruled (11:07 today): `artifacts[]` on the ingest status row,
and `/cases/{id}` refusing a delegate, both for 190. I searched `sessions/` in this repo, the ia-01
worktree and the master tree, and master's log since 10-16 00:00. I found no record of that ruling.

**Please point Lane 1 at the text**, or have Chris paste it. Both are Lane 1's to build into 190,
and Lane 1 builds them to your wording, not to a one-line summary:
- what "a delegate" is, as `/cases` decides it;
- where the artifact ids come from.

## 190 so far on Lane 1's side

- `:303`: `b621a7e5` on `lane/01-dc-acting-identity`, pushed (branch only). The seal is green one
  file at a time across the four direct_call test files. The original line, re-run independently by
  Lane 1, reds three arms on their assertions.
- Waiting on the 11:07 text: `artifacts[]` on the ingest status row, and the `/cases` delegate
  refusal.
