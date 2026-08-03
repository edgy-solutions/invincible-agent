# ADR-0036 — Config layering: seed, overlay, composition

**Status:** Accepted (pattern + composition site). No overlay exists yet — written BEFORE the first one, so the pattern is doctrine rather than whatever the first deployment improvised.
**Date:** 2026-08-03
**Deciders:** Platform team
**Related:**
  - The **Topaz policy repo** — the precedent. Git-asserted grants, sync tools with disjoint prune
    scopes, validate → reconcile → readback, revocation-by-removal. This ADR generalizes it.
  - [ADR-0034](ADR-0034-trust-lifecycle-admission-policy-decision-records-autonomous-path.md) — the trust
    table is ratifiable config; its rungs are exactly the kind of content work must own differently.
  - [ADR-0035](ADR-0035-two-planes-process-and-data-with-embedded-provenance.md) — source mappings are
    config too, and the restricted-boundary rule that makes overlays necessary is stated there.
  - [ADR-0029](ADR-0029-process-workflow-model-spo-steps-restate.md) — workflow definitions are
    git-asserted config; they inherit this pattern when work authors its own processes.

## Context

The Topaz repo answered this once, for authorization: **structure syncs, content overlays, the
mechanism is identical on both sides.** That answer was scoped to one artifact class and it held.

The surface has since grown well past it. Every one of these is ratifiable data that the open repo
seeds and work must own differently:

| surface | seeded here | work owns |
|---|---|---|
| qualification statuses | five, `qualifying` flagged as doubtful | the states engineers actually use |
| disposition rules | demo ruleset | rules citing real process docs |
| trust table | empty, born-supervised | actual rungs per vendor-format |
| source mappings | an empty template | filled contracts against real sheets |
| workflow definitions | the grouped review | work's own processes |
| audience / capability grants | example identities | real identities, non-email claims |

Without a stated pattern, each of these acquires a different answer at deploy time — and the answers
will be worse than the Topaz one because they will be improvised under delivery pressure. The
constraint that forces this is already standing and permanent: **internal process detail cannot cross
the fence**, so "just put the real values in the seed repo" was never available.

## Decision

### 1. Three layers, and the open repo ships the first two

- **Mechanism** — schema, validation, loaders. `validate_ruleset`, the status vocabulary's
  loud-refusal loader, the mapping template's shape. **Ships once, runs identically on both sides.**
- **Seed** — honest starting content, flagged where weak (`qualifying` carries its own
  delete-me-if-wrong note in-file). Never a placeholder pretending to be a decision.
- **Overlay** — work's deltas, in a work-side repo. Never syncs outward.

### 2. Composition happens AT THE REPO, not at ingest

Work's repo composes seed + overlay in CI into the artifacts the **unchanged** ingest consumes.

Rejected, with reasons:

- **Overlay-at-ingest** (the ingest job composes before landing). Rejected primarily because it
  breaks a property this codebase already depends on: **`ruleset_ref` / `trust_table_ref` are content
  hashes of an artifact you can open and read.** Composing at ingest makes the hash cover something
  that never existed as a file, so "what exactly was this decision made under?" becomes
  unanswerable by inspection — and that question is the entire point of those refs.
- **Per-mechanism overlays** (each loader learns layering). Rejected outright: N implementations of
  one law, which is the two-escapers problem at config scale. They will disagree, once, in
  production.

Composition **emits the composed artifact** as a readable file. Debugging a config question must
never require mentally replaying a merge.

### 3. Three properties, each inherited from the Topaz arc rather than invented

**a. The composed result passes the SAME validation.** Work's overlay + seed runs the identical
`validate_*` gate the seed passes alone. A work-side typo minting a phantom status fails at work's
ingest exactly as it would here — because the mechanism ships with the seed, the overlay inherits
its guards for free. This is the property that makes overlays safe rather than merely convenient.

**b. Provenance carries the LAYER.** The composed artifact's hash covers the merged content, and each
entry records which layer asserted it. An auditor asking *"who decided `ltb_only` exists — us or the
platform?"* gets an answer. Without this, an overlay silently launders a work decision into something
that looks like an upstream default, which is the same laundering ADR-0035 refuses for data sources.

**c. DELETION MUST BE EXPRESSIBLE.** Work must be able to say *"no `qualifying` state here"* as an
overlay **statement**, not by forking the seed file. This is the clause most likely to be skipped and
the one that decides whether the pattern survives: without it, the first unwanted seed entry forces a
fork, and a fork means work stops inheriting mechanism updates — the overlay becomes a copy, and the
whole layering collapses into two divergent repos.

The Topaz precedent already has the shape: **revocation-by-removal**, where absence in the composed
result is a first-class, auditable outcome rather than an accident.

### 4. The restricted boundary holds BY CONSTRUCTION

The overlay repo lives at work and never syncs outward. Nothing in the seed repo learns an internal
fact. The reverse channel is the established structural-summary protocol: shape described, content
withheld — *"eleven statuses, three seed entries deleted"* is reviewable and names nothing.

## Consequences

- **The team-contribution model gets its enabling infrastructure.** The overlay repo is where a
  funded team's domain content lives — their statuses, rules, mappings — inside the extension
  contract's legal zone by construction.
- Work gains a **CI composition step**: a real new build dependency, and the honest cost of this
  decision. Mitigated by composition emitting a readable artifact.
- **Seed quality now matters differently.** A seed entry is a suggestion work must actively delete,
  so a bad seed is friction rather than a bug — which is why `qualifying` ships flagged.
- Every future config surface inherits the pattern instead of inventing one.

## Non-goals

- **Building the composition tool.** This ADR fixes the *site* and the properties; the tool is work.
- **Migrating existing config.** The Topaz repo already works; it is the precedent, not a customer.
- **A merge algebra.** Start with the simplest rule that satisfies §3c — overlay entries replace or
  delete by key, seed applies where the overlay is silent. Anything richer waits for a case.

## Open questions

1. **Overlay granularity** — per-file, per-entry, or per-field? Per-entry is the lean (it makes
   deletion natural), but a real overlay will show whether field-level merge is ever wanted.
2. **Does the composed artifact get committed, or built fresh each time?** Committing makes the
   deployed state readable in git; building keeps one source of truth. Lean: build, but publish the
   composed artifact alongside the deployment so it is inspectable.
3. **Do workflow definitions overlay at all,** or does work simply author its own? A process is
   arguably not a delta on someone else's process — unlike a vocabulary, where deltas are natural.
   Deferred to the first work-authored workflow.
