# ADR-0018 — Symmetric SPO routing (restore ADR-0004 subject classification, retire VerifyVerbChoice)

**Status:** Accepted
**Date:** 2026-06-07
**Deciders:** Platform team
**Related:**
  - [ADR-0004](ADR-0004-predicate-graph-routing.md) — the original predicate-graph design that
    proposed BAML+TypeBuilder for both subject AND verb classification.
  - [ADR-0008](ADR-0008-routing-fallback-policy.md) — the yellow-zone /
    `VerifyVerbChoice` band-aid we're retiring here.
  - [ADR-0009](ADR-0009-sunset-classification-axes.md) — the Step F'.6
    simplification that introduced the asymmetry this ADR closes.

## Context

ADR-0004 proposed a symmetric routing layer: a single BAML call with
TypeBuilder dynamic enums for both subject ontology classes and
predicates (verbs) would map a user query to `(subject_uri,
verb_label)`, then a Cypher path-find over the predicate graph would
return the engine sequence. **Two constrained-enum classifications,
one mechanism.**

[ADR-0009](ADR-0009-sunset-classification-axes.md) Step F'.6 then made
two divergent decisions on the subject and predicate sides:

- **Subject:** kept the two-stage pattern. `/resolve` runs Weaviate
  hybrid over the `OntologyClass` collection to get top-10
  candidates, builds a `TypeBuilder` dynamic enum from them, calls
  `b.ClassifyDomainIntent` (LLM constrained to that enum), returns
  `(subject_uri, confidence, reasoning)`. Vector-recall + LLM-precision.
- **Verb:** dropped the LLM step. `/search_predicates` runs Weaviate
  hybrid over the `Predicate` collection and returns the BM25 top
  score directly. No LLM, no constrained-enum classification, no
  reasoning trace. The supervisor used the BM25 score as its routing
  decision.

The rationale at the time (paraphrased from ADR-0009's alternatives
section):

> Constrained generation: feed the LLM the list of registered verbs
> and force it to pick one. Rejected. Risk of the LLM picking from
> misfits when nothing fits.

But that rejection rationale wasn't a "subject vs verb" argument —
it was a generic "constrained enums force bad picks" worry. The same
concern would apply equally to subjects. It didn't. The subject side
kept the pattern; the verb side dropped it.

[ADR-0008](ADR-0008-routing-fallback-policy.md) added a yellow-zone
band: when the BM25 score landed between two operator-tunable
thresholds (default `[0.4, 0.85]`), the supervisor called a separate
BAML function `VerifyVerbChoice` to second-guess the BM25 top-1. The
function was a band-aid for the missing LLM-precision step on the
verb side — and it only fired in the yellow band, so confidently-
scored-but-wrong matches sailed through untouched.

The asymmetry compounded into a series of routing regressions
through 2026 (mesh:traceLineage scoring 0.71 for "what tables do
you have?", mesh:describeAsset scoring 1.44 for "describe procedure
TEST-1234", every one of which routed to the wrong engine because
BM25 over verb synonyms couldn't tell substrate fit from lexical
proximity). [ADR-0017](ADR-0017-presentation-as-predicate.md) closed
a different symmetry gap on the rendering side; this ADR closes the
one on the routing side.

## Decision

**Restore the symmetry.** The verb-side routing path adopts the same
vector-recall + LLM-precision pattern the subject side has used since
ADR-0009. The `VerifyVerbChoice` BAML function and the yellow-zone
threshold band are retired.

### Engine O — new endpoint

`/classify_predicate` mirrors `/resolve`:

```
POST /classify_predicate
  body: { query, subject_uri, subject_reasoning, entitled_domains, domain }
  →
    1. predicate_hybrid_search(query, entitled_domains, limit=10)
       — Weaviate BM25 over the Predicate collection, filtered by
       entitled_domains.
    2. tb = TypeBuilder()
       for cand in candidates:
         tb.Predicate.add_value(cand.verb_iri).description(
           cand.description + verb_type + input_uri + owner_persona
         )
       tb.Predicate.add_value("UNKNOWN").description("none fit")
    3. result = b.ClassifyPredicate(query, subject_uri,
                                    subject_reasoning, domain,
                                    baml_options={"tb": tb})
    4. return {
         resolved_verb_iri:     result.resolved_verb_iri,
         confidence_score:      result.confidence_score,
         reasoning:             result.reasoning,
         predicate:             <matching Weaviate record>,
         candidate_verb_iris:   [...],
       }
```

The LLM sees the verb's `description + input_uri + owner_persona` as
each enum value's description. It can reason about substrate fit ("a
verb whose description says 'operates on catalog assets' does not
belong on a WorkInstruction") rather than lexical proximity.

### BAML — new function, deleted function

Added:

```baml
enum Predicate { @@dynamic }

class PredicateClassification {
  resolved_verb_iri Predicate
  confidence_score float
  reasoning string
}

function ClassifyPredicate(
  query: string,
  subject_uri: string,
  subject_reasoning: string,
  domain: string,
) -> PredicateClassification {
  client MainAgent
  prompt #" … "#
}
```

Deleted:

- `VerifyVerbChoice` function
- `VerbVerificationResult` class

### Supervisor — single-threshold dispatch

The supervisor's `execute_subtask` now follows the same shape as
before but with a different routing call and a simpler threshold:

```
routing_query = sub_query
routing_domain = entitled_domains[0]   if entitled_domains else "MAINTENANCE"
status, predicate, telemetry = _classify_route(
    context, routing_query, entitled_domains, routing_domain,
)

if status == INFRA_ERROR:    abort with INFRA_ERROR signal
if status == NO_MATCH:       fall back to Engine A (no_predicate_matched)

score = predicate["score"]    # this is now the LLM's confidence
if score < THRESHOLD:        fall back to Engine A (low_confidence)
else:                        dispatch to specialist
```

`_classify_route` orchestrates the two HTTP calls:

```
subject_uri, subject_conf, subject_reason = _resolve_subject(query, domain)
       # → POST /resolve
verb_iri, verb_conf, verb_reason, predicate
    = call POST /classify_predicate with subject context
```

The yellow-zone band (`PREDICATE_FALLBACK_SCORE_THRESHOLD_HIGH`),
`_verify_verb_choice_with_baml`, and the `from baml_client import b`
import in the supervisor are all removed. The supervisor now makes
no BAML calls of its own; Engine O owns every LLM call in the
routing layer.

### Threshold semantics change

The remaining `PREDICATE_FALLBACK_SCORE_THRESHOLD` (default 0.4) now
applies to the **LLM's emitted confidence**, not a BM25 score. They
are not directly comparable. Plan to retune against the LLM's
actual confidence distribution rather than reusing the BM25-era
default; the operator-facing semantics ("below threshold, fall back
to generalist; above, dispatch specialist") stay the same.

## Consequences

**Wins:**

- **Routing is now SPO-aware.** The verb classifier sees both the
  query and the resolved subject, so it can reject substrate
  mismatches even when the verb's name and the query share tokens.
  The "describe" → `describeAsset` confidently-wrong pattern goes
  away because the LLM rejects the verb on substrate grounds.
- **The yellow-zone band is gone.** One threshold instead of two,
  one decision path instead of three. The audit trail simplifies:
  every routing decision emits one structured-log record with
  `subject_uri, subject_conf, verb_iri, verb_conf, candidates,
  reasoning`. The router becomes testable as a parametrized HTTP
  call (see "Test gate" below).
- **VerifyVerbChoice + helpers retired.** The "second-guess gate
  over BM25" was always a band-aid for the missing precision step
  on the verb side. Deleting it removes a code path with its own
  failure modes (OpenRouter key missing, Ollama model name wrong,
  graceful-degradation pitfalls — every one of those bugs was real
  this week).
- **Code-symmetry-restored.** `/resolve` and `/classify_predicate`
  are now near-mirror images of each other. Future improvements
  (caching, batching, retry policy) apply to both.

**Costs:**

- **Net +1 LLM call per subtask routing**. Before: BM25 search +
  occasional `VerifyVerbChoice` in the yellow band (~0.3 calls avg).
  After: 2 LLM calls always (`ClassifyDomainIntent` for subject,
  `ClassifyPredicate` for verb). On the sandbox's local-Ollama
  setup this is a non-cost; on a pay-per-token cloud LLM this is
  ~+1.7 calls per subtask of upfront tokens.
- **Latency:** 2 sequential LLM calls add 500ms–2s of upfront latency
  vs the prior BM25-only path. Acceptable for current per-query
  latency budgets (~3–10s for the agent's reasoning loop dominates).
- **Threshold semantics changed.** Operators tuning
  `PREDICATE_FALLBACK_SCORE_THRESHOLD` against BM25 histograms have
  to re-tune against the LLM confidence distribution. The default
  0.4 is a holding value; the next operator-tuning cycle should pick
  the right value from observation.
- **A new BAML function to maintain.** `ClassifyPredicate`'s prompt
  has to be kept aligned with the registered verb set. Misalignments
  show up as confidence drops in the structured-log audit trail and
  as failures in the routing test gate.

## Alternatives considered

- **Keep BM25, fix it with anti-synonyms + better synonym curation.**
  Rejected. That's what we already did in the previous routing-
  failure cycles and it doesn't scale — every new verb needs hand-
  tuned anti-synonyms and the failure surface keeps shifting.
- **Keep BM25, run `VerifyVerbChoice` on *every* result (not just
  the yellow band).** Rejected. It would close the substrate-fit
  gap by always asking the LLM to second-guess BM25 — same effect
  as restoring the LLM precision step, but with more code and a
  more fragile control flow.
- **Single combined `ClassifyRoute` call producing both subject and
  verb in one round-trip.** Deferred as a future optimization
  (ADR-0018 follow-up). Halves the upfront LLM cost (2 → 1) and
  may improve quality (the LLM reasons about the (S, P) pair
  holistically) but couples the subject and verb enum schemas
  more tightly. Implement after the two-call version is validated
  in production and the routing test gate (next section) has a
  baseline confusion matrix.
- **Subject as a hard filter on `/search_predicates`** (filter
  predicates whose `input_uri` matches the resolved subject before
  BM25 ranks). Deferred. Requires a non-trivial input_uri ⇔
  ontology_class mapping that the registrations don't currently
  carry (Engine E's `input_uri="mesh:GraphQuery"` ≠ resolved
  `:WorkInstruction`). Predicate input_uri schema cleanup is a
  separate ADR item.

## Test gate

The previous router had no parametrized test gate, which is the
direct reason every routing failure surfaced in production rather
than in CI. This ADR comes with a regression test suite that
exercises `/resolve` + `/classify_predicate` against a corpus of
known queries with expected `(subject_uri, verb_iri)` outcomes.

The suite lives at `tests/routing/test_classify_route.py`. Each test
case is a `(query, expected_subject_uri, expected_verb_iri,
expected_confidence_min)` tuple. The suite is parametrized so adding
a new failure mode is one line. CI runs it against a sandbox
deployment of Engine O. A failed test indicates one of:

- A new verb registration that conflicts lexically/semantically
  with an existing one.
- A drift in the LLM's classification stability (model swap,
  prompt change, etc.).
- A real bug in `/resolve` or `/classify_predicate`.

The suite is required to pass on master. It is the bar this ADR's
implementation has to clear.

## Indicators for revisiting

- **LLM confidence distribution is bimodal at the threshold**, i.e.
  many decisions cluster just below 0.4 and many just above. The
  threshold is in the wrong place; the operator should tune.
- **Routing latency dominates total query latency.** If the 2 LLM
  calls upfront are noticeably user-facing, accelerate to the
  combined `ClassifyRoute` call (ADR-0018 follow-up).
- **A class of substrate mismatches is consistently routed wrong.**
  Update the verb's description / input_uri / owner_persona on
  registration; the LLM uses those as the enum value description
  when picking. Don't write synonyms as a workaround.
- **`UNKNOWN` rate is sustained above ~10–15%** of all routing
  decisions. Either the registry is undercovered (engines don't
  serve queries users are asking) or the LLM's reasoning is
  rejecting on bad grounds (prompt or model issue). The structured-
  log `routing_decision` records the LLM's reasoning text — the
  operator triages from that.

## Migration plan

Status: **implemented** in the same commit that flips this ADR to
Accepted. Reference the corresponding diffs in:

- `baml_shared/baml_src/contracts.baml` — `ClassifyPredicate`
  function added; `VerifyVerbChoice` + `VerbVerificationResult`
  deleted.
- `agent_fleet/ontology_service/main.py` — `/classify_predicate`
  endpoint + `ClassifyPredicateRequest` + `ClassifyPredicateResponse`
  added.
- `src/iagent/defs/dynamic_supervisor.py` — `_resolve_subject` and
  `_classify_route` helpers replace `_resolve_predicate_endpoint`;
  `_verify_verb_choice_with_baml` deleted; `execute_subtask`'s
  yellow-zone branch deleted.
- `tests/routing/test_classify_route.py` — parametrized routing
  regression suite (the test gate).

Engines unchanged. Frontend unchanged. Helm values:
`PREDICATE_FALLBACK_SCORE_THRESHOLD_HIGH` removed
(`PREDICATE_FALLBACK_SCORE_THRESHOLD` keeps the same meaning but
applies to LLM confidence rather than BM25 score).
