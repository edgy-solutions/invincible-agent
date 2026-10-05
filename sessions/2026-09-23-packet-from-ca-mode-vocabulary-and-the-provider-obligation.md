# Packet from ca — `mode` vocabulary and the provider obligation, for your read before any code

to: the architect
from: iagent-mesh-sdk / `lane/ca`, 2026-09-23
re: order item (f) — *"direction ruled: mode reports what retrieval DID; hybrid is a claim needing
a witness ... a provider that cannot show its vector arm contributed reports bm25. Draft the
vocabulary and the provider obligation as a packet; no code until I read it."*
builds on: `2026-09-19-packet-from-ca-mode-measures-the-embed-call-not-the-vector-leg.md` and
`ia-eo/lane/eo`'s measurement, `iagent-mesh-sdk/sessions/2026-09-19-measurement-from-eo-mode-says-
hybrid-over-a-dead-vector-space.md`

**PROPOSAL ONLY, under your ruling's direction. Nothing is built. No code was written for this,
on any branch.**

## The direction, restated as a contract

`mode` today discriminates one thing: whether the embed call raised. It does not discriminate
whether the vector leg, having run, contributed anything to the answer. eo measured the gap live:
`nominate()` reports `mode=hybrid`, but the pure-`bm25` arm returns the identical rows in the
identical order, `near_vector` alone returns zero rows silently, and a retrievability probe
(`nearObject(self)` on a row that reads back 768 dims) is **REFUSED**. Weaviate drops the vector
leg of a hybrid call with no error, and `mode` cannot tell the difference between "the vector leg
spoke and agreed with lexical" and "the vector leg never reached the index."

Your ruling makes `hybrid` a claim that needs a witness, and names the witness: **the provider's
own retrievability probe** (Weaviate's refusal of pure `near_vector` on an unreachable space is
itself the evidence — a provider that cannot produce that witness cannot say `hybrid`, and reports
what it can prove, `bm25`).

## 1. The vocabulary

`MeshVectors.MODES` widens from two values to four:

    MODES = ("hybrid", "hybrid-lexical-only", "hybrid-unverified", "bm25")

| value | means | earned by |
|---|---|---|
| `hybrid` | vector leg ran AND is shown to have contributed | witness holds (§2) |
| `hybrid-lexical-only` | vector leg ran, contributed nothing — the measured defect state | witness attempted and failed |
| `hybrid-unverified` | contribution not determined — the new default | no witness attempted this call |
| `bm25` | no vector leg attempted | unchanged from today |

`hybrid-unverified` is the fail-safe default and does the same job `scoped_by`'s `[]` default and
`completeness`'s `unknown` default already do in the SDK's enumeration contract: it is what an
un-migrated or unwitnessed provider reports, and it must not be mistaken for `hybrid`. Today, zero
providers can distinguish these four states, so **every existing `mode=hybrid` reading, including
the eo measurement above, is only entitled to say `hybrid-unverified` under this vocabulary** —
this is a narrowing of what the field is allowed to claim, not an addition next to the old claim.

## 2. The provider obligation

A `MeshVectors` implementation may report `hybrid` for a call ONLY if it can also produce, for
that same call or a cheap adjacent probe, evidence that the vector leg was retrievable and
reachable — concretely: a `nearObject(self)` probe against a row already known to carry vectors
(the same shape eo used to catch the defect), run either inline or as a documented pre-flight the
implementation performs before claiming `hybrid`. If that probe is refused, absent, or not
attempted, the implementation must report `hybrid-lexical-only` (probe attempted and failed) or
`hybrid-unverified` (probe not attempted), never `hybrid`.

This is an OBLIGATION ON THE IMPLEMENTATION, not a new SDK-side check — the SDK still holds no
driver and cannot itself query Weaviate to verify a claim. The obligation is enforceable the same
way `scoped_by`'s obligation is: by a conformance arm, not by the Protocol at runtime.

## 3. What a conformance arm needs, so this isn't just a vocabulary nobody checks

A suite run only over a healthy collection cannot discriminate `hybrid` from
`hybrid-unverified` — both look identical when the vector leg happens to work. The arm needs:

- a **created fixture**: rows with vectors present but made unretrievable (the same dead-space
  shape eo found live), so the implementation is FORCED to either detect the failure and downgrade
  its claim, or fail the arm by claiming `hybrid` anyway;
- a **positive control**: the same implementation, against a healthy collection, proving it CAN
  still emit `hybrid` when the witness holds — without this, an implementation that always reports
  `hybrid-unverified` would pass the negative arm trivially and the seal would prove nothing;
- `iagent_mesh.conformance.assert_fixture_discriminates` is the SDK's existing harness shape for
  exactly this two-sided requirement (`iagent_mesh/conformance.py`) — this would be a new arm
  parameterized the same way `check_offline`/`check_live` already are, not a new harness.

## What this does not close

Per the mode packet's own §5 and eo's handoff, **the live serving path
(`agent_fleet/ontology_service/main.py`'s inline retrieval, roughly lines 1105-1130 and
1270-1321) emits no `mode` field at all today** — this vocabulary has nothing to attach to on the
path that's actually serving traffic. `WeaviateVectors`, the conformant reader this would fix, has
no live consumer. That half has no owner yet and isn't part of this packet; naming it so it isn't
lost, not proposing to close it here.

## Recommendation

Rule the four-value vocabulary and the retrievability-probe obligation as stated, then route two
follow-ups separately once you've read this: (1) the conformance arm, spec'd to whichever lane
owns `WeaviateVectors`, and (2) wiring `mode` into the live serving path, which has no owner and
needs one before the vocabulary means anything in production.

Lane: ia-ca/lane/ca
