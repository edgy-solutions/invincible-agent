# B(2) probe → prime → pcn dogfood — run card (one place, not four)

The consolidated deploy procedure for the PCN/PDN dogfood. All the graph-collision / read-union / vocab
work is committed and deploy-gated (see `pcn-pdn-bulk-resolve.md §8` for the why); this is the ordered
**do**. A cluster/deploy action — run it in the deploy session.

Preconditions already landed (do NOT re-litigate at the console):
- Graph-split + read-union — DONE (`0183b41` engine-o union, `927a41e`/`dd218e8` split, `fff5378` AGENTS).
- Idempotency ruling — SETTLED (VirtualObject-on-composite; `pcn-pdn-bulk-resolve.md §1`).
- CORE re-tag audit — a **FULL prime** (DROP-first, re-ingests IOF_Core) fires its wake; a
  **partition-additive** ingest does NOT. What actually landed pcn was additive, so the wake is
  **still ARMED** (not fired, not spent) — see the two-modes note below.

**⚠️ TWO INGEST MODES — "run the prime" is ambiguous; always name the mode.**
- **Partition-additive (safe default):** launch ONE TTL's `ontology_files` partition
  (`addDynamicPartition` + `launchPipelineExecution` on `ingest_ontology_job`, `domain` explicit, NO
  `clear_ontology_graphs`). POST-merges one file into one domain graph; other domains + instance
  graphs untouched; no regression gate; does NOT fire the CORE-audit wake. This is what landed pcn
  and re-tested mesh_system.
- **Full prime (`prime_databases.py --trigger-ingest`):** `clear_ontology_graphs()` DROPs the
  manifest domain graphs (DROP-first), then re-ingests the whole manifest. Destructive,
  decision-bearing, needs the frozen-matrix regression gate, and DOES fire the CORE-audit wake
  (re-tags IOF_Core across domains). Every doc that says "run the prime" means THIS mode.

## B(2) probe — in order, with the 2×2 live

Producer→consumer, so a break localizes to the hop that shows it:

1. **MinIO (source truth).** `mesh_system.ttl` present at the ingest source, and the
   InstanceIdentifier / InstanceResolution triples present *in the file*. If absent here, everything
   downstream is moot — the bug is upstream of everything probed.
2. **Fuseki (producer truth).** The pair present in the domain graph post-prime. Distinguishes
   *staleness* (not yet re-ingested) from *sync failure*.
3. **Neo4j (consumer truth).** The pair as `:OntologyClass`, **and** the pcn classes alongside them.
   The long-`rdfs:comment` probe rides for free here — if the suspected per-node-write-on-long-comment
   bug is real, the pcn classes drop at this hop.

## Read the result against §8.2 BEFORE writing anything down

| pcn syncs? | pair reappears? | verdict | routing |
|---|---|---|---|
| yes | yes | staleness was the whole story; long-comment hypothesis **moot** | **green-lights the full sequence** → prime + dogfood; convergence unblocked |
| yes | no | hypothesis **FALSIFIED**, drop **unexplained** | B(2) stays **OPEN** — do NOT record "sync works". `_TEMPORARY` retirement WAITS (its wake was `resolve_instance` registering cleanly). New probe for the unexplained drop. |
| no | — | hypothesis **strengthened** (long comments break the write) | fix the sync, re-probe. Keep the long comments — they're the test. |
| no | yes | mixed / two independent effects | investigate both; do not average into a verdict |

Only the first cell green-lights the full sequence. The others **re-route, not fail.**

## Then (first cell only)

4. **Prime.** Lands `pcn_extension` (+ re-lands the manifest; instances live in `{DOMAIN}_INSTANCES`,
   untouched by the manifest DROP). CORE-audit deferral is spent — proceed.
5. **Dual-substrate dogfood red→green** (all four, or it's not green):
   - pcn classes present in Fuseki's `SUSTAINMENT` graph, **and**
   - present as `:OntologyClass` in Neo4j, **and**
   - surfaced by `/classes?domain=SUSTAINMENT`, **and**
   - the SPO interview offers them as subjects — with **honestly-zero verbs** (the true state until
     disposition endpoints land; a non-empty verb menu here would be the bug, not the goal).
6. **Re-extract** a PCN/PDN doc after prime — that pre-split batch was declared non-surviving
   (`§8.0b`), so the real parts come from a post-split extraction.

## Run log — 2026-07-23, read-only half (prime NOT run; doc-tools untouched)

Ran the read-only diagnostic against current sandbox state (context `edge`). Held at the prime line —
prime triggers the doc-tools ingest and another agent was testing doc-tools.

- **Hop 1 (MinIO, source):** transitively confirmed — the pair is in the repo TTL AND downstream in
  Fuseki, so the source chain is intact (a class can't be in Fuseki without being in the source).
- **Hop 2 (Fuseki, producer):** ✅ both `mesh:InstanceIdentifier` + `mesh:InstanceResolution` are
  `owl:Class` in `http://internal/MESH`, with all 22 mesh siblings.
- **Hop 3 (Neo4j, consumer):** ✅ both present as `:OntologyClass` — **and** carrying their FULL long
  definitions (`InstanceIdentifier` 648 chars, `InstanceResolution` 675) vs the short control
  `AgentResponse` (47). No node dropped, no comment truncated.

**Verdict (read carefully against §8.2):** the long-comment-per-node-write hypothesis is **FALSIFIED on
current data** — the two LONGEST-comment mesh classes synced completely, node and definition. The B(2)
motivating symptom (pair absent from Neo4j) is **not present**. This is NOT the trap cell ("pcn syncs +
pair still missing") — the opposite is observed, so there is no silent "sync works" collapse to guard
against here. **Caveat (honest):** this reads CURRENT state, not a FRESH re-ingest — "present + complete
now" points hard at *staleness-was-the-story / already-resolved*, but the definitive "a fresh write lands
them clean" and the pcn-specific long-comment sync both need the prime run, which stayed held.

**Routing:** green branch — convergence is very likely unblocked. Remaining, prime-gated (do when
doc-tools is free): run prime, then re-verify these two STILL carry full definitions post-fresh-ingest,
**and** that pcn classes sync with theirs. `_TEMPORARY` retirement: encouraging (its resolve_instance
substrate classes are present + complete), but its own clean-registration test is separate.

## Run log — 2026-07-23, DNS fixed, pcn vocab dogfood GREEN (additive, not full-prime)

DNS root-caused + fixed (Pi-hole rate limit raised), engine-o re-rolled clean → **read-union deployed**
(`grep -c _graph_scope` = 3 in the running pod). Then landed the pcn vocabulary **additively** — the
ingest is a `DynamicPartitionsDefinition` (one partition per TTL), so instead of a destructive full
re-prime I ran the single pcn partition, which touches only the SUSTAINMENT graph:

- `mc pipe` `pcn_extension.ttl` → `ontologies/sustainment/pcn_extension.ttl` (kubectl cp needs tar,
  absent in the minio container; pipe on stdin works).
- Dagster GraphQL: `addDynamicPartition` + `launchPipelineExecution` on `ingest_ontology_job` assets
  `[ingest_ontology_to_jena, sync_jena_ontologies_to_neo4j]` with `extra_metadata.domain=SUSTAINMENT`
  passed EXPLICITLY (no path-derived-domain risk) and NO `clear_ontology_graphs` (additive). Both
  asset steps SUCCESS.

**Dogfood red→green — all four, verified:**
- ✅ Fuseki: 4 pcn classes in `<http://internal/SUSTAINMENT>`; graph 10104 → **10142** (+38, grew not dropped).
- ✅ Neo4j: 4 pcn `:OntologyClass` (domain=SUSTAINMENT) with FULL definitions (Component 352, notices
  326-337 chars) — **pcn's long comments synced intact**, so the long-comment-drop hypothesis is
  falsified on pcn data too (the pcn half of §8.2's 2×2).
- ✅ `/classes?domain=SUSTAINMENT` (engine-o read path + union): 89 classes incl. all 4 pcn subjects
  (Component / PDN / PCN / Sustainment Notice) — the SPO interview's authorized-subject source, so it
  now offers them, with honestly-zero verbs (no disposition endpoints yet).
- ✅ No collateral: `SUSTAINMENT_INSTANCES` = **26** (untouched — the real IPCN25300X parts survived);
  DATA_ENGINEERING/MAINTENANCE/MANUFACTURING/MESH all unchanged. The collision fix + additive path
  proven end-to-end on live data.

**B(2) CLOSED — the grid is complete (2026-07-23, arch-caught that the pcn half wasn't the point).**
The probe's actual subject was the InstanceIdentifier/InstanceResolution pair, not pcn. Ran the
`mesh_system` partition **additively** (same safe path; it was already in MinIO) to test the pair
against a FRESH sync write. Result: both steps SUCCESS; Neo4j pair present with FULL defs (648/675,
unchanged) and mesh class count unchanged at 22. So: pcn syncs ∧ pair present-after-fresh-re-ingest →
the **staleness** cell → the long-comment-drop hypothesis is **moot**, B(2) is **CLOSED**, and the
sync-health blocker on the `_TEMPORARY`/resolveInstance convergence is removed (that thread's own
clean-registration test is next; B(2) no longer gates it).

**Remaining (unchanged wake states):** pcn INSTANCES (26 triples) aren't consumable until the pcn
resolveInstance provider exists; zero disposition verbs until endpoints land; the bulk-resolve
dispatcher/driver is the M1 chunk.

## Run log — 2026-07-23, M1 wiring #1: disposition rules LIVE, policy-as-data proven end-to-end

Cluster authorized ("cluster is yours"). Landed the disposition-rules TTL via the same additive
partition path as the vocab (§8.0c order: rules ingest FIRST), Jena-only (rules are individuals, not
`owl:Class`, so no Neo4j sync): `mc pipe pcn_disposition_rules.ttl` → MinIO → Dagster launch
`ingest_ontology_to_jena` only, `domain=SUSTAINMENT`, no clear. SUCCESS. **Verified live:** 6
`pcn:DispositionRule` + 6 `pcn:changeClass` in `<http://internal/SUSTAINMENT>`. **Loader acceptance
gate MET LIVE** (not just fixture): a SPARQL CONSTRUCT of the rule triples → `load_disposition_rules`
→ 6 rules / 6 classifications, `ruleset_ref = rules@edc21f242929`, `validate_ruleset` CLEAN, and the
real IPCN25300X shape (Material/Process/Location/Testing) → **`dispatchQualification`** — the actual
notice's disposition computed from POLICY-IN-THE-GRAPH, no code table. The policy-as-data thesis works
against real data. Remaining loader work = the driver's live SPARQL fetch inside the engine (the
CONSTRUCT I ran by hand becomes the driver's query); pure graph→structure logic is sealed + live-proven.

## Run log — 2026-07-23, M1 wiring #2: resolveInstance provider LIVE (instances consumable)

§8.0c order step 2 done. Provider code (route `POST /resolve_pcn_instance` + pure matcher, 7/7;
reproducible self-registration in engine-o's lifespan via `register_engine_to_mesh`, mirroring Engine
D — survives re-prime, `5a7f6bc`/`657dff4`). CI built the engine-o image; rolled engine-o. **Verified
LIVE end-to-end:** on boot engine-o logged the registration and Neo4j holds
`(InstanceIdentifier)-[resolveInstance {provider:engine_o_sustainment, endpoint:/resolve_pcn_instance,
domains:[SUSTAINMENT], timeout:5}]->(InstanceResolution)` — discoverable by the /resolve fan-out.
Endpoint results: `NSR01L30NXT5G` → `components/NSR01L30NXT5G` (pcn:Component) @1.0 + fuzzy neighbors
sorted; `PCN IPCN25300X` → `doc/IPCN25300X` (ProcessChangeNotification) @0.9 (PCN kept as fragment);
`ZZ_BOGUS_9999` and lone `the notice` → 0 candidates (honest abstain). The 26 real instance triples
are now consumable. SURFACED (not hidden): engine-o is router AND this provider — mild smell, accepted
(owns the Jena instances), exit documented (move to a sustainment engine if one appears).

**Next (§8.0c step 3): menu-growth** — a DISTINCT capability write. `_OPERABLE_SUBJECTS_CYPHER` is
`MATCH (s:OntologyClass)-[r]->() WHERE r.iri IS NOT NULL`, so a class is operable iff it has a VERB
edge — the resolveInstance provider (on InstanceIdentifier) does NOT grow the pcn-subject menu. That
needs the disposition-VERB registration pointing at a REAL disposition endpoint (verbs wake
per-endpoint; a stub would be the dead-end menu). So step 3 = the disposition endpoint (the first real
effect endpoint — where a hidden decision is most likely) + its verb registration carrying the
menu-growth assertion, then funnel smoke over IPCN25300X.

## Run log — 2026-07-23, M1 wiring #3: dispatch graph-write + step-5 query LIVE (engine-o side)

The engine-o side of the dispatch loop. `POST /write_pcn_disposition_state` (idempotent
delete-then-insert into SUSTAINMENT_INSTANCES via a derived Jena `/update`) + `POST /pcn_parts_by_state`
(step-5 query via the read-union). Three build/roll cycles — two bugs, both caught by VERIFY-LIVE not
assumed green: (a) `Optional[str]` under `from __future__ import annotations` → Pydantic 500 (module
forbids typing imports, §657); (b) `INSERT DATA` close was a PLAIN string `' }} }}'` → four literal
braces → Fuseki 400 (the hand-written SPARQL succeeded; only the Python construction was wrong). Fixed,
rebuilt, **verified LIVE:** wrote dispatchQualification→NSR01L30NXT5G, dispatchLTB→NSR01F30NXT5G,
archive→SNSR15304NXT5G (all `ok:true`); step-5 `pcn_parts_by_state` returned each part in its state via
the read-union — "all parts in LTB" is one hop through the same graph the policy lives in, no dashboard
store (the architectural win). Test state then DELETED (state-without-task is the inconsistency the
convergence decision kills; the real driver produces state+task together). The dispatch effect's two
writes now both have live executors: task-mint (cortex-bff `_register_human_task`) + graph-state
(`/write_pcn_disposition_state`).

**Next: the Restate DRIVER** — grouped HumanTask (review) → resolve_batch → per-item VirtualObject
(keyed notice×part) executing `plan_dispatch` as two journaled `ctx.run` steps, TASK-FIRST, with the
failure-injection convergence seal. Then the menu-growth verb registration (observed) + the cortex-ui
dashboard calling `/pcn_parts_by_state`.

## Everything else is in its wake state with a named trigger

Zero undocumented dormancy (the point of the week): dispatcher → on the settled ruling; disposition
verbs → per-endpoint; LLM rung → on `recall_override` telemetry; CORE audit → on its new condition
(`§8.1`); ADR-0025 flip riders (can_view 3-caller seal / menu re-check / suspended-join re-eval);
Decision D → its three parked questions (role-split menus, anonymous-count disclosability, reason
quality). None waits on a decision that hasn't been made.
