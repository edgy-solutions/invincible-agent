# ADR-0015 — Router regression testing at the `/search_predicates` layer

**Status:** Phase 1 Accepted (2026-06-04). Phase 2 (Postgres table +
canary cron + drift detection) deferred. See "Implementation status"
below.
**Date:** 2026-06-03 (proposed); 2026-06-04 (Phase 1 shipped)
**Deciders:** Platform team
**Related:**
  - [ADR-0004](ADR-0004-predicate-graph-routing.md) — the predicate-
    graph router whose behavior this ADR proposes to validate. This
    ADR is the test/observability layer that the routing design has
    been missing.
  - [ADR-0008](ADR-0008-routing-fallback-policy.md) — the fallback
    policy that fires when no predicate matches. The audit table
    proposed here is what tells us whether the fallback is firing
    too often.
  - [ADR-0014](ADR-0014-no-hardcoded-urn-hints.md) — the same family
    of problem at the prompt layer (agents claiming behavior in code
    that may not actually be served by the registry). This ADR
    extends the "registry is the single source of truth" rule to
    behavioral contracts, not just URN hints.

## Context

The predicate-graph router (Engine O `/search_predicates`) picks
which engine handles each subtask based on Weaviate hybrid search
over the `Predicate` collection, filtered by the caller's
`entitled_domains` and (optionally) cost class. Routing quality is
what determines whether a real user query reaches the engine that
can answer it.

What the routing decision actually depends on:

1. Each registered predicate's `description`, `verb_synonyms`, and
   `verb_local` text — the substrate for hybrid search ranking.
2. Each predicate's `domains` array — what entitlement claims
   intersect with it.
3. Each predicate's `cost_class` — used for tie-breaking and
   downranking.
4. The Weaviate vectorizer config (BM25 weights, embedding model).
5. The caller's JWT claims (`entitled_domains`, `persona`).

Any change to any of these — by a new agent registering, an
existing agent updating its description, a Weaviate index rebuild,
an embedding model upgrade, a domain-claim policy change — can
silently reroute existing question shapes to a different engine.
Engine selection is the most consequential decision in the request
path and it's currently the least observable.

### What the existing observability does and doesn't catch

| Layer | Observability today | Routing-decision visibility |
|---|---|---|
| BAML `ExtractIntent` (Engine O `/route_intent`) | Langfuse spans | ✅ full LLM trace |
| BAML `DecomposeQuery` (Engine O `/plan`) | Langfuse spans | ✅ full LLM trace |
| `/search_predicates` Weaviate hybrid + filter | none | ❌ invisible |
| Engine selection + score margin | none | ❌ invisible |
| Domain-filter eliminations | none | ❌ invisible |
| Fallback firing | logged but not aggregated | ⚠️ buried |

The most consequential layer is the least instrumented. This ADR
fixes that.

### The trigger

During the 2026-06-03 session, several catalog-Q&A queries that
should have routed to Engine A (`mesh:analyzeWithCodeAgent`) were
routed to Engine DA (`mesh:analyzeDataset`) because:

1. Engine A's `domains=["MAINTENANCE","MANUFACTURING","SUSTAINMENT"]`
   excluded it from `DATA_ENGINEERING` queries before the hybrid
   search even ran.
2. Engine DA's verb synonyms (`"data analysis"`, `"query dataset"`)
   matched catalog-Q&A questions too strongly.

Both were silent. Nothing in the logs, nothing in any dashboard,
told the team "Engine A was filtered out of 100% of DATA_ENGINEERING
queries this week" or "Engine DA is winning catalog questions by a
0.04 score margin." The misroute was discovered only because the
answers were visibly wrong (hardcoded URN hints in Engine DA's
prompt, see ADR-0014). Without that visible failure mode, the
misroute would have continued indefinitely.

### Why this is a continuous-validation problem, not a CI problem

A naive answer is "write a regression test in CI." That works for a
fixed deployment, but the iagent mesh is a long-lived production
deployment where the bulk of agent registrations happen over the
lifetime of the cluster, not at deploy time. By month two of
production:

- Several agents have updated their verb descriptions
- A few new agents have registered
- The Weaviate index has been rebalanced
- One embedding model has been upgraded

None of those changes go through a CI pipeline that gates them
behind the routing regression suite. They happen live, via
`register_engine_to_mesh()` calls at engine startup. The validation
has to happen at the same layer the registration happens — inside
Engine O, against the live registry, continuously.

## The constraint we want to keep

- **The registry is the single source of truth.** What each agent
  claims to handle has to be authoritative, not defined separately
  in a YAML file in a repo that drifts the moment the registry
  changes.
- **Routing decisions are observable as data.** Every decision
  produces a row that downstream queries can aggregate, slice, and
  alert on.
- **Drift detection is continuous, not batch.** When a new
  registration causes a routing flip, we know within seconds, not
  the next time the CI suite runs.
- **L1 only for now.** The BAML chain layer (route_intent + plan)
  and the full mesh layer (orchestrate) are out of scope for this
  ADR. Most routing regressions originate at the
  `/search_predicates` layer, and that's where the testing pressure
  belongs.

## Decision

### 1. Agents declare their behavioral contract at registration time

`register_engine_to_mesh(...)` gains an `expected_questions`
parameter:

```python
register_engine_to_mesh(
    name="engine_a_restate_analyst",
    verb="mesh:analyzeWithCodeAgent",
    description="Metadata analysis engine. Answers questions ABOUT...",
    verb_synonyms=[...],
    domains=["MAINTENANCE", "MANUFACTURING", "SUSTAINMENT", "DATA_ENGINEERING"],
    expected_questions=[
        {"q": "Who owns the customers_gold dataset?",
         "category": "ownership_lookup",
         "min_score": 0.5},
        {"q": "What is the source of truth for the Revenue dashboard?",
         "category": "lineage_traversal",
         "min_score": 0.5},
        # ... 30-50 question shapes the engine claims
    ],
)
```

These are stored alongside the existing predicate properties in the
Weaviate `Predicate` collection (or in a paired `PredicateContract`
collection if we want to keep the routing-search collection lean).
Atomic write: an engine's description and its contract update
together, so the contract can never lag the registry.

### 2. Four feedback loops, all at the `/search_predicates` layer

| Loop | Trigger | Cost | What it catches |
|---|---|---|---|
| At-registration validation | Every `register_engine_to_mesh()` call | ~10 ms per question × N questions per engine, total ~1 s | A new or updated registration causing previously-correct routings to flip |
| Canary pulse | K8s CronJob every 5 min | ~50 ms × total corpus size, ~10 s | Drift between registrations: index rebuilds, embedding model upgrades, anything that quietly changes scores |
| Real-traffic audit | Every user-driven `/search_predicates` call | additive ~1 ms (async write) | Adversarial cases, near-tie hotspots, entitlement-filter exclusions on real traffic |
| Confidence-threshold gating | At decision time | additive 0 ms | Confident-but-wrong routing protected against by refusing to commit below threshold and surfacing a disambiguation back to the user |

All four operate exclusively on `/search_predicates`. No BAML
chain, no full mesh exercise, no other engine touched.

### 3. Single audit table as shared substrate

```sql
CREATE TABLE routing_decisions (
    id              BIGSERIAL PRIMARY KEY,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    source          TEXT NOT NULL,   -- 'user_request' | 'canary' | 'registration_validation'
    request_id      TEXT,             -- trace correlation
    user_id         TEXT,             -- null for canary
    sub_query       TEXT NOT NULL,
    entitled_domains TEXT[],

    candidates_raw  JSONB NOT NULL,   -- [{engine, verb, score}, ...] before filter
    candidates_filt JSONB NOT NULL,   -- after entitlement + cost filter
    picked_engine   TEXT,
    picked_verb     TEXT,
    pick_score      REAL,
    pick_margin     REAL,             -- pick_score - second_place_score
    fallback_reason TEXT,             -- null on success

    expected_engine TEXT,             -- canary + registration only
    is_correct      BOOLEAN,          -- canary + registration only

    search_ms       INT,
    total_ms        INT
);

CREATE INDEX ON routing_decisions (occurred_at);
CREATE INDEX ON routing_decisions (picked_engine, occurred_at);
CREATE INDEX ON routing_decisions (source, occurred_at);
CREATE INDEX ON routing_decisions ((candidates_filt::text)) WHERE fallback_reason IS NOT NULL;
```

Engine O writes one row per `/search_predicates` call. The `source`
column distinguishes the three populations:

- `user_request` — real traffic, the realistic distribution
- `canary` — synthetic, the regression baseline
- `registration_validation` — fired immediately after every
  registration change, the drift detector

### 4. Soft drift policy at registration time

When a registration causes any previously-passing claimed question
(from any engine, not just the registering one) to flip:

- Log the drift as a structured event with full diff (which
  questions flipped, from which engine to which, what the score
  margin shrank to)
- Emit a Prometheus counter
  `iagent.routing.registration.drift{engine,affected_engine}`
- Accept the registration anyway

This biases toward not blocking deployments. The detection is the
value; the policy of what to do with detection can tighten later
once we have a few weeks of data on how often drift actually fires
during normal operations.

If we later want to make this stricter:

- **Quarantine mode**: accept the registration but mark the new
  predicate as `shadow=true`; it doesn't actually serve routing
  decisions until a human reviews the drift report and clears it
- **Reject mode**: refuse the registration with the drift report as
  the rejection reason; the engine operator updates their
  description or the affected engine's contract before retrying

Both are pure policy changes on top of the same detection
mechanism.

### 5. Confidence-threshold gating

The router refuses to commit below a configurable score margin
(default 0.05). Below that, instead of routing it returns the
top-K candidates to the caller (BFF / supervisor), which surfaces a
disambiguation question to the user ("did you mean: (a) catalog
metadata Q&A, (b) execute SQL on a dataset, (c) search technical
manuals?"). The user's answer becomes a labeled positive example
that can be promoted into the chosen engine's `expected_questions`
on the next deploy.

This protects against confident-but-wrong routing AND turns routing
failures into a labeled-data pipeline. Important: the threshold is
on margin (top-1 vs top-2), not on absolute score. A 0.9 score that
beats top-2 by only 0.02 is still ambiguous; a 0.4 score that beats
top-2 by 0.3 is unambiguous.

## Implementation status

**Phase 1 (Accepted 2026-06-04)** — structured-log substrate. Every
`/search_predicates` call in Engine O emits a single-line JSON record
with the exact column shape of the Phase 2 SQL DDL below. The emit
goes to stdout via a dedicated logger
(`iagent.routing.audit`); kubectl logs / fluentbit / Loki / Datadog /
Langfuse all pick it up unchanged. Aggregation queries are immediate
("how many decisions had margin < 0.05 last hour" = log query, not
SQL — but the SQL DDL below is what makes the migration mechanical
when Phase 2 lands).

Phase 1 also lets the consumer side close ADR-0017's
`X-Presentation-Path` loop: cortex-bff already reads the header and
puts it in Dagster `Output.metadata`, and a follow-up commit will
have cortex-bff emit its own `routing_decision` log line with
`source='presentation_decision'` and the `picked_engine` set to the
chosen presentation path. Same audit shape, two emitters.

Schema additions made to support Phase 1 emit:
[`SearchPredicatesRequest`](../../agent_fleet/ontology_service/main.py)
gained three optional fields: `request_id` (trace correlation),
`user_id` (slicing the audit log per caller), `audit_source`
(`'user_request' | 'canary' | 'registration_validation'`, default
user_request). All existing callers continue to work without
migration.

What Phase 1 does NOT yet have, and why deferring is okay:

- **Postgres table.** Adds a non-trivial Engine O ↔ Postgres
  dependency (connection pool, migration, async write worker,
  failure modes). The structured-log substrate satisfies the
  per-decision visibility goal today; Phase 2's value is aggregate
  queries that don't go through log search. Defer until either the
  log-search latency becomes painful OR ADR-0016 §5's revisit
  trigger needs SQL-shaped queries the log system can't serve.
- **Canary pulse + K8s CronJob.** The audit emit shape is ready —
  `audit_source='canary'` is wired — but the canary endpoint and
  CronJob aren't built. Defer until the per-engine `expected_questions`
  contracts are authored (it's wasted infrastructure without them).
- **Per-engine `expected_questions` registration.** The 30-50 question
  contracts per engine are the biggest single cost of the full ADR.
  Defer until at least one drift incident makes the case concrete.
- **Drift detection at registration time.** Same dependency: needs
  the per-engine expected_questions before it has anything to compare
  against.
- **Confidence-threshold gating.** Available as a Phase 2 follow-up;
  current sandbox margins look healthy from the Phase 1 emit so
  there's no urgency.
- **Grafana dashboard.** Phase 1's logs work today via Loki/Langfuse
  log query. Promote to a dashboard once Phase 2 lands the SQL.

## Implementation sketch (Phase 2, deferred)

Engine O changes (single file, modest):

1. Extend `register_engine_to_mesh()` signature to accept
   `expected_questions: list[ExpectedQuestion] = []`. Persist them as
   a JSON property on the `Predicate` object (or a paired
   `PredicateContract` collection — choice not critical).
2. Instrument `/search_predicates` to capture every decision and
   write asynchronously to `routing_decisions`. The write must not
   block the response (use a bounded asyncio queue + a worker task).
3. Add `/internal/canary_pulse` endpoint that walks every
   registered engine's `expected_questions` and fires each through
   `/search_predicates` with `source="canary"`. Returns a summary
   `{total, correct, pass_rate, drift_summary}`.
4. Add a small admin REST surface for the routing team:
   `GET /internal/routing_decisions?picked_engine=...&since=...`
   for ad-hoc queries.

Cluster-side additions:

1. New PostgreSQL table `routing_decisions` (could live in the
   existing `iagent` database).
2. K8s `CronJob` that hits `/internal/canary_pulse` every 5 min.
3. Grafana dashboard with: per-engine routing volume, canary pass
   rate, confidence-margin distribution over time, near-tie
   hotspots, fallback-firing rate.

Total implementation estimate: ~2 days for the Engine O changes +
~half day for the cluster wiring + ~1 day to author 30-50 question
contracts per engine. The biggest cost is the per-engine contract
authoring, but that's a one-time setup that future ADR-0007
("survey before mint") style discipline can keep current.

## Alternatives considered

### Repo-side YAML corpus (rejected)

A single `tests/routing/corpus.yaml` listing
`{question, expected_engine}` pairs, run from CI.

Why rejected: by month two of production the YAML is stale because
agent registrations have drifted. The corpus can't represent a live
registry's truth from a file in a static repo. This is the same
ADR-0014 lesson (scaffolding hardens into pseudo-truth when divorced
from the registry that owns it).

### Langfuse-only routing observability (rejected as sole solution)

Langfuse v3 supports non-LLM spans; we could synthesize a span for
each `/search_predicates` call with candidates as metadata.

Why rejected as the *sole* mechanism: Langfuse is designed for
per-request tracing and works well there, but the questions the
routing team needs to answer are aggregate-shaped ("what fraction of
last week's queries had margin < 0.05?"). SQL over an audit table
is the right tool. The Langfuse span can be added on top if the team
is already living there, but it isn't a substitute.

### L1 + L2 + L3 all at once (deferred to follow-up ADRs)

The original scoping included three layers: L1 (`/search_predicates`
direct), L2 (BAML chain), L3 (full mesh). Per user direction this
ADR is scoped to L1 only.

Why deferred: L1 catches the regression class that today's actual
failure modes belong to (description / synonym drift, entitlement
filter changes, new agent crowding). L2 and L3 are correct
additions later when L1's coverage proves a need. The promotion
path is clear: when a routing regression slips past L1, an L2 case
is added for that specific pattern.

## Open items for the future decision

- **Score margin threshold default.** Start at 0.05 absolute. Tune
  with two weeks of real-traffic data; the audit table directly
  supports `SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY
  pick_margin) FROM routing_decisions WHERE source='user_request'`.
- **Contract authoring discipline.** Per ADR-0007's
  "survey before mint" principle, when an engine wants to add or
  modify its claimed questions it should grep the existing audit
  table for similar phrasings first — to avoid claiming what another
  engine is already winning. A small admin tool that does this
  search is a half-day add.
- **Drift report routing.** Today the structured log lands in
  whatever the cluster sends Engine O logs to. As the deployment
  grows, the drift report should be tee'd into a routing-team
  Slack/email channel.
- **Multi-tenant entitlement claim distribution.** As more user
  personas with different `entitled_domains` populate the audit
  table, slicing decisions by claim becomes a natural follow-up
  question. The schema supports it; the dashboard does not yet.

## Out of scope

- L2 (BAML chain) and L3 (full mesh) testing. Promoting specific
  cases to those layers is a future workflow, not this ADR's
  decision.
- BAML / Langfuse integration for non-LLM spans. Tracked as a
  separate observability ticket; this ADR's audit table is the
  authoritative routing log regardless.
- Active routing improvement strategies (e.g. learn-to-rank,
  reinforcement from disambiguation answers). This ADR is about
  detection; improvement strategy is a future ADR once detection is
  in place and producing data.
