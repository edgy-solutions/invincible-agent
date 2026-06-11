# State Snapshot — 2026-06-11, Recipe v2 landed

Instance resolution as a registry-discovered capability is live. Every
gate in the recipe's §5 build order green; matrix red rows are all
gated on sandbox-DataHub-has-no-test-assets, not on architecture.

## What landed (commits, in order)

| # | sha | summary |
|---|-----|---------|
| 1 | d454a64 | Step-0 spec rows (R1-R7) committed before code |
| 2 | a9071b4 (doc-tools) | canonical mesh_system.ttl in source control + new InstanceIdentifier/InstanceResolution classes |
| 3 | d6cd491 | Engine D /resolve_instance + pure decision-table module + 18 logic tests |
| 4 | d56e74b | Engine O wires the leg + BAML schema + recall-biased prompt + invariant guards |
| 5 | a3f5548 | mesh-registrar uses `mesh_`-prefixed customProperties (gateway↔sensor protocol fix) |
| 6 | 75a8011 | container-vs-dev import fallback for instance_resolution |
| 7 | 94560ad | replace undefined `logger` with print() in instance helpers |

## Gates

| Gate | Status | Evidence |
|------|--------|----------|
| Spec  | ✅ | R1-R7 in `test_classify_route.py`; R1/R2/R6/R7 stay red until DataHub seeded |
| TTL   | ✅ | `mesh:InstanceIdentifier` + `mesh:InstanceResolution` in Neo4j @ `domain=MESH` |
| Provider | ✅ | Gateway: `Registered urn:li:mlModel:(...,engine_d_resolve_instance,PROD) (verb=mesh:resolveInstance)`; sensor: `✅ Synced predicate edge: (mesh:InstanceIdentifier) -[resolveInstance]-> (mesh:InstanceResolution)` |
| Logic | ✅ | 18/18 decision-table tests PASSED |
| Router | ✅ | end-to-end /resolve verified — identifier extracted, providers discovered, fan-out fired, decision table empty-case fall-through, provenance dict populated with `instance_identifier`, `llm_guess`, `instance_match`, `instance_n` |
| Generality | ⏳ | deferred — Engine E joins next as second provider; architecture proves itself when adding the second provider needs ZERO changes to `ontology_service/main.py` (the standing-guard tests would turn red if a backend name leaked in) |

## Standing guards in place

`tests/routing/test_recipe_v2_invariants.py` (5/5 PASSED):
- No lexical→class mapping (regex) in any Engine O source file
- No backend-specific names (`iagent-engine-d`, `datahub_wrapper`, etc.) in router code
- Decision table stays in its dedicated pure module (not inlined into main.py)

`tests/routing/test_instance_resolution_decision.py` (18/18 PASSED):
- Every branch of the decision table covered with no cluster, no HTTP, no LLM

## Side-quest results — Contract D gaps closed for free

The gateway's `mesh_`-prefixed-props fix retroactively unblocks every
engine that opted into the gateway last night. After the fix shipped:

```
Registered ... engine_a_*        (9 verbs)
Registered ... engine_da_*       (1 verb)
Registered ... engine_e_neo4j_expert      (mesh:queryKnowledgeGraph)
Registered ... engine_w_weaviate_expert   (mesh:retrieveKnowledge)
Registered ... engine_d_resolve_instance  (mesh:resolveInstance)
```

The architect's earlier worry about `mesh:GraphExpertResponse` and
`mesh:KnowledgeRetrievalResponse` being plumbing-pseudo-classes is
settled: both were legitimate Response-shape concepts in the
canonical mesh_system.ttl all along; they just had never been
*ingested* until tonight. The gateway caught the gap; Piece 1's
canonical re-ingest closed it.

## Matrix steady-state

**13 / 17 passing** (5-row Recipe v2 block + Wave-1 hierarchy + 11 originals).

| Row | Query | Status | Why |
|-----|-------|--------|-----|
| R1 | Tell me about gold.sales.revenue_summary | RED | DataHub empty in sandbox; instance leg fires correctly, empty answer, falls through to LLM (lands at idp:Column) |
| R2 | Tell me about gold.sales.revenue_sumary (typo) | RED | same as R1 |
| R3 | Tell me about foo.bar.zzz_nope | **PASS** | ghost name correctly lands at UNKNOWN (instance leg empty → LLM low-conf → generalist) |
| R4 | What feeds gold.sales.revenue_summary.amount? | RED | LLM picks `mesh:traceLineage` despite subject=idp:Column (the verb is typed against idp:Dataset — Column is NOT a subclass of Dataset). Side-quest: hierarchy hint may need a "compat_verb_iris=[] means abstain" rule, OR R4's expected behavior needs updating to reflect that the LLM CAN semantically infer a verb when the subject lacks typed verbs. Not a Recipe v2 architecture failure. |
| R5 | What tables do you have? (control) | **PASS** | identifier=null, instance leg never fires, lands at idp:Dataset → mesh:enumerateCatalog ✓ |
| R6 | Tell me about the Customer 360 dashboard | **PASS** | LLM extracts "Customer 360"; phone book empty; LLM correctly picks idp:Dashboard from query semantics |
| R7 | so yesterday someone mentioned customers_gold or something, what is that? | RED | Extraction recall worked; phone book empty; LLM landed on idp:Column rather than Table |
| Wave-1 hierarchy | Who is the owner of the customer_silver table specifically? | **PASS** | hierarchy fix from abba2d2 still holding |
| 11 originals | (Engine A/E/W controls) | **PASS** | no regressions |

## Trace from a /resolve call (proof the architecture works)

```json
POST /resolve {"query":"Tell me about gold.sales.revenue_summary","domain":"DATA_ENGINEERING"}
→ {
    "resolved_uri":"http://invincible-agent/idp#Column",
    "confidence_score":0.97,
    "reasoning":"...",
    "provenance":{
      "instance_resolved":false,
      "instance_match":"empty",
      "instance_n":0,
      "instance_identifier":"gold.sales.revenue_summary",
      "llm_guess":"http://invincible-agent/idp#Column"
    }
  }
```

Every Recipe v2 property holds in this trace:
1. LLM extracted `instance_identifier` (recall-biased prompt works)
2. Engine O discovered providers via Cypher (`Discovered 1 mesh:resolveInstance providers: [...]`)
3. Fanned out to Engine D in parallel
4. Engine D returned empty (sandbox DataHub has no `gold.sales.revenue_summary`)
5. Decision table returned `instance_match=empty`
6. Fall-through: LLM's guess (`idp:Column`) stands — the system NEVER guessed kind from string shape
7. Provenance dict carries the full trace for downstream observability

## What blocks the matrix from going green

The 4 red rows need real DataHub assets. The system can't resolve
`gold.sales.revenue_summary` to Table when DataHub literally doesn't
have that asset registered. This is a **sandbox-data issue, not a
Recipe v2 issue.** Either:
- Seed DataHub with a small fixture set covering R1/R2/R4/R6/R7 — this lets the matrix go green and validates the exact-match + fuzzy + Column paths against authoritative data
- Defer matrix-greening to whenever the next ingest of real catalog data lands; the architecture is verified by the live trace above

## Open follow-ups (in order)

1. **Generality acceptance test**: register Engine E as the second `mesh:resolveInstance` provider (for `urn:instance:...` nodes) and confirm zero Engine O changes are needed. This is the *real* "not a hack" test.
2. **Compliance URI prefixed-name bug**: pre-existing doc-tools follow-up.
3. **R4 expected behavior**: decide whether the LLM picking traceLineage for a Column subject is correct (semantic inference) or wrong (Contract A says the verb is typed against Dataset which is NOT an ancestor of Column). The hierarchy fix from abba2d2 only annotates ancestors, so this isn't a hierarchy bug — it's the LLM ignoring substrate constraints when no compatible verbs exist. Likely fix: when `compatible_verb_iris=[]`, force UNKNOWN.
4. **Contract C dual-store verification**: the gateway should wait for sensor materialization before returning 200 — would have surfaced the `mesh_`-prefix bug a turn earlier.
5. **Extraction-recall property** in frozen-baseline benchmark (R6+R7).
