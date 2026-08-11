# The consolidation-completes-at-the-last-consumer law

> **A consolidation is complete when every consumer is bound to the shared implementation — not
> when the shared implementation exists.**

Building the seam and wiring the callers to it are two pieces of work. The first is visible,
argued for in a commit message, and satisfying. The second is tedious and invisible, and it is the
one that makes the first true.

## Why it needs stating

The failure is not "we forgot." It is that **the one-implementation rule gets invoked as the
justification for building the seam, and then treated as satisfied by its existence.** The commit
message argues, correctly, that a second implementation of X is exactly what the rule forbids —
moves the richer semantics into the shared place — and leaves a consumer pointing at the poorer
one. The argument is sound and the outcome still has two implementations, now with a document
asserting it has one.

That assertion is the damage. An unconsolidated system that knows it is unconsolidated gets fixed.
One carrying a commit message saying otherwise does not get re-examined.

## The instances

* **`iagent-mesh-sdk` v0.3.0** — `registration_transport.py` was added to be *the* one
  authenticated registration path: the mint, ADR-0006 retry semantics, a named failure. The
  platform binds it. **The SDK's own `MeshTool` lifespan still calls the bare POST**
  (`core.py:244` → `_emit_to_registrar`) — no credential, no retry. So any externally-scaffolded
  engine, *the exact audience the package exists for*, registers unminted and stops under
  `REQUIRE`. The package built to prevent the defect shipped it.
* **`core/authz.py`** — importable and applied nowhere. Same class; the unapplied thing was the
  mechanism.
* **`dag-tools` central gateway** — the on-behalf-of subject header is honoured while the
  authentication it presupposes was never built. Same shape at one remove: not two
  implementations, but a seam whose precondition is unbound. See
  `[[dag-tools-gateway-unverified-subject]]`.

The SDK instance is the sharpest, because **the unapplied thing was the fix itself.**

## The test

Before reporting a consolidation done, answer with a list and not a belief:

> **Who were the consumers of the old path, and which line now binds each of them to the new one?**

If the answer names the seam rather than the call sites, the consolidation is half-built. If any
consumer lives in the same repo as the new seam, check that one **first** — proximity is what
makes it feel already handled.

## Relation to the enumerate-ADR-consumers law

That law asks *who is affected by this decision.* This one asks *who is still on the old path
after it.* Same discipline, opposite end of the change: one enumerates before, one verifies after,
and a consolidation needs both.
