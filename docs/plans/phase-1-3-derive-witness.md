# Phase 1.3 consumer half — the DERIVE, witnessed. CLOSED.

The trust key is now computed from the artifact. `(format_fingerprint, pipeline_version)` no longer
crosses a client boundary in any form: callers supply a POINTER and nothing else.

## The legs — routes read from the Restate JOURNAL, table hash read back from the pod each time

| leg | artifact | derived key | table | route |
|---|---|---|---|---|
| **A — back-corpus** | REAL (`diodes_2683/…`) | `unknown/pcn/v1` × *(none)* | committed `trust@1c45c6dc296e` | `GroupedReview` — suspended |
| **2 — promoted** | fixture, stamped | `witnesscorp/pcn/v1` × `doc-tools@witnessderive` | fixture `trust@75742c56a72b` | `AutonomousReview` — completed |
| **3 — version mismatch** | fixture B, same key | same | fixture `trust@1794ef9e5500` | `GroupedReview` — running |

```
AutonomousReview/pcn-review-DRV-LEG2-…/run       completed
GroupedReview/pcn-review-DRV-BACKCORPUS-…/run    suspended
GroupedReview/pcn-review-DRV-LEG3B-…/run         running
```

**Leg A used a REAL artifact and is the corpus's actual state**: no producer stamp, so it takes the
floor and *says so* — `admitted_by=policy-default-missing-provenance`. That is the back-corpus
degrading safely **and legibly**, which was the whole point of splitting refuse from floor.

**Leg 3 is the first time the upgrade-invalidation guard has been exercised against a version that
actually describes the producer.** Previously it was checked against a caller-asserted string.

## The methodological trap this witness hit

Leg 3's first run **did not execute**. It returned leg 2's `workflow_id` and leg 2's ADMISSION
line, because the BFF derives an ingress idempotency key from `(request_key, approver)` — and I had
driven both legs against the SAME artifact. Same pointer, same approver, same key: Restate
correctly ATTACHED to the prior invocation instead of running a second one.

So the guard under test was never exercised, and the run looked successful. Caught by the readback
naming the wrong notice — not by anything going red.

**The pointer is now the idempotency key as well as the admission key**, which is a new coupling
this change introduces: two legs that differ only in TABLE state cannot share an artifact. Leg 3 was
re-run against a second artifact with identical content at a distinct path — same derived key,
distinct pointer.

## Finding — the fingerprint does not partition the way promotion assumes

Measured across all 16 real artifacts in `processing-artifacts`:

- **4 of 16 carry no `header.mfr`** → all derive **`unknown/pcn/v1`**, one key spanning unrelated
  vendors. Promoting it would grant trust to every unidentifiable artifact regardless of producer.
- **`onsemi` vs `ONSEM`** — one vendor, two fingerprints. Trust earned under one does not apply to
  the other. Fail-safe, but evidence never accumulates for the split-off variant.
- **`doc_type` absent on 9 of 16** → silently defaults to `pcn`.

This is exactly what ADR-0034 open question 3 anticipated (*"the fingerprint needs real corpus data
to sharpen"*) — and this IS that corpus data.

**`unknown/pcn/v1` is a degenerate fingerprint in the same way `unset` is a degenerate version**, and
the sentinel rule does NOT catch it: that rule guards the version axis only. A promotion keyed on
`unknown/*` would match every unidentifiable artifact at once — the same
matches-everything-on-absence hazard, on the other axis.

**Recommended, not taken** (it extends a rule the architect scoped narrowly): forbid a rung above
`supervised` keyed on a fingerprint whose vendor component is `unknown`. Same shape, same one-line
justification, same home in `parse_trust_table`.

## Settlement — no residue

- both witness artifacts removed, `head_object` confirming absence (a fixture artifact that outlives
  its witness is corpus contamination — a later promotion could be argued against evidence the
  pipeline never produced)
- table restored to the committed `trust@1c45c6dc296e`; `witnesscorp/pcn/v1` resolves `supervised`

## Also witnessed

- **engine-a boots with the registry invariant active** — definitions loadable by name, verified by
  direct invocation in the pod (its success log is invisible: module-level `logger.info` does not
  reach stdout in this image, so the *failure* path is loud — a raise blocks startup — while the
  success is unobservable. Worth knowing before relying on the log line.)
- **the service-half probe is CLEAN** — 6/6 expected services registered, including
  `AutonomousReview`.
- **engine-a reads the bucket** with credentials it already had; `boto3` was the only thing missing.

## What remains

`pipeline_version` will read `(none)` on every real notice until **doc-tools is rebuilt and re-runs
an extraction** — the stamp is committed (`300b8e8`) but no stamped artifact exists yet. Until then
every real notice takes the floor as `policy-default-missing-provenance`, which is correct, legible,
and the honest state.

**The ceremony's fingerprint leg is closed.** The key is derived from the artifact on both axes; the
remaining gap is corpus, not code.
