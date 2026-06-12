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

## Architect correction (2026-06-13 late) — the "stochasticity" framing was wrong

The original write-up above said the 4 matrix failures "look like LLM
stochasticity." That framing missed a contradiction in its own
evidence: a direct ``/resolve`` curl returned WorkInstruction with
**full phone-book provenance** (instance leg fired); the matrix's
calls saw ``provenance=null`` (instance leg did NOT fire) for the
same query. Those cannot both be stochasticity — if the override
fires, the LLM's guess is *replaced*; sampling variance in the guess
is irrelevant. Same-input-different-path means something differs
between the callers.

Diagnosed by ruling out each candidate:

  - **Replicas:** single Engine O pod, single endpoint. Ruled out.
  - **Model / env:** SMOLAGENTS_MODEL=gpt-oss-128k:120b on the
    running pod, same value everywhere. Ruled out.
  - **HTTP library / payload:** `requests.post(json=...)` 5/5
    deterministic with full provenance (identical to the matrix's
    ``_post``). Ruled out.
  - **Timeout strangle pattern:** ``instance_match=timeout`` would
    have appeared in provenance; provenance was ``None``, not
    ``timeout``. Ruled out.

Running ONE failing row in pytest by itself surfaced a much more
specific reason — a different reasoning string than the matrix's
full-run output:

> "Conjunctive-read invariant: Neo4j marks
> ``[mesh:queryKnowledgeGraph]`` as compatible with the resolved
> subject, but **none of those verbs survived the Weaviate
> intersection** (registered in Cypher but not in the predicate
> search index)."

That's the conjunctive invariant firing — and pointing at Weaviate's
side as the missing half. Direct Weaviate inspection confirmed the
row EXISTS with correct properties (saga wrote it cleanly).
``predicate_hybrid_search`` uses BM25 (the sandbox Weaviate has no
vectorizer enabled), and ``mesh:queryKnowledgeGraph``'s registered
``verb_synonyms`` were ``[query graph, graph lookup, cypher query,
find in graph, knowledge graph search]`` — none of which BM25-match
"procedure", "work instruction", "maintenance steps", "diagram".
The row was BELOW the limit cutoff in BM25 ranking, so the
compat-filter intersection was empty, so Contract B fired UNKNOWN.

This is the conjunctive invariant **working as designed**. The
pre-v0.2 fabrication fallback at ``/classify_predicate`` was
synthesizing the verb into the LLM's enum when BM25 missed it; that
was the workaround whose removal the ADR amendment specified. The
synonym gap was hiding behind the fallback for as long as the
matrix has existed. Removing the fallback surfaces the real
registration gap at Engine E.

Fix shipped 3acd985: expand engine_e_neo4j_expert's
``verb_synonyms`` to cover the standing matrix's MAINTENANCE-domain
question grammar (procedure, work instruction, maintenance steps,
diagram, rotor assembly, etc.). Engine E re-rolls and re-registers
through the v0.2 saga; BM25 will now surface
``mesh:queryKnowledgeGraph`` for procedure queries; intersection
includes it; LLM picks it.

## The positive-control amendment

The architect's correction also pointed at a structural gap in the
standing-guard discipline: the resolve_instance probes hit each
provider's ``/resolve_instance`` endpoint directly. They proved the
providers *answer*; they proved nothing about whether Engine O's
instance leg *consults them* on a real ``/resolve`` call. The four
red rows were accidentally the only test exercising the router-side
integration under matrix conditions, and they were red while the
probe stack was green.

The rule, saved to memory at
``feedback_abstention_needs_positive_control.md``:

> The positive control must exercise the INTEGRATED PATH, not just
> the component. A probe that bypasses the consumer can stay green
> while the consumer is broken.

Standing guard to add as a follow-up: a router-side probe that
asserts ``instance_resolved=true`` flows through ``/resolve`` itself
(not through the provider's endpoint). Queued below.

## Outstanding morning items (corrected priority order)

1. **Verify the synonym fix lands**: matrix passes 18/18 again. If
   it does, the conjunctive invariant + the fix are both correct;
   if not, dig further. Running now in background bo9ki7m5x.
2. **Add the router-side integration probe** that exercises
   ``/resolve``'s phone-book leg end-to-end. The architect's
   amendment to the positive-control rule says any component-
   bypassing probe needs a matching integration probe.
3. **Authorize the orphan-edge DELETE** — only AFTER #1 confirms
   the synonym fix doesn't depend on edge identity in any
   unexpected way. Snapshot the matching edges first (5min
   reversibility insurance). Run matrix before and after; predict
   no movement.
4. **v0.2.1 Restate VirtualObject wiring** — polish, conjunctive
   invariant makes safety class identical with or without.

## What I'd strike from the prior queue

The "widen the expected-subject set" option I had listed at #2 was
exactly the wrong call: it would have relabeled the suite to accept
the fallback path's output as correct, hiding the integration gap
behind a loosened assertion — the literal definition of
green-for-the-wrong-reason, the thing R6's provenance-tighten
exists to prevent. The architect was right to strike it.
