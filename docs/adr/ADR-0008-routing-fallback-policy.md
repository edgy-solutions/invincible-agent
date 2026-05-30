# ADR-0008 — Routing fallback policy (LLM as generalist fallback)

**Status:** Proposed
**Date:** 2026-05-30
**Deciders:** Platform team
**Related:**
  - [ADR-0004](ADR-0004-predicate-graph-routing.md) — the predicate
    graph is the routing mechanism; this ADR decides what to do when
    it returns nothing useful.
  - [ADR-0009](ADR-0009-sunset-classification-axes.md) — the cleanup
    that made `/search_predicates`'s signal trustworthy (no silent
    degradation), which is the precondition for a fallback policy to
    fire on real misses instead of false negatives.

## Context

ADR-0009 Step F'.6 made Engine O's `/search_predicates` honest:

- It returns ranked candidates with Weaviate hybrid scores when there
  is a match.
- It returns `found=false` when no predicate matched the user's NL
  under the caller's entitled domains.
- It returns 503 when Weaviate (the routing accelerator) is
  unavailable.

The Cypher exact-match fallback was deliberately removed so the
supervisor sees the *real* routing signal, not a silently-degraded
proxy.

That decision exposed a question we deferred when ADR-0009 was first
written: **what does the supervisor do when routing legitimately
fails?** Today, `dynamic_supervisor.py:execute_subtask` aborts the
subtask with a "no registered predicate matches" response. That's a
correct failure mode for true misses, but it's also a brittle UX —
the user gets a hard error for any query that happens to fall outside
the registry's verb coverage, even when a free-form analyst could have
done something useful.

ADR-0009's claim that this question was "folded into Step F'" was
premature. Step F'.6 answered "what does Engine O return on a match?"
It did not answer "what does the supervisor do on a miss?" That's
this ADR's scope.

The user direction during ADR-0009 implementation was:
> "off the top of my head I am tempted to say use the LLM"

— meaning a generalist agent should pick up where the predicate-graph
left off. The remainder of this ADR is the design of *which* misses
trigger the fallback, *what* the fallback does, and *how* operators
see when it's firing.

## Decision

When `/search_predicates` does not produce a confidently-matched
predicate, the supervisor routes the subtask to **Engine A as a
generalist fallback** — instead of aborting. The fallback is
**flagged** (Engine A knows it is the fallback path) and **observable**
(a counter exposes the fallback rate as a first-class signal).

### When the fallback fires

| Engine O response | Fallback? | Why |
|---|---|---|
| `found=true`, top score ≥ threshold | **No** | Confident match — use it. |
| `found=true`, top score < threshold | **Yes** | Routing is guessing; Engine A may do better than a low-confidence specialist. |
| `found=false` (no match) | **Yes** | Query is outside registry coverage; Engine A is the only honest answer. |
| HTTP 503 (Weaviate unavailable) | **No** | Infrastructure outage. Fail loud; do **not** mask with the fallback. Same reasoning that drove ADR-0009's Cypher-fallback removal — silent degradation hides the real signal. |
| HTTP 5xx (Engine O bug) | **No** | Bug in the registry layer. Fail loud. |
| Routing succeeded but the matched engine returned an error | **No** | The matched engine had its chance. Re-routing through the fallback would mask engine-specific failures (mem0 errors, BAML schema mismatches) as generic "no specialist" misses. |

### What the fallback does

The supervisor calls Engine A's `/analyze` endpoint with the original
`sub_query` and these additional fields:

```http
POST {ENGINE_A_URL}/analyze
X-Fallback-Reason: no_predicate_matched | low_confidence
X-Fallback-Score: <float | "none">  # the rejected top-score, if any
X-Fallback-Query: <original verbatim>
```

Engine A's smolagent prompt adapts: it knows the registry did not have
a specialized tool for this NL and acts as a generalist. The prompt
shift is small (a sentence in the system prompt) but matters for tone
and uncertainty calibration — a fallback response should say "I am
answering as a generalist because no registered tool matched your
request" rather than presenting as authoritative.

### Where the threshold lives

The score threshold is **a supervisor-side policy**, not a registry
concern. Engine O always returns the raw Weaviate hybrid score; the
supervisor decides whether the top hit is "good enough" via an
environment variable:

```
PREDICATE_FALLBACK_SCORE_THRESHOLD=0.40   # default; operator-tunable
```

Engine O does not interpret the threshold. Rationale: keeps Engine O's
job pure (retrieval over the registry) and keeps routing policy
together (the supervisor already owns "which predicate, which engine,
what payload").

### Telemetry

The fallback is a first-class signal, not a hidden behavior:

```
predicate_fallback_total{reason="no_match"}     counter
predicate_fallback_total{reason="low_score"}    counter
predicate_routing_score                          histogram
```

Operators looking at the dashboard can answer:

- "What fraction of user queries are hitting the generalist fallback?"
- "Is the score distribution drifting down (registry coverage shrinking)?"
- "Is the fallback rate spiking (telemetry signal of a misregistered
  engine or a vocabulary gap)?"

If `predicate_fallback_total` ratio drifts above ~30% sustained, the
registry has a coverage problem and the response is to register more
predicates or expand existing synonym lists, **not** to lower the
threshold to mask the signal.

## Consequences

**Wins:**

- Real failure modes (Weaviate outage, registry bug, engine error)
  surface loud — the fallback only catches the *registry-coverage*
  miss case, which is exactly what an LLM is good at.
- Users get useful responses for queries outside the registry's verb
  coverage instead of a hard "no match" error.
- Fallback rate becomes a coverage-quality signal we can act on.
- Engine A's existing smolagent loop already handles "no specialist
  tool available" gracefully — the change is a prompt shift, not a
  new code path.
- Threshold is operator-tunable without a deploy; we can A/B different
  thresholds against the fallback-rate counter to calibrate.

**Costs:**

- Engine A becomes load-bearing for the fallback path. If Engine A is
  down, fallback queries fail; specialist routing still works. Engine
  A's reliability is already a hard requirement (it serves the
  `mesh:analyzeWithCodeAgent` predicate too), so this doesn't add a
  new SPOF.
- The threshold is a calibration knob that needs initial tuning. The
  0.40 default is a starting guess; the histogram will inform a real
  number in the first week of operation.
- Engine A's prompt now has two modes (specialist vs generalist
  fallback). Keep the divergence to a single conditional block — a
  full prompt fork is over-engineering.

## Alternatives considered

- **Abort the subtask on every miss (current behavior).** Rejected.
  Treats "vocabulary gap" the same as "user asked for something
  genuinely impossible." Users have no way to tell which they hit, and
  ops has no signal to act on coverage gaps.
- **Constrained generation: feed the LLM the list of registered verbs
  and force it to pick one.** Rejected during ADR-0009 Step F'.6
  drafting in favor of Weaviate hybrid; revisiting it as the *fallback*
  mechanism would re-introduce the constraint problem (LLM forced to
  pick from a list of misfits) without the Weaviate signal that proved
  it was a misfit in the first place. The verb is already gone; the
  user needs a useful answer, not a forced-match.
- **Fall back to the second-best Weaviate hit if the top is below
  threshold.** Rejected. If the top hit is low-confidence, the
  second-best is even lower; "shop down the list" buys nothing.
- **LLM disambiguation pass: ask the LLM "given these N low-score
  candidates, which is most relevant?"** Considered — could be added
  later as a refinement when fallback rate is high and the operator
  team wants finer-grained recovery. Out of scope for the initial
  policy decision; capture as a follow-up after we see real data.
- **Silently widen the entitled-domains filter (drop the scope check
  on miss).** Rejected. Scope is an authorization decision, not a
  fuzzy hint. Silently dropping scope on a miss is a security
  regression.

## Migration plan

1. Add `PREDICATE_FALLBACK_SCORE_THRESHOLD` to the supervisor's
   `SupervisorQueryConfig` with the 0.40 default.
2. In `dynamic_supervisor.py:execute_subtask`, replace the
   `predicate is None` abort branch with:
   - If `predicate is None` (Engine O reported `found=false`) → call
     Engine A with `X-Fallback-Reason: no_predicate_matched`.
   - Else if `predicate.score < threshold` → call Engine A with
     `X-Fallback-Reason: low_confidence`.
   - Else → existing route to the matched engine.
3. In Engine A (`agent_fleet/restate_analyst`), read the
   `X-Fallback-Reason` / `X-Fallback-Score` headers and prepend a
   single-sentence "you are operating as a generalist fallback because
   …" block to the smolagent system prompt when set.
4. Add the three telemetry instruments (`predicate_fallback_total`
   counter with `reason` label, `predicate_routing_score` histogram).
5. Document the threshold and the fallback semantics in the supervisor
   readme so operators can find the knob.

## Indicators for revisiting

- **`predicate_fallback_total` ratio sustained above ~30%** of all
  routed subtasks. That's a registry-coverage problem masquerading as
  a working system; the response is to expand coverage, but the
  observation should also prompt a re-read of this ADR to see whether
  the threshold or the fallback target is part of the issue.
- **Engine A becomes the dominant routing target** (more fallback
  traffic than specialist traffic). At that point either the registry
  is grossly under-populated or the threshold is too high.
- **A specialist engine's domain gets perpetually preempted by the
  fallback** because its synonyms / description don't score well
  against typical user phrasings. Indicates the embedding text
  composition (humanized verb + synonyms + description) needs a
  contribution from the engine team rather than a threshold change.
- **PingSSO claims expand** (per [ADR-0009](ADR-0009-sunset-classification-axes.md))
  and `entitled_domains` becomes a real scope. The current ADR
  assumes domain scope rarely makes a confident match fall below
  threshold; if domain-shaped queries reliably bottom out, the
  threshold-versus-scope interaction needs a new look.
