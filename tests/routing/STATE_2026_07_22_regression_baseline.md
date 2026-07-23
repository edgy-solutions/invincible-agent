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

### Menu-vs-verb finding (Slice-2) — CORRECTED 2026-07-22

⚠️ **RETRACTION (verified vs asserted):** an earlier draft of this section asserted
the menu and the verb-bearing subjects were **"disjoint"** and the `spo_operation`
path was **blocked**. That was WRONG — it came from a *mid-ingest snapshot* (a 105-
class menu captured while the re-ingest was still in flight, plus a per-subject verb
loop that under-counted). Same failure class as the lowercase graph-map: a transient
count presented as a stable fact. The numbers below are re-measured on the STABLE
state (release rev 59, chart `0.3.26`, all ontology-ingest hooks green — NOT mid-ingest).

**VERIFIED (live, 2026-07-22, rev 59):**
- The `spo_operation` path **works** — the live interview authored
  `spo_operation(subject=MaintenanceReferenceOntology/TechnicalManual,
  verb=mesh:retrieveKnowledge, output=mesh#KnowledgeRetrievalResponse)` through real
  Restate+BAML, and the definition validated (`complete: True`). Slice-2 is sealed
  live across ALL step kinds (metadata + human_await + direct_call + spo_operation).
- Exact overlap, MAINTENANCE domain: **menu (`/classes`, Fuseki IOF vocab) = 122**;
  **verb-bearing (Neo4j capability graph, all domains) = 14**; **overlap
  (spo_operation-authorable) = 7** (WorkInstruction, TechnicalManual, ProcedureStep,
  4 mil DataModules). **115 of 122 menu subjects (94%) carry no verb** (abstract IOF
  vocabulary: agent, algorithm, assembly, DitaNode…). The 7 verb-bearing subjects NOT
  in the MAINTENANCE menu (`mesh#*`, `idp#Dataset`, `mfg#*`) are OTHER domains,
  correctly excluded by domain scoping — not a gap.

**So the real issue is menu signal-to-noise, not a blocker:** the interview offers
122 subjects but only 7 lead to an `spo_operation` (94% dead-ends). The Slice-2
design question is whether the operation-subject menu should be SOURCED from the
capability graph (verb-bearing subjects, per role) rather than the full ontology
vocabulary — a `select-from-authorized-set` question (authorized subject set =
domain ∩ can_view ∩ has-a-compatible-verb), taken to the architect. Not a regression
(the menu was empty before) and not the overwrite bug.

## After the DataHub catalog seed + engine-d read-auth (2026-07-22)

The DataHub demo-catalog gap was closed on sandbox: a write PAT was minted (operator),
stored durably in a gitignored `values-sandbox.secret.yaml` overlay feeding
`iagent-secrets.DATAHUB_TOKEN`, the demoSeed catalog job (chart 0.3.25) seeded 8 datasets /
3 dashboards / 3 charts with it (no 401), and engine-d was restarted to pick up the
now-populated token (envFrom injects at pod-start; engine-d had rolled before the PAT landed).
**Matrix: 20 passed / 3 failed.**

The 5 DataHub cases flipped UNKNOWN → resolved (`gold.sales.revenue_summary` ×2,
`What feeds …amount?`, `Customer 360 dashboard`, `customers_gold`). Remaining 3:

- `foo.bar.zzz_nope` — correct abstain, a pass mislabeled (unchanged; leave it).
- `procedure 1234` — the open resolveInstance identifier-form thread (unchanged; engine-e/ADR-0031).
- `What's the weather like today?` — **NEW this run; it passed in the two prior runs.** An
  out-of-domain query whose abstention is LLM-mediated (gpt-oss). Per the intermittent-failure
  discipline a single-shot result on a stochastic case is luck; almost certainly an LLM blip
  (nothing in the catalog/ontology/engine-d work touches off-domain routing), but flagged rather
  than dismissed — a confirming re-run is the honest close.

Reproducibility note: the seed + engine-d-auth were done via a direct job + restart because
(a) the deployed release was chart 0.3.23 while the catalog fold is in 0.3.25, and (b) a flaky
k8s API kept throwing transient EOFs that failed the helm hooks. A clean `helm upgrade` to 0.3.25
with `-f values-sandbox.secret.yaml --set demoSeed.enabled=true` on a stable API does it all from
install (engines get the token + the catalog seeds in one pass) — no direct-run/restart needed.
