# Post-bump sandbox regression baseline — 2026-07-22

The comparison the last regression gate lacked: a recorded baseline. Captured
after the chart `0.3.10 → 0.3.23` upgrade (which pulled ~13 versions of routing/
resolution code, incl. the ADR-0031 resolution-ladder work and the D4/engine
fixes). **No pre-bump baseline exists** — the upgrade already happened — so this
is the *post-bump* reference; it does not prove any case flipped green→red from
the bump itself, only where the current cluster stands.

## Matrix: 16 passed / 7 failed

The split is clean and diagnostic: **class/ontology routing is 16/16 green**
(the path the D4 / ontology-graph / engine-name work touched — no regression),
and **all 7 failures are named-instance resolution → UNKNOWN**, in engine-d/e
paths. Substrate intact at capture: Neo4j 955 OntologyClass / 852 subClassOf /
13 verb edges, resolveInstance providers D+E re-registered.

## The 7 failures, characterized

| Case | Kind | Status |
|---|---|---|
| `gold.sales.revenue_summary` (×2), `Customer 360 dashboard`, `customers_gold` | **demo-catalog gap** — `seed_datahub_catalog` was the one demo seed not folded, so a fresh cluster has no demo catalog to resolve against | **Addressed:** folded into the gated `demoSeed` Job (`demoSeed.seedCatalog`, commit `dbc42d9`). ⚠️ seeding WRITES to DataHub → needs `secrets.datahubToken` (a write PAT); empty in this sandbox, set at work. |
| `foo.bar.zzz_nope` | **abstention gate working AS DESIGNED** — a non-existent instance *should* resolve to UNKNOWN (`_ir_abstention` → `instance_not_found`) | Not a real failure — a pass mislabeled. Folding the catalog will NOT (and should not) change it. |
| `procedure 1234` | **resolveInstance identifier-form brittleness** — the instance exists ("Test Procedure 1234" in Neo4j, provider registered) but the query token "1234" doesn't match the display name | Open — ADR-0031 resolution-ladder territory (engine-d/e). The containment fix (`87fe361`) covers descriptor *suffixes* ("rso portal superset dashboard" ⊃ "rso portal"), not a bare-number token vs a full name. |

## Reading it

- The ~4 DataHub cases are a **reproducibility** gap, now closed in code — a
  fresh cluster with `demoSeed.enabled=true` **and** a DataHub write PAT seeds
  the demo catalog, so those resolve. Without the PAT the catalog emit 401s
  (auth), which is an operator-credential requirement, not a code defect.
- `zzz_nope` is honest-abstain behavior; leave it.
- `procedure 1234` is the live instance-resolution hardening thread (the
  telemetry signals `recall_override` / `no_instance` / `RESOLVE_INSTANCE_ALIAS`
  are the instruments for whether an LLM candidate-generator rung is ever worth
  building — see ADR-0031).

So the honest headline: **16/23 is the post-bump baseline; of the 7, ~4 are a
now-folded demo-data gap (pending the write PAT), 1 is a correct abstain, and 1
is the open resolveInstance identifier-form thread.** None are in the
class/ontology-routing path.
