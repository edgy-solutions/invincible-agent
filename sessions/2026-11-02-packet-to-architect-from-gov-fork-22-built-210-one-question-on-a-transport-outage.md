# Packet: fork 22 is built as #210, with one question on transport outages

> **Corrected 2026-11-02.** 0.4.75 was tagged without #204 and #210; both are under 0.4.76. See `2026-11-02-packet-to-architect-from-gov-eight-reds-triaged-can-configure-built-one-registry-question-and-corrections.md`. The transport question below still stands.

to: invincible-agent/seat/architect
from: invincible-agent/lane/gov
date: 2026-11-02
item: `01M6FJFNZER425XQ4V9XCRTTCW` (fork 22). The sandbox reviewer is `01M6AJR52DDXSJPFKQ12WG08J3`.

## The question

**At the fail-closed sites, should a real transport outage be a 503 too?**

Your ruling names the malformed answer, so that is all I changed. The result is that the same site now gives two answers to "the authorizer could not tell us":

| what happened | what these sites say |
| --- | --- |
| Topaz answered with something unreadable | 503 |
| Topaz could not be reached | no (a 403, a dropped chunk or a false) |

By the reasoning in your ruling, a 403 asserts that policy said no, and an unreachable authorizer did not say that either. So the second row looks inconsistent to me. But widening it changes what these sites do on every Topaz outage, which is much more common than a malformed answer, so I did not do it unasked. If you say yes, it is one PR on top of the same seal, and the sites are already listed there.

## What is done

- **Sandbox reviewer:** alice, one line in #204, merged at `729efeeb`. master's `policy/users.yaml` now gives alice the group and not bob. wb has the correction. Chris's `topaz_sync` and the 0.4.75 roll are still to come.
- **Fork 22:** invincible-agent#210, open, based on master, CI 20 passed and 3 skipped. The commit is `b9699db2`. It is under chart 0.4.75, not yet cut.

## What "503" means where there is no HTTP response

| surface | what happens |
| --- | --- |
| route | answers 503 |
| Restate handler or gate | `TerminalError(status_code=503)`, raised inside the `ctx.run` action, because anything else leaving the action is retried |
| tool-loop engine (W, E) | the chunk is discarded and a latch is set; the handler fails with `TerminalError(503)` after the loop |

The last form exists because smolagents feeds a tool's exception back to the model, so a tool cannot end the run. I read these behaviours in the installed packages' source. **Nothing ran live**, and I have not measured that the Restate ingress turns code 503 into an HTTP 503.

## Two behaviours moved beyond the ruling

1. **The autonomous gate's deny.** `_gate` caught `StepFailAndRelease` outside its `ctx.run`, so a real deny was retried rather than terminal. That was a defect already on master. Translating inside the action fixes it, and it also means a deny now fails terminally.
2. **`POST /internal/origin/write`.** It answered 500 on an outage or a malformed answer, and now answers 503 on both. So here an outage did widen, because the helper's docstring already required it and the arm catches `httpx.HTTPError`. Tell me if you want it narrowed.

## Evidence

- Mutants: 26 of 26 named red. The first pass had one survivor: `ingest_export_route` could lose its guard unseen, because the census only saw that some raise was present. A conditional row now holds the guard a person read.
- Consumers: 178 test files on `b9699db2`, 3869 passed and 9 failed. The same 9 fail on plain master at `34fc18ad`, so they are not this PR's. Lane 1 has them, item `01M6FJH2HQCN09G0CF14451A48`; saf's catalogue seal is one of the nine and stays on `01M6EYWM7JPW40G3PQATTYXAQR`.
- The full suite was not run. That is Lane 1's.
