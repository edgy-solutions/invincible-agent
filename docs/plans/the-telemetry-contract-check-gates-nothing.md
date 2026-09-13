---
id:         the-telemetry-contract-check-gates-nothing
status:     open
owner:      unassigned
blocked-on:
closed-by:
repo:       invincible-agent
summary:    build-containers.yml has ZERO `needs:`, so `build` and `lint` run in parallel. The ADR-0038 telemetry mapping truth-check is a STEP IN LINT — it runs, it reports honestly, and it gates nothing: a red mapping produces a failed lint job beside a successful build job, and the image ships. doc-tools solved the same problem with `build-and-push: needs: telemetry-contract`. Fix is a decision about CI critical path, not a defect repair.
---

# The telemetry contract check runs, reports, and gates nothing

**Found 2026-09-12 while sweeping for a class `doc-tools-7f` had reported and then retracted.**

    $ grep -c 'needs:' .github/workflows/build-containers.yml
    0

**`build` (line 22) and `lint` (line 480) are independent jobs.** The ADR-0038 telemetry mapping
truth-check is a step inside `lint`, and its own comment states the stake:

> *a dangling or unmapped field fails here, before it silently emits nothing to Langfuse.*

**"Before" is exactly what is not true.** It fails *beside*, not before.

## The comparison that makes it clear it is a defect rather than a preference

| | where the check runs | what a RED does |
|---|---|---|
| doc-tools | `telemetry-contract` job | `build-and-push` declares `needs:` it — **the image is never built** |
| invincible-agent | a step in `lint` | `build` is unaffected — **the image is pushed and rollable** |

Both repos independently arrived at the same instrument: a fast pre-build check that
`pip install`s just the leaf plus `pydantic`/`pyyaml` and runs in seconds. **Only one of them wired
it to anything.**

## Why this is the guard-that-cannot-fire family, in an unusual costume

The familiar forms are dark: born dead, orphaned, shadowed, weakened. **This one is loud.** It runs
on every push, reports honestly, and goes red when it should — **to an audience with no power to
act on it before the artifact ships.** A reader seeing the red has already been overtaken by the
image.

**It is also the shape that most resembles working.** A failed check in a run that also produced an
image reads as "something needs fixing", not as "the thing this was built to prevent has already
happened".

## The fix is a decision, not a repair

Adding `needs:` to a **15-service build matrix** changes the critical path of every push: the
matrix currently starts immediately and would instead wait on lint. That is a real cost and it is
the architect's call, not a bug fix to slip in.

**Three options, and the middle one is probably right:**

1. `build: needs: [lint]` — strongest, slowest. Every push pays lint's latency before any image.
2. **Split the telemetry check out of `lint` into its own tiny job and make `build` need THAT.**
   It installs one dependency and runs in seconds, so the added latency is small — this is exactly
   doc-tools' shape, and it is their shape *because* the check is cheap.
3. Leave it and accept that the check is advisory. **Then say so in the comment**, because the
   comment currently claims "before" and that claim is false.

**Option 3 is only acceptable if the comment changes.** A guard that documents itself as blocking
while running in parallel is worse than an honest advisory check, because the next person reads the
comment and stops looking.

## Definition of done

* A red telemetry mapping truth-check **prevents an image from being pushed**, verified by
  mutation: break `telemetry-mapping.yaml`, push a branch, confirm no image appears.
* Or, if option 3: the step's comment says **advisory** and names what does gate the image.
