# Gateway v0.2 — Cutover Day Status

**Date:** 2026-06-13 overnight
**Decision:** ADR-0006 §Addendum rollback via Restate saga, conjunctive-read invariant as the load-bearing safety fact.

## What shipped

| # | sha | scope |
|---|-----|-------|
| 1 | 52de1e4 | ADR redraft (decided fork, four additions, fabrication caveat) |
| 2 | 2e146d4 | Gateway v0.2 saga + helm Restate config + saga unit tests (7/7) |
| 3 | 2e08241 | SDK retry semantics |
| 4 | 4cb0970 (doc-tools) | aitool sensor retirement |
| 5 | 32d257a | fabrication removal + conjunctive-read invariant test |
| 6 | d65b360 | cutover diff harness (Step 3) |
| 7 | 7ff7daa | dual-import fix for v2_saga / v2_substrate |
| 8 | 7100598 | Weaviate factory fix (host:port form) |
| 9 | 91bfb6b | harness aliasing bug fix |

## Cutover verification stack

| Stage | Result |
|---|---|
| mesh-registrar rolled with v0.2 saga | ✅ |
| doc-tools rolled with sensor retired | ✅ |
| engine-o rolled with fabrication removed | ✅ |
| All 5 fleet engines re-rolled, registered via saga | ✅ — 14 v0.2 saga registrations in 0.18–0.66s each |
| Probes (3/3) | ✅ engine_d + 2× engine_e all return correct class + provenance |
| **Conjunctive-read invariant (3/3)** | ✅ Neo4j-only, Weaviate-only, both-present all behave per the safety property |
| Cutover diff harness | Mixed — see below |
| Full matrix | 14/18 — see below |

## Conjunctive-read invariant test green

**This is the load-bearing safety acceptance.** The three tests in
`test_conjunctive_read_invariant.py` directly insert synthetic
substrate writes and verify:

- A Neo4j-only edge (Weaviate row missing) **does NOT** enter the
  LLM's constrained enum.
- A Weaviate-only row (Neo4j edge missing) **does NOT** enter the
  LLM's constrained enum.
- A both-present registration **does** reach the enum (control —
  ensures the filter doesn't become overly strict).

The safety argument the rollback decision rests on is now empirically
verified and guarded.

## Cutover diff — the masks-rule prediction landed

The diff harness surfaced the discrepancy the ADR amendment predicted:
pre-v0.2 sensor-materialized orphan edges sitting next to the fresh
v0.2 saga writes. Sample for `mesh:lookupOwnership`:

```
{tool_urn: None, url: http://restate-agent-svc.../analyze, provider: None}
{tool_urn: None, url: http://restate-agent-svc.../analyze, provider: None}
{tool_urn: urn:li:mlModel:(...,engine_a_lookup_ownership,PROD), url: http://restate-agent-svc.../analyze, provider: engine_a}
```

Three edges per verb is the modal pattern: two pre-v0.2 orphans
(allowlist drift + a44b9fb-era match-key collision) plus one fresh
v0.2 saga edge. The orphans don't degrade routing because
`/find_compatible_verbs` DISTINCTs by verb_iri and both edges point
at the same engine endpoint, but they pollute the substrate-invariant
test from ce599d0 once we re-enable strict checking.

**Auto-mode blocked the mass-DELETE cleanup** — correctly, the user
never explicitly authorized a destructive write on the shared
sandbox. Cleanup is queued as a morning decision. The proposed
Cypher:

```cypher
MATCH ()-[r]->()
WHERE r.iri IS NOT NULL
  AND r.iri STARTS WITH 'mesh:'
  AND r._tool_urn IS NULL
  AND r.endpoint_url IS NOT NULL
DELETE r
```

## Matrix regression — 14/18 (down from 18/18 yesterday)

Four rows failed, all in the MAINTENANCE domain, all with the same
failure mode: subject resolved to `mro:ProcedureStep` (no compat
verbs) → Contract B short-circuit → UNKNOWN.

| Row | Failure |
|---|---|
| R8 — Tell me about procedure TEST-1234 in detail | subject was supposed to be `WorkInstruction` via Engine E phone book |
| Describe procedure TEST-1234 and show me its diagram | same shape |
| What is the work instruction for procedure 1234? | same shape |
| Show me the maintenance steps for the rotor assembly | LLM picks ProcedureStep semantically — definition says "ordered actions" |

### Curious mismatch

A direct curl against `/resolve` for the failing R8 query returns the
correct WorkInstruction subject with full Engine E phone-book
provenance:

```json
{"resolved_uri":"https://spec.industrialontologies.org/.../WorkInstruction",
 "confidence_score":0.97,
 "reasoning":"Routed via mesh:resolveInstance (match=exact, provider=engine_e)...",
 "provenance":{"instance_resolved":true,"instance_match":"exact",
   "instance_provider":"engine_e", ...}}
```

But the matrix run for the same query shows `subject_uri =
mro:ProcedureStep` and `resolve_provenance = {}` — the phone book
didn't fire. Either the BAML extraction is non-deterministic for
this exact phrasing OR there's an Engine O state divergence between
the matrix's calls and my direct curls. The conjunctive invariant
itself is fine (the test passes) — this is about WHICH subject the
resolver picks before the conjunctive filter applies.

### Why this is not (yet) a v0.2 issue

The matrix passed 18/18 yesterday. My v0.2 changes touched:

- `/classify_predicate` — fabrication fallback removed
- `mesh-registrar` — saga added
- `doc-tools sensor` — retired

The failures land at `/resolve`'s LLM call (subject pick), which my
changes don't touch. The compat-walk from `mro:ProcedureStep` returns
empty because ProcedureStep has no `subClassOf` parents AND no verbs
typed against it — this was true yesterday too. Yesterday's pass means
the LLM picked `WorkInstruction` (which DOES have queryKnowledgeGraph
typed against it). Today the LLM picks `ProcedureStep`.

Hypotheses worth checking in the morning:

1. **LLM temperature drift** — the Weaviate Predicate rows v0.2 wrote
   shouldn't affect OntologyClass hybrid search (different collections),
   but verify no cross-contamination.
2. **OntologyClass description drift** — did the maintenance_extension
   ingest re-fire and update ProcedureStep's description to attract
   "rotor assembly" + "maintenance steps" queries more strongly?
3. **Subject substring tolerance** — the existing matrix rows already
   allowed either WorkInstruction OR RotorAssembly; the test fails the
   moment the LLM picks a third option. This may be a test-spec issue
   rather than a routing issue: ProcedureStep is a defensible
   classification for "maintenance steps".

## Outstanding morning items (priority order)

1. **Authorize the orphan-edge DELETE** so the substrate-invariant
   test can be re-enabled to strict.
2. **Decide R4 / matrix policy** — accept LLM stochasticity by
   widening the expected-subject set (WorkInstruction OR RotorAssembly
   OR ProcedureStep) OR figure out why the LLM picks differently today
   than yesterday and restore stability.
3. **Verify the helm chart's `iri` aliased-properties cleanup** — the
   substrate guards still pass but the orphans count toward total
   edges; once cleaned up, re-run the cutover diff to confirm clean.
4. **v0.2.1 Restate VirtualObject wiring** — per the ADR amendment,
   tonight shipped saga LOGIC but not the Restate durability layer.
   This is the next planned polish; not urgent because the conjunctive
   invariant makes the safety class identical with or without Restate.
