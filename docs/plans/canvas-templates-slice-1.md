---
id:         canvas-templates-slice-1
status:     in-flight
owner:      unassigned
blocked-on:
closed-by:
code-site:  policy/canvases/portfolio.yaml, src/iagent/canvas_template.py, scripts/generate_canvas_schema.py, .github/workflows/validate-canvas-templates.yml
repo:       invincible-agent
summary:    ADR-0050 slice 1, NON-GATEWAY HALF — landed 2026-08-23. Ratified `policy/canvases/portfolio.yaml` (five panels, verbs read off the seeder's own `measure` field, slots declared as the verbs' REAL signature defaults since §3's carry is blocked), Pydantic models + generated JSON Schema + drift test with positive control, and a merge-gating CI job. Seal 3 recorded FAILING against today's phrase seed — structurally, from source, so it cannot be a lucky pass. GATEWAY HALF IS NOT MINE and is not here: `seedCanvas(template_id)`, `_CALLER_IDENTITY_VERBS`, and the superseded Ruling (a) seal. THREE THINGS OWED, named below rather than implied: verb-EXISTENCE checking (seal 1's other half), the live seal-3 run (~50 min, needs a quiet substrate), and the cortex `TEMPLATES` row §7 requires before the backend advertises a second template.
---

# Canvas templates, slice 1 — the non-gateway half

Decisions live in
[ADR-0050](../adr/ADR-0050-canvas-templates-are-ratified-yaml-a-panel-is-a-pre-resolved-step.md).
This packet is what landed, what did not, and what is owed.

## What landed

| piece | where | note |
|---|---|---|
| the ratified template | `policy/canvases/portfolio.yaml` | five panels, `role` + ordinal only (§7) |
| the models | `src/iagent/canvas_template.py` | pure; `template_ref` per §1.5 |
| the generator | `scripts/generate_canvas_schema.py` | `--check` / `--validate`, help-safe |
| the committed schema | `policy/canvases/canvas_template.schema.json` | generated, self-declaring |
| the drift seal | `tests/test_canvas_schema_drift.py` | 12 tests, positive control first |
| seal 3 | `tests/planning/test_canvas_seed_determinism.py` | structural arm + opt-in live arm |
| the CI job | `.github/workflows/validate-canvas-templates.yml` | `pull_request` — see the departure |

## Seal 3 is recorded as FAILING, and it is recorded structurally

ADR-0050 requires seal 3 to be run against today's seed **and to fail**, because *"a seal that
has never been shown to bite on the thing it was written to catch is decorative."*

**It fails, and the failure is asserted from the seeder's source rather than from one run.** That
is deliberately stronger than a live observation: a single live pass could come back stable by
luck and would then read as the seal passing. Today's `PORTFOLIO_CANVAS_QUESTIONS` declares five
**phrases** and no verb, so each panel's verb is whatever the classifier returned on that run —
the panel set is not merely unstable, it is **not expressible until after the seed completes**.
The seeder's own comment records the instability (*"subject resolution SHIFTS… moved Portfolio
0.86 → Site 0.75 across a single prime"*), and the test asserts that sentence is still there, so
the rationale cannot be quietly deleted out from under the seal.

**The live arm exists and was NOT run tonight.** It is `CANVAS_SEED_LIVE=1`-gated, and the reason
it stayed off is a measurement hazard, not convenience:

* seeding is **sequential by RULING (b)** — ~25 min per seed, so the arm is ~50 min;
* `max_concurrent_runs: 2` plus a reaper gap **deadlocked this queue twice in one day**;
* **a prime was in flight** (`mesh:StatefulSupportResponse`), and a prime *changes subject
  resolution*. Running then would have produced the expected failure **for an unattributable
  reason** — a coincidence wearing a result's clothes, which is the same error class as a
  positive control that passes because it matched the wrong prefix.

Run it on a quiet substrate and paste the two panel sets into this packet.

## The CI job departs from a standing convention, deliberately

`suite-order-independence.yml` is `workflow_dispatch`-only under
[`no-ci-gate-on-the-suite`](no-ci-gate-on-the-suite.md): a never-executed job wired to `push`
burns minutes or goes red for environment reasons and trains people to ignore it.

**This job is wired to `pull_request` anyway**, because §1.3's requirement is specifically
merge-time failure and a dispatch-only job does not deliver it — shipping one and calling §1.3
satisfied would be the decorative seal the ADR is written against. The exemption is narrow: the
job is seconds of hermetic pure Python over ~200 lines of YAML, with no cluster, no database and
no network. **The fallback is pre-committed: one environment-caused red and it demotes to
`workflow_dispatch`.** The standing rule loses to an argument only until it wins on evidence.

## Two corrections the build made to its own inputs

**The generator must not import through the `iagent` package.** `src/iagent/__init__.py` imports
the Dagster definitions, so `from iagent.canvas_template import …` opens Postgres connections and
emits cortex-bff proxy warnings before reaching a Pydantic class — observed on the first run. A
schema is a projection of a type and must not need infrastructure to produce, or the seal only
goes green where infrastructure happens to be reachable. The generator loads the models **by file
path**, and `test_the_generator_is_hermetic` is what stops someone simplifying that back.

**The CI broken-on-purpose fixture violated two rules and was measuring a coincidence.** The
first draft used `_brokenonpurpose` as the `template_id`, which also fails the id pattern — so
the step would have gone red **with the verb check deleted**. Fixed to violate exactly one rule,
and the step now additionally greps for `panels/0/verb` so a failure from any other cause
(missing dependency, moved directory) cannot read as the control working.

## OWED — named, not implied

1. **Verb-EXISTENCE checking.** Acceptance seal 1 is *"a template referencing an undeclared verb
   fails at merge"*. What landed is the **shape** gate — a malformed verb IRI is refused. Nothing
   yet asserts `mesh:planCostCurve` is actually registered. The test that covers the shape half
   says so in its own docstring rather than implying the whole seal.
2. **The live seal-3 run** (above).
3. **The cortex `TEMPLATES` row.** §7: `CanvasUse` is a closed union with one row, and a second
   `template_id` must be admitted **on both sides, frontend first**. Slice 1 re-expresses the
   existing canvas so nothing new is advertised yet — but slice 2 cannot land before that row
   does, and the ordering trap is already written by name into the archetype registries.
4. **`shared_slots` is empty on purpose.** `program` is §3's worked case and belongs to slice 2,
   gated on the dispatch-boundary slot carry. Declaring one now would fire an ask whose answer
   nothing can bind — a question that costs the user a turn and changes no card.

## The one panel worth reading twice

`plan_funding_gap` declares `group_by: org`. That is the verb's real signature default, and the
phrase it replaces (*"where is funding short by organization"*) was **reworded on 2026-08-28 to
match that default** after the by-initiative wording returned eleven organisations — the verb ran
on its default while the card's question said something else, with no disclosure surface, because
the strip renders routing and not verb params. Declaring it makes the card's parameters legible
instead of true by luck. **Revert to `initiative` only when extraction AND carry both land**; the
acceptance test for that build is this panel returning initiatives.
