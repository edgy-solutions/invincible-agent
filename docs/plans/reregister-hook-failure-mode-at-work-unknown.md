---
id:         reregister-hook-failure-mode-at-work-unknown
status:     blocked-on-human
owner:      human
blocked-on: work-cluster read access — AGENTS.md fence clause 3 ("Work-cluster anything is the human's until agents get read credentials there")
closed-by:
code-site:  helm/invincible-agent/templates/engine-reregister-job.yaml
repo:       invincible-agent
summary:    RE-HOMED 2026-08-22 from `registration-boot-order-race`, which closed on its sandbox witnesses. The owed question survives here with its own board line: at WORK on 2026-08-14, engines booted before the ontology ingest landed, took a Contract-D 422, never retried, and recovery was a hand restart — and nobody established WHICH of three ways the re-register hook failed to fire there. The hook is now characterised on SANDBOX in both directions (refuses on a partial graph, opens on a full one), which makes the work-cluster question narrower but does not answer it: the two clusters differ in timing, image lag and Dagster concurrency. Requires a read against work, which is the human's under clause 3.
---

# Which of the three ways did the re-register hook fail at work?

**Origin:** split out of
[`registration-boot-order-race`](registration-boot-order-race.md) when that packet closed on
2026-08-22. It closed because both of its arms were witnessed on the sandbox cluster; **this
question was never in scope for those witnesses** and would have been buried by the closure.

## The question, unchanged

Witnessed at work 2026-08-14: an engine booted before the ontology ingest landed, got a
Contract-D **422**, and never retried — the ruling says 422 is permanent, which is right for a
real contract violation and wrong for *"the graph is not populated yet."* Recovery was a hand
restart. The re-register hook exists precisely to prevent that, and it did not.

**Three ways it could have failed, and nobody has read which:**

1. the hook never ran (not rendered, not scheduled, or gated off in that release);
2. it ran and its sentinel passed early, restarting engines against a still-filling graph;
3. it ran, waited correctly, and the engines still lost the race for another reason.

## What the sandbox work changed — and what it did NOT

The hook is now characterised on **sandbox**, both directions, days apart:

- **refuses** on a partial graph (`Ingest: 10 ok, 0 failed, 5 unfinished` → refused to report
  success; `reregister` never ran);
- **opens** on a full one (`[ready] all 2 sentinels present`, six engines, job SUCCEEDED).

That **narrows** cause 2 considerably: the pre-`6f7f217` single-sentinel form is exactly the
early-pass failure, and it is fixed. It does **not** answer the question, because the two
clusters are not the same instrument:

| | sandbox | work |
|---|---|---|
| image currency | rolled to chart 0.3.40 today | unknown to agents |
| Dagster concurrency | `max_concurrent_runs: 2`, ~46 min for 15 ingests | unknown |
| what ran on 2026-08-14 | — | the release in place then, not today's chart |

A conclusion transferred from sandbox to work without a read is exactly the stamp-axis error
this repo keeps paying for: a result carries the environment it was measured in.

## What answering it needs

A read of the **work** cluster around the 2026-08-14 event: whether an
`engine-reregister` Job object exists for that release, its logs if so, and the chart version
deployed at the time. All read-only.

**Blocked under fence clause 3** — *"Work-cluster anything is the human's until agents get read
credentials there… the fence is literal, not a permission judgment."* Revisit when agents get
read creds on work.

## Why this is its own packet rather than a line in the closure

The parent packet's claim — *the hook runs, both arms, verified* — is TRUE and complete for the
substrate it was verified on. Leaving an unanswered work-cluster question inside a closed packet
would make the closure read as broader than it is, and would hide the question from the board.
Re-homed rather than dropped: same question, its own line, its own fence.
