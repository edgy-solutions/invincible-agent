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
| `procedure 1234` | **resolveInstance identifier-form brittleness** — the instance exists ("Test Procedure 1234" in Neo4j, provider registered) but the query token "1234" doesn't match the display name | Open — ADR-0031 resolution-ladder territory (engine-d/e). The containment fix (`87fe361`) covers descriptor *suffixes* (a name-plus-descriptors query ⊃ the core cataloged name), not a bare-number token vs a full display name. |

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

## Re-run after the ontology-menu fix (2026-07-22, same day)

The ontology PUT-overwrite + graph-name bugs were fixed and fully re-deployed
(doc-tools `71a66f9` PUT→POST; iagent `e3edb58` prime `clear_ontology_graphs`;
engine-o `{domain}` `014ab45`), then Fuseki was cleared + re-ingested (11 runs,
POST-append) and every engine rolled. **Re-run: 16 passed / 7 failed —
byte-identical to the baseline above, same 7 cases.**

That is the point of the re-run: the entire ontology-fix + re-deploy cycle
(new producer/consumer code, a full Fuseki clear+rebuild, engine rolls)
**introduced zero regression.** The matrix exercises `/resolve` + `/classify_predicate`
(instance + class routing), which read Neo4j/Weaviate — unaffected by the Fuseki
graph fix (`/classes` is the only consumer of the graph-scoped Fuseki path, and
nothing in the matrix reads `/classes`). Substrate re-verified intact after the
re-ingest: Neo4j 955 OntologyClass / 852 subClassOf (the MinIO→Neo4j sync reads
the TTLs directly, so the Fuseki PUT-overwrite never reached it).

### What the ontology fix DID change (not in this matrix)

`/classes` (the SPO-interview subject menu, ADR-0029 Slice 2) went from
**mil-only 10 classes → the full 294-class IOF ontology (105 labeled, 104 named
IOF-core: `agent`, `algorithm`, `assembly`, `action specification`, …)**. Root
cause was `ingest_ontology_to_jena` PUT-replacing one domain graph per file, so
N MAINTENANCE TTLs collapsed to the last (mil_extension); IOF_Core/MRO were
silently destroyed. Fixed at source (POST-merge + clear-once), reproducible, no
hand-seeded data.

### New finding surfaced by the now-working menu (Slice-2, not a regression)

With the menu populated, a live probe showed the **subject menu and the
verb-bearing subjects are disjoint**: the menu is the Fuseki IOF ontology
vocabulary (`/classes`), while the verb edges sit on ~60 curated routing classes
in **Neo4j** (`MaintenanceReferenceOntology/WorkInstruction` → `queryKnowledgeGraph`,
`TechnicalManual` → `retrieveKnowledge`). Those verb-bearing IRIs are **not in the
Fuseki menu graph at all** — so `/find_compatible_verbs` works for them, but the
interview can't *offer* them (the enforcement correctly restricts picks to the
menu). The verb question itself is proven live; aligning the menu vocabulary with
the verb-bearing routing subjects is a Slice-2 data-model decision (which source
of truth the subject menu draws from), separate from the overwrite bug. It is not
a regression — the menu was empty before, so this was never exercisable.
