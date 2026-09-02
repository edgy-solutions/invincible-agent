---
id:         sdk-blocking-sync-handlers
status:     closed
owner:      human
blocked-on: 
closed-by:  iagent-mesh-sdk e6b6757 (v0.4.0) — sync handlers run on a worker thread via anyio.to_thread.run_sync under an explicit contextvars.copy_context(); the quickstart's promise was made TRUE rather than corrected away. BOTH RULINGS ANSWERED BY ENUMERATION: the census this item demanded found ZERO MeshTool.execute() handlers in invincible-agent (zero MeshTool call sites at all), so the population holding retroactively-broken sync handlers was EMPTY — fix the code, no migration debt, nobody to audit. Landed TOGETHER with [[sdk-discards-caller-identity]]'s SDK half in one change to route_handler, so the run_in_executor composition hazard never had a window.
code-site:  iagent_mesh/core.py:438, docs/jupyter_guide.md
repo:       iagent-mesh-sdk
summary:    AVAILABILITY BUG WEARING A DOC CLAIM. MeshTool runs synchronous handlers DIRECTLY on the event loop — no threadpool — while the quickstart tells authors to prefer sync `def` for Polars work because "we will execute it safely in a background thread." There is no background thread. A recommended handler doing df.collect() blocks the whole tool server. The doc did not describe the code; it described an intention, and authors have been coding against the intention.
---

# The quickstart promises a background thread that does not exist

> ## RESOLVED — iagent-mesh-sdk v0.4.0 (`e6b6757`)
>
> **NOT YET PUSHED OR PUBLISHED.** The tag is local to the SDK working tree; the fleet still
> consumes `v0.3.1`. This item is closed against the SDK's `master`, not against anything
> deployed. See the wake-condition note at the foot of this file.
>
> **Ruling 1 — fix the code, not the doc.** `anyio.to_thread.run_sync`, with the request
> context copied explicitly via `contextvars.copy_context()`. The doc's promise is now true.
>
> **Ruling 2 — the count, which decided ruling 1.** The enumeration this item required found
> **zero** `MeshTool.execute()` handlers across invincible-agent — in fact zero `MeshTool`
> call sites at all. The population that "currently holds broken code" was empty, so the
> blast-radius question the ruling turned on had no blast radius. The five in-repo SDK
> templates all use the unchanged single-parameter form. **Nobody needed auditing, and that
> was established rather than assumed.**
>
> **Coordination honoured.** Landed in the SAME change as
> [[sdk-discards-caller-identity]]'s SDK half — one edit to `route_handler`, not two. The
> `run_in_executor` trap this item named never had a window to occur, and
> `test_THE_COORDINATION_TEST_contextvar_survives_into_the_threaded_sync_handler` is the
> standing proof: it passes only when the threading mechanism copies context. Verified by
> substituting `loop.run_in_executor`, which passes every other threading test while losing
> the caller.
>
> **Acceptance, each sealed:**
>
> | criterion | seal |
> |---|---|
> | a multi-second `collect()` does not delay a concurrent request | `test_a_blocking_sync_handler_does_not_delay_a_concurrent_request` |
> | quickstart claim and code agree | `docs/jupyter_guide.md` updated; code threads |
> | a `ContextVar` set by the auth dependency is readable in a sync handler | `test_THE_COORDINATION_TEST_...` |
> | the count of affected deployed handlers is known, not estimated | zero, by enumeration |
>
> A false green was caught while sealing this: the concurrency test originally passed **with
> the defect present**, because its clock started after the stall had already ended. Fixed,
> then confirmed to fail against the unthreaded path.


**Found 2026-08-27**, while checking whether a `ContextVar` would survive into a sync handler
for [[sdk-discards-caller-identity]]. The threading question had a prior: *does the SDK thread
sync handlers at all?* It does not.

## The evidence

`iagent_mesh/core.py:438`:

```python
if inspect.iscoroutinefunction(func):
    return await func(input_data)
return func(input_data)          # <- no threadpool, no to_thread
```

`docs/jupyter_guide.md`, under "Platform Pro-Tip":

> **Use standard `def` (Recommended):** If you are crunching Polars DataFrames
> (`df.collect()`), stick to standard `def`. **We will execute it safely in a background
> thread.**

`grep -rn "run_in_threadpool\|to_thread\|run_in_executor" iagent_mesh/*.py` returns nothing.

## Why this is worse than an ordinary bug

**The doc did not merely fail to describe the code — it recommended the failing path for the
heaviest workload.** An author crunching Polars is exactly the one told to use sync `def`, and
exactly the one whose handler will hold the event loop for the duration of a `collect()`. Every
other request to that tool — including its health probes — waits.

And the population is self-selected for harm: authors who read the guidance and complied are
worse off than authors who ignored it.

**This is the shape where the record is the only guard.** Nothing fails at the moment the
handler is written. It works in dev with one caller. It degrades under concurrency, as
latency, on a tool that reports healthy — an absence, discovered late, attributable to nothing
in particular.

## What has to be decided, and why not by an agent

**1. Fix the code, or fix the doc?** They are not equivalent.

- *Thread the handlers* (`asyncio.to_thread`) makes the promise true and every existing sync
  handler retroactively correct. It also changes execution semantics for handlers that were
  written — knowingly or not — assuming single-threaded access to module state.
- *Correct the doc* makes existing handlers retroactively wrong and obliges their authors to
  migrate to `async def` or accept blocking.

The choice decides **which population currently holds broken code**, and that is a
blast-radius ruling, not a technical preference.

**2. Who audits the existing handlers, and how many are there?** Neither option can be sized
without a count of deployed tools with sync handlers doing heavy work. Enumerate before
choosing — a remembered list of "the tools we know about" is how the sixth one breaks.

## The coordination constraint — not optional

[[sdk-discards-caller-identity]] changes the **same function**: `MeshTool.execute()`'s
`route_handler`. Its fix puts a `CallerIdentity` in a request-scoped `ContextVar`; this one
changes where the handler runs.

**They interact.** `asyncio.to_thread` copies the context; `loop.run_in_executor` does not. Fix
this one with `run_in_executor` and the contextvar reads `None` inside exactly the handler
style the quickstart recommends — and without that item's fail-closed rule, the read lands on
the service identity, silently, in the most common case.

**Two uncoordinated fixes to one seam is how that function grows a third defect.** Sequence
them, or do them together.

## Acceptance

- A sync handler performing a multi-second `collect()` does not delay a concurrent request to
  the same tool.
- The quickstart's claim and the code agree, whichever way the ruling goes.
- If threaded: a `ContextVar` set by the auth dependency is readable inside a sync handler.
- The count of affected deployed handlers is known, not estimated.

## The ADR-shaped sentence underneath

> **A performance promise in a quickstart is an API contract, because it changes what
> callers write. Documentation that recommends a path is answerable for that path
> working.**

---

## Wake condition — read before treating this as deployed

**Closed in source, present nowhere downstream.** `v0.4.0` (`09d7326`) exists only in the SDK
working tree: not pushed, not tagged on `origin`, not on PyPI. Every consumer still resolves
`iagent-mesh @ git+...@v0.3.1`.

**So the checkable event is the PIN BUMP, not the tag.** The deployment surface is the 13
`pyproject.toml` files (plus their `uv.lock` entries) that pin `v0.3.1`. Until those move, a
deployed engine's `MeshTool` still runs sync handlers on the event loop.

This file will be updated again when the SDK is pushed and published — that is the event worth
recording, and it has not happened.
