# B(2) probe → prime → pcn dogfood — run card (one place, not four)

The consolidated deploy procedure for the PCN/PDN dogfood. All the graph-collision / read-union / vocab
work is committed and deploy-gated (see `pcn-pdn-bulk-resolve.md §8` for the why); this is the ordered
**do**. A cluster/deploy action — run it in the deploy session.

Preconditions already landed (do NOT re-litigate at the console):
- Graph-split + read-union — DONE (`0183b41` engine-o union, `927a41e`/`dd218e8` split, `fff5378` AGENTS).
- Idempotency ruling — SETTLED (VirtualObject-on-composite; `pcn-pdn-bulk-resolve.md §1`).
- CORE re-tag audit — the prime run FIRES its wake, and the deferral is already recorded (`§8.1`). That
  decision is **spent** — don't re-open it at prime time.

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

## Everything else is in its wake state with a named trigger

Zero undocumented dormancy (the point of the week): dispatcher → on the settled ruling; disposition
verbs → per-endpoint; LLM rung → on `recall_override` telemetry; CORE audit → on its new condition
(`§8.1`); ADR-0025 flip riders (can_view 3-caller seal / menu re-check / suspended-join re-eval);
Decision D → its three parked questions (role-split menus, anonymous-count disclosability, reason
quality). None waits on a decision that hasn't been made.
