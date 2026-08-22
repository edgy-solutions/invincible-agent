---
id:         prime-ingest-timeout-shorter-than-its-own-queue
status:     closed
owner:      unassigned
blocked-on:
closed-by:  6a8e918
code-site:  helm/invincible-agent/values.yaml, helm/invincible-agent/templates/prime-substrate-job.yaml
repo:       invincible-agent
summary:    CLOSED 2026-08-22 by 6a8e918 (ingestTimeout 1800->3600, HELM_TIMEOUT 40m->75m, both bounds moved because raising the inner alone makes helm the binding constraint) plus tests/test_prime_timeout_bounds_agree.py. WITNESSED: the next prime ran 15 ok / 0 failed / 0 unfinished in ~2760s — inside the new bound, and past where the old one died at ingest ~10. Originally: MEASURED 2026-08-22 by a real helm-driven prime. `primeSubstrate.ingestTimeout` is 1800s; the prime launches 15 ontology ingests and dagster's `max_concurrent_runs` is 2, so they SERIALISE into ~8 batches. Ten finished inside the window, five did not — `mesh_system` (which carries every archetype class) among them. The prime then REFUSED to report success, which is the 9e31ae8 fix behaving exactly as designed: `reregister` never ran and no engine restarted against a partial class graph. Substrate left undamaged at its before-numbers (29 classes / 44 rows). The timeout is not tuned to the queue it waits on, and the two numbers have never been compared.
---

# The prime waits 1800s for a queue that cannot drain in 1800s

The first helm-driven prime since the `--wait-for-ingest` fix landed. It failed, and the
failure is two separate things that must not be confused:

- **the fix worked** — it waited, found the graph incomplete, and refused;
- **the configuration is wrong** — the wait it was given cannot cover the work it waits on.

## Measured

```
--- Waiting for 15 ingest run(s) ---
  [SUCCESS] × 10
  [TIMEOUT] product_structure_extension     still running after 1800s
  [TIMEOUT] qualification_status_vocabulary still running after 1800s
  [TIMEOUT] idp_extension                   still running after 1800s
  [TIMEOUT] mfg_extension                   still running after 1800s
  [TIMEOUT] mesh_system                     still running after 1800s
--- Ingest: 10 ok, 0 failed, 5 unfinished ---
[ERROR] ontology ingest did not complete cleanly; refusing to report success.
```

**Zero failed.** Nothing was broken; five runs simply had not been reached yet.

```
QueuedRunCoordinatorDaemon: 2 runs are currently in progress. Maximum is 2, won't launch more.
```

## The arithmetic nobody had done

| quantity | value | where it lives |
|---|---|---|
| ingests launched by one prime | **15** | `prime_databases.py` partition set |
| dagster `max_concurrent_runs` | **2** | dagster instance config |
| ⇒ serialised batches | **8** | neither file knows about the other |
| observed throughput | 10 runs / 1800s ≈ **6 min per run-slot** | this run |
| ⇒ time for all 15 | **≈ 45 min** | |
| `primeSubstrate.ingestTimeout` | **1800s (30 min)** | `values.yaml` |

The timeout is roughly **two thirds** of the work it is waiting for. It was not chosen wrong so
much as chosen *independently* — it is a duration, and the thing it bounds is a queue, and the
two have never been compared to each other.

`scripts/upgrade-sandbox.sh` already knows the chain is slow — it sets `HELM_TIMEOUT=40m` and
says "a full chain has been observed past 30 minutes." That knowledge stopped at the helm
timeout and never reached the INGEST timeout nested inside it. **The outer bound was widened
and the inner one was not**, so the inner one is now the binding constraint and the outer
generosity buys nothing.

## What the fix bought, stated plainly

This is the first live exercise of `9e31ae8` (+ `6f7f217`) and it is a **refusal**, which is the
harder half to witness. Under the previous behaviour this same run would have reported
"Prime complete" at the `[LAUNCHED]` lines — about 47 seconds in — `reregister` would have
restarted the engines, engine-f would have registered presentation triples against archetype
classes that did not exist, and Contract D would have refused them silently. That is the
2026-08-21 defect verbatim, and it did not happen.

Substrate after the failure: **29 `mesh#` classes, 44 `Predicate` rows** — identical to the
pre-run baseline. A failed prime left nothing half-written.

## Disposal — pick one, do not do both blindly

1. **Raise `ingestTimeout` to cover the queue.** ≥ 3600s, with `HELM_TIMEOUT` above it. Cheapest,
   and honest about the sandbox being slow. The number should be *derived from* the batch count
   rather than picked, and the derivation written next to it.
2. **Raise dagster's `max_concurrent_runs`.** Faster wall-clock, but the arm64 sandbox is
   resource-bound and 15 concurrent ontology ingests may simply trade a timeout for an OOM.
   Measure before choosing.
3. **Make the prime compute its own bound** — `batches × observed_per_run × margin` — so the two
   numbers can never drift apart again. The correct fix, and the largest.

**Do not** lower the ingest count or split the prime to fit the timeout: that reintroduces
partial-graph priming through the front door.

## Acceptance

A helm-driven prime that reports `Ingest: 15 ok, 0 failed, 0 unfinished`, followed by
`reregister` running and `scripts/probes/baseline.sh` showing ~~49 classes / 48 rows~~, zero
refusals. Both numbers, one command, after the chain — not during it.

**MET 2026-08-22, at different numbers than written, and the difference is honest.** The run
reported `Ingest: 15 ok, 0 failed, 0 unfinished` in ~2760s; `ontologySeed` and `reregister` both
completed (the first unbroken chain in the arc); the probe read **51 classes / 52 rows, zero
refusals, 52/52 marked**. The acceptance was written when the model had 49 classes and 48
expected rows; two more subject classes and four more archetypes were declared between filing
and closing. The *shape* of the acceptance held exactly — the numbers moved because the model
grew, which is the right reason for an acceptance figure to be stale.
