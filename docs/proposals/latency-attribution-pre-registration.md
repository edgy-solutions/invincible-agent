# Pre-registration: where the six minutes lives

**Filed 2026-08-24, BEFORE any phase timing was collected.** The hardened-renderer build was
authorized for CORRECTNESS and DETERMINISM. It is now also suspected of being the LATENCY fix.
That suspicion has to be registered before it is tested, or "we fixed it" becomes unfalsifiable
after the fact.

## The measured baseline

Per-question wall clock through the real UI path (`POST /interview/stream` → Dagster
`supervisor_query_job` → engines → presentation), harvested 2026-08-24 from 12 completed
questions:

    median 6.9 min      clean cluster 303–416 s      min 303 s
    (the 2679 s / 2751 s samples span the token-expiry run and are NOT question times)

Routing owns **~7 s** of that (funnel B, measured directly at n=3, median 7.2 s p90 10.8 s).
**Over five minutes per question is unattributed.**

## The named suspect

Every planning answer currently costs a **full generative LLM render**: no hardened renderer
exists for `INTERVAL_TIMELINE` / `PERIOD_SERIES` / `THRESHOLD_GRID` / `MATRIX_GRID` /
`DELTA_SET`, so `_render_archetype_hardened` returns `handled=False` and the request falls to
`b.DesignUI()`. Measured 2026-08-24: all four planning measures render via
`X-Presentation-Path: fallback-designui`, every one flattened to `CHART_WIDGET`.

The hardened renderers DELETE that call. So one authorized work item is simultaneously the
correctness fix, the determinism fix, and — if this registration holds — most of the latency fix.

## THE PREDICTION (human-registered)

* **`DesignUI`'s render call owns 60–75% of post-routing time.**
* **The hardened path brings per-question wall clock under 2.5 minutes**, with narration
  (the wired number-check) as the residual.

## Falsification branches, named in advance

* **Bulk is Dagster orchestration overhead** → the renderer build remains right for correctness
  and determinism, but the latency work RE-OPENS with a different target. We would want to know
  this BEFORE anyone declares the six minutes solved.
* **Bulk is narration** → same conclusion, different owner.
* **Bulk is DesignUI, but the hardened path lands above 2.5 min** → the direction is confirmed
  and the magnitude is not; residuals get attributed individually.

## How the before/after MUST be measured

**Hold the question set fixed** — the four resolver-verified phrasings, subject confidence
≥0.86:

    "what is scheduled by initiative and phase"   (gantt,  Portfolio 0.96)
    "where are we over budget"                    (curve,  Portfolio 0.86)
    "which sites are overloaded"                  (grid,   Site 0.99)
    "capability maturity by site versus target"   (matrix, Capability 0.97)

**n ≥ 2 per side.** This is not ceremony. `DesignUI` is NONDETERMINISTIC — proven the same day:
`plan_schedule` with 14 rows produced `CHART DATA NOT RENDERABLE — no numeric column` in the UI
and a clean draw minutes later from the same measure. A single-run comparison could catch the
fallback on a lucky draw and understate the fix.

> **The nondeterminism finding applies to measuring the nondeterminism's removal.**

## The sentence this whole packet exists to preserve

> **A beat that worked in rehearsal can fail in the room, with no change anywhere.**

Not a rendering bug — a nondeterministic component on the demo's critical path, in a project
where every count is predicted and every phrasing certified at n≥3, and then the last hop rolls
dice. The gantt's "intermittent failure" was never intermittent. It was a fair coin landing
differently, and both faces have now been observed.
