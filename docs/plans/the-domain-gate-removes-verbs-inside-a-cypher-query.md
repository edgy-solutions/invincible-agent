---
id:         the-domain-gate-removes-verbs-inside-a-cypher-query
status:     open — the one eligibility gate the trace does NOT cover
owner:      unassigned
blocked-on: a decision on whether `/find_compatible_verbs` returns the unscoped set alongside the scoped one
repo:       invincible-agent
ruled-by:   ADR-0025 (`domain_scope_excluded`, the deny primitive's data shadow)
code-site:  agent_fleet/ontology_service/main.py (`/find_compatible_verbs`, the domain filter in the Cypher WHERE), src/iagent/defs/dynamic_supervisor.py:399 (`_find_compatible_verbs`), the empty-pool branch that re-asks unscoped
summary:    Every other eligibility gate now records what it removed (`an-eligibility-gate-must-leave-evidence`). The domain gate cannot, because it filters INSIDE the Cypher query — the excluded verbs are never materialised on either side of the wire, so there is no Python seam where a removed verb passes through. `domain_scope_excluded` is detected today by RE-ASKING Neo4j unscoped on the empty-pool path, which is a different and more expensive mechanism and only fires when the pool is empty. A domain gate that removes SOME verbs and leaves others is invisible, and that is the shape that produces a confident wrong answer rather than an abstention.
---

# The domain gate removes verbs inside a Cypher query

## Why the trace stops here

Every other gate has a Python seam — a list goes in, a shorter list comes out, and the
difference is recordable:

```python
compatible_verbs, _arity_dropped   = _filter_verbs_by_arity(...)
compatible_verbs, _argfit_dropped  = _filter_verbs_by_argument_fit(...)
candidates,       _gate_excluded   = <productive-option gate>
```

The domain gate has no such moment. `/find_compatible_verbs` filters by `entitled_domains`
**in the query's own WHERE clause**, so the verbs it excludes are never constructed as objects
anywhere. Nothing on either side of the wire has ever held them.

**So the trace is complete for four gates and blind for the fifth.** Stated plainly rather than
left to be discovered, because a trace that looks complete is worse than one known to have a
hole — a reader who finds no exclusion record concludes nothing was excluded.

## What exists today, and its two limits

`domain_scope_excluded` IS detected — by re-asking Neo4j **unscoped** when the scoped walk comes
back empty, and comparing:

```python
if subject_uri != "UNKNOWN" and compatible_verbs is not None and not compatible_verbs:
    unscoped_verbs, _ = _find_compatible_verbs(context, subject_uri, entitled_domains=[])
    if unscoped_verbs:
        fb_reason = "domain_scope_excluded"
```

**Limit 1 — it only fires when the pool is EMPTY.** A domain gate that removes three verbs and
leaves one is invisible: the pool is non-empty, the branch never runs, and the trace records
nothing. That is exactly the 2→1 shape from the arity gate — *the harder failure is the one that
produces an answer* — and here it produces a confident answer from a surviving verb while the
better one was scoped away.

**Limit 2 — it is a second round trip**, taken on a path that has already failed. Fine as a
diagnosis of an abstention; not something to run on every successful route.

## The shape of the fix

`/find_compatible_verbs` already runs the walk. Have it return the verbs the domain filter
removed, alongside the ones it kept — one query, two result sets, no extra round trip:

```
{verbs: [...], excluded: [{kind: "verb", uri, gate: "domain",
                           disposal: "removed", reason: "not_in_<DOMAIN>"}]}
```

The supervisor then extends `_eligibility_trace` with them exactly as it does with engine-o's
class-level records, and **the existing empty-pool re-ask becomes redundant** — `fb_reason` can
be derived from the trace instead of from a second query. That is the part that makes this worth
doing rather than merely tidy: it removes a round trip while adding coverage.

The Cypher change is a `COLLECT` of the verbs failing the domain predicate rather than dropping
them in the WHERE. Cost is bounded by the compat-walk's own reach, which is already `*0..5`.

## Why this one matters more than its position in the queue suggests

**This is the gate that fired on the finance-persona planning question two nights ago.** A
caller with a finance persona asking a planning question had verbs scoped away and got the
generalist — and the record said `domain_scope_excluded` only because the pool happened to end
up empty. Had one planning verb survived the scope, the answer would have come back from it,
confidently, with no trace at all.

**And it is the gate whose exclusions are most often ACTIONABLE.** Arity says "name an
instance"; argument-fit says "the query cannot supply an argument". Domain says *"this exists
and your scope excludes it"* — which is a sentence about entitlement, not phrasing, and it is
the one a user genuinely cannot diagnose alone.
