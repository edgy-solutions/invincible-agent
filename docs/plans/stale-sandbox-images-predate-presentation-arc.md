---
id:         stale-sandbox-images-predate-presentation-arc
status:     open
owner:      unassigned
blocked-on:
closed-by:
code-site:  helm/invincible-agent/values-sandbox.yaml
repo:       invincible-agent
summary:    The sandbox runs pre-arc builds. `iagent-engine-f` started 2026-08-18 and `iagent-cortex-ui` started 2026-08-15; the ENTIRE presentation-SPO arc (slices 2a/2b/2c/4, the frontend_id seam, the union fallback, and every component contract) landed 2026-08-20. Probed 2026-08-21: a planning `output_uri` to `/render_ui` returns `x-presentation-path: fallback-designui` — the OLD LLM path, because the deployed code has no `select_presentation`. CONSEQUENCE: any integration check against sandbox today is testing an architecture that no longer exists in the tree, and would report green or red for reasons unrelated to the code under test. Blocks the portfolio-review plan's Gate 1, which asserts provenance the deployed engine cannot emit.
---

# The sandbox is testing an architecture the tree no longer has

Probed 2026-08-21 while verifying that a planning `output_uri` flows through the presentation
seam. It does not, and the reason is not in the code.

## What was observed

```
POST http://iagent-engine-f:8087/render_ui
  frontend_id  cortex-ui-desktop
  output_uri   http://invincible-agent/mesh#PeriodCostSeries
  raw_data     {"rows":[{"period":"FY26-Q3","total":5050000}]}

HTTP 200
x-presentation-path: fallback-designui
{"components":[{"archetype":"CHART_WIDGET", …}]}
```

`fallback-designui` is the **LLM DesignUI path**. The current tree's `/render_ui` resolves a
caller's registered menu through `select_presentation` and stamps `presentation_source` /
`selection_basis` provenance. None of that ran, because none of it is deployed.

## Why

| workload | pod started | arc landed |
|---|---|---|
| `iagent-engine-f` | 2026-08-18 | slices 2a–2c + 4, `frontend_id` seam, union fallback — all **2026-08-20** |
| `iagent-cortex-ui` | 2026-08-15 | every `.contract.ts`, `assembleCapabilities`, self-naming on stream requests — all **2026-08-20** |

Both images are tagged `:latest`, so the code exists in the registry-facing sense and simply
has not been pulled. The running cortex-ui therefore also does **not** send `frontend_id` and
does **not** register derived contracts, which means the registry engine-f consults is empty
of exactly the rows the arc created.

## Why this is filed rather than fixed tonight

Restarting sandbox workloads is an outward-facing action on a shared environment, and the
`:latest` + `pullPolicy` combination means a rollout re-pulls the whole fleet, not one
deployment — see [[cluster-access-edge-direct]] for that footgun. That is a decision for a
human who is awake, not a convenience taken at 01:00 by an agent that only needed a probe.

## What it blocks, concretely

The portfolio-review plan's **Gate 1 asserts `presentation_source == "registered"` and
`selection_basis == "output_uri+payload"`.** The deployed engine-f emits **neither field** —
it has no `select_presentation`. So Gate 1 cannot be evaluated against sandbox at all until a
redeploy, and an implementer running it today would read the absence as a code failure.

The plan's **unconditional Day-5 eval against the real demo endpoint** has the same exposure
one layer up: it would be checking the provider path and model name against a stack whose
presentation layer is two days behind the tree.

## The general shape, worth naming

This is a **stamp-axis fact** — a property of *where* the code ran, not of what it does —
and it is the same species as
[`suite-unrunnable-on-windows-native`](suite-unrunnable-on-windows-native.md): an environment
silently narrowing what a check can prove, while the check itself reports normally. The probe
returned HTTP 200 with a rendered component. Nothing about the response said "you are talking
to last week."

## Disposal

1. Redeploy `engine-f` and `cortex-ui` from current `master`, then re-run the probe and expect
   `presentation_source` + `selection_basis` in the provenance rather than `fallback-designui`.
2. Re-run the same probe as the **acceptance check** for this packet — a redeploy that does not
   change the observed path did not deploy what was intended.
3. Consider whether a version/commit header on `/render_ui` responses is worth the small cost.
   Every diagnosis in this packet came from correlating pod start times against `git log` by
   hand, which is a step that will be repeated every time this question is asked.
