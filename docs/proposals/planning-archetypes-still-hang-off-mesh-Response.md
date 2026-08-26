# Nine planning archetypes still hang off `mesh:Response`

**For Lane 1 (ontology).** Found by Lane 2 while running the full suite; **not fixed here**,
because the file is yours and the correct target is a convention call, not a mechanical edit.

## The failing test

    tests/planning/test_planning_classes_are_declared.py
      ::test_planning_archetypes_hang_off_mesh_Archetype_not_mesh_Response

    AssertionError: mesh:IntervalSchedule is not a mesh:Archetype
      (parents: {'http://invincible-agent/mesh#Response'})

Failing on committed HEAD, with no TTL modified in the working tree — so it is not a
regression from anything in flight. It has been red at least since 2026-08-25.

## The shape: ONE class follows the new convention, NINE predate it

Enumerated from `setup/ontologies/mesh_system.ttl`:

| class | declared parent | line |
|---|---|---|
| `mesh:ShortfallGrid` | **`mesh:Archetype`** ✅ | 394 |
| `mesh:PeriodCostSeries` | `mesh:Response` | 245 |
| `mesh:FundingGapSet` | `mesh:Response` | 250 |
| `mesh:LoadThresholdGrid` | `mesh:Response` | 255 |
| `mesh:DecisionArtifact` | `mesh:Response` | 265 |
| `mesh:MaturityMatrix` | `mesh:Response` | 275 |
| `mesh:ContributionSequence` | `mesh:Response` | 280 |
| `mesh:FootprintSet` | `mesh:Response` | 290 |
| `mesh:IntervalSchedule` | `mesh:Response` | 295 |
| `mesh:EffectSet` | `mesh:Response` | 310 |

**`ShortfallGrid` is the newest** — added yesterday with the funding-gap binding — and it is the
only one under `mesh:Archetype`. So the convention changed when it landed, the test was written
to the new convention, and the nine older classes were never migrated. The test is not wrong;
it is early.

## Why this is a ruling and not a find-and-replace

The nine are the SAME classes the hardened renderers project and the presentation registry binds
(`INTERVAL_TIMELINE`, `PERIOD_SERIES`, `THRESHOLD_GRID`, `MATRIX_GRID`, `DELTA_SET`). Their
parent is read by anything that walks the class graph, so the migration is a substrate change,
not a text change:

* **Contract D** validates that a verb's `output_uri` resolves to an `:OntologyClass` — a
  reparent lands through the prime, and engine-p re-registers against it. That is the path that
  rejected all fourteen planning verbs atomically when `mesh#DecisionArtifact` was missing.
* Anything selecting on `subClassOf mesh:Response` today would stop seeing these nine.
* The prime is the only reproducible way to apply it (`fold-not-hand-run`), which means the
  change and its verification are ~50 minutes apart.

## What I verified, so you do not have to re-derive it

* The nine are declared exactly once each; no duplicate or conflicting parent triples.
* No TTL is modified in the working tree — this is committed state.
* `mesh:Archetype` exists as a class (ShortfallGrid resolves against it), so the target is real
  and not a dangling reference.

## Suggested acceptance, if you take the migration

Pre-register before priming, per house discipline: **all ten planning classes report
`subClassOf mesh:Archetype`**, Contract D refusals **0**, engine-p registers **14 verbs**, and
`test_planning_archetypes_hang_off_mesh_Archetype_not_mesh_Response` goes green. Those four
numbers together distinguish "the TTL changed" from "the substrate accepted the change" — a
distinction this repo has paid for before.
