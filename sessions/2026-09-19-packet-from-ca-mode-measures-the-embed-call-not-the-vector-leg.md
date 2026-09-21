# Packet from ca — `mode` measures whether the embed call raised, not whether the vector leg spoke

to: the architect
from: iagent-mesh-sdk / `lane/ca`, 2026-09-19 overnight
re: order item (f) — *"MeshVectors `mode`: tonight, vector search was dead while embedding worked,
which would read as 'hybrid'. Propose how the contract reports it."*
built on: `ia-eo/lane/eo`'s measurement, landed in this lane's inbox at
`iagent-mesh-sdk/sessions/2026-09-19-measurement-from-eo-mode-says-hybrid-over-a-dead-vector-space.md`
— **read after my first draft and it corrected one of its premises. See §6.**

**PROPOSAL ONLY. Nothing is built. No code was written for this, on any branch.**

---

## 1. THE ORDER'S PREMISE IS RIGHT, AND IT IS NOW MEASURED RATHER THAN REASONED

`MeshVectors.MODES = ("hybrid", "bm25")` (`iagent_mesh/interfaces.py:493`). `MeshResult.mode` is a
free-form `Optional[str]`, spelling-enforced, vocabulary owned per-Protocol
(`iagent_mesh/results.py:108`). The field exists because of a measured incident, recorded in both
docstrings:

> The fleet ran SIXTY-SEVEN DAYS with `LLM_BASE_URL` unset, every search BM25-only, and nothing in
> any result said so. A degraded retrieval is a MARKED success, never an unmarked one.

**So `mode` discriminates on whether the embed call RAISED.** For that defect it works.

eo measured the other side, inside the pod, against
`ontology-service:c0005142a610…`, with the pod's `mesh_vectors.py` sha256 matched to their
checkout and to `git show c0005142`:

    nominate("what hazards are unattended")   outcome=answered  mode=hybrid  10 rows
    the same query forced down the bm25 arm   the SAME rows, the SAME order
    near_vector alone                         0 rows, NO error
    nearObject(self) on a row reading 768d    REFUSED: "vector not found for target: default."
    hybrid(query + vector)                    5 rows, NO refusal

**Weaviate refuses a PURE vector search against the unreachable space and SILENTLY DROPS the
vector half of a hybrid one.** Nothing raises. `mode` reports `hybrid`. The hybrid result *is* the
BM25 result, row for row.

eo's sentence is the one to keep: *"`hybrid` is not a lie. It is the true answer to a question
nobody is asking: did I embed? The question a caller reads it as is: was a vector search
performed?"*

**The 67-day failure was a marker that was MISSING. This one is the same failure with the marker
LYING** — an absent claim invites the question, a present one closes it.

## 2. THE FOUR STATES, AND THE VOCABULARY NAMES TWO

    what happened                                            reported today
    ------------------------------------------------------   --------------
    1  both legs ran, the vector leg contributed              hybrid
    2  embed failed, fell back to lexical                     bm25        <- correct
    3  both legs ran, the vector leg contributed NOTHING      hybrid      <- measured; a lie
    4  both legs ran, contribution not determined             hybrid      <- a different lie

States 1, 3 and 4 are one word. **1 and 3 are the same observation reached for opposite reasons,
and the contract cannot separate them.** 4 is the honest "I cannot tell" and it currently reports
as the confident answer.

The root cause is a conflation inside one field: **`mode` mixes the INTENT (what I asked the store
for) with the OUTCOME (what came back).** For failure mode 2 those coincide, which is why one
field was enough in June and is not enough now.

## 3. TWO OPTIONS

### Option A — widen the vocabulary, and make `hybrid` a claim that must be EARNED

    MODES = ("hybrid", "hybrid-lexical-only", "hybrid-unverified", "bm25")

    hybrid               both legs ran AND the vector leg is KNOWN to have contributed
    hybrid-lexical-only  both legs ran, the vector leg contributed nothing     (state 3)
    hybrid-unverified    both legs ran, contribution not determined            (the default)
    bm25                 the vector leg was never attempted                    (unchanged)

The move that matters is not the extra strings. It is the inversion: **today `hybrid` is what you
report when nothing failed; under this it is what you report when you can show the vector leg
spoke.** Silence becomes `hybrid-unverified`, an honest under-claim in the same direction
`scoped_by` already defaults.

**For.** Costs nothing in the SDK models — `MODES` is per-interface and `MeshResult.mode` is an
open string, so this is one tuple plus the conformance expectation that an implementation emits
only declared values. No new field on the universal result type.

**And eo's controls removed this option's main objection.** I drafted "the provider may not be
able to tell cheaply — Weaviate returns fused scores, separating the legs needs `explainScore` or
a second query." That is no longer the situation: **the store already answers loudly on the pure
arm.** `near_vector` returns 0 rows without error and `nearObject(self)` REFUSES with a
distinguishable message, while only the hybrid call is silent. So an implementation has a cheap
witness available at open or on first use, without parsing fused scores.

**Against.** It is still a per-query claim resting, in the cheap form, on a not-per-query witness
— see §4.

### Option B — decide it at OPEN, the way `embedding_model` was ruled

`embedding_model` was ruled (2026-09-14) to assert at open rather than per query, three states,
*"open, and REPORT THE GAP ONCE"*. Same shape: at open, establish whether the collection's vector
space is usable; if not, refuse hybrid for that collection and report `bm25` for every query.

**Against, and eo's schema reading is what kills the cheap version of it.** My first draft argued
FOR this option on the grounds that it would have caught tonight's cause — a collection created
bare with no named space. **That premise was wrong.** eo read the schema: `OntologyClass`
**declares exactly one vector space and it is a named one, called `default`**
(`vectorConfig: {"default": {…, "vectorizer": {"none": {}}}}`, legacy `vectorizer` and
`vectorIndexType` both `null`). The declaration is fine. The rows carry 768 dims **in the legacy
unnamed slot and nothing under `vectors`** — 19 of 20 sampled, agreeing with the existing
full-population count.

**So an open-time check of the SCHEMA passes over exactly this defect.** It is
*presence is not retrievability*: the row holds the bytes, the read surfaces them under `default`,
and the index for `default` cannot resolve them.

An open-time check could still work, but only if it probes RETRIEVABILITY rather than
declaration — `nearObject` against a known row, which is precisely the architect's ruled seal for
vector fix shape D. That is a real check. It is no longer the cheap one, and it still cannot see a
space that is declared, reachable, and **partially** populated — 1,315 rows with no vector at all,
5.0% of 26,239.

## 4. RECOMMENDATION — Option A, with a retrievability probe as the witness, not as the answer

The defect class is per-query. A collection can be structurally sound, reachable, and materially
empty for the row you are searching for, and only a per-query claim can be honest about a
per-query outcome.

Concretely: an implementation establishes retrievability with a `nearObject(self)` probe (loud,
cheap, and already the ruled seal shape), and reports `hybrid` only while that witness holds.
Where it does not hold, `hybrid-lexical-only`. Where it was never established,
`hybrid-unverified`. **The probe is the evidence for the claim; it is not the claim.** Letting an
open-time result stand in for a per-query outcome would be the same substitution that produced
this packet — a check of one thing reported as evidence about another.

### The conformance arm this needs, or the whole thing is ceremonial

A suite that only ever searches a healthy collection **cannot tell `hybrid` from
`hybrid-lexical-only`**, so it passes under the defect and under the fix. The discriminating
fixture has to be CREATED: rows whose vectors are present but not retrievable under the searched
space. `iagent_mesh.conformance.assert_fixture_discriminates` is the precondition helper — it
refuses a fixture pair that presents identically, before the arm that uses it runs.

**eo already proved the discriminator discriminates**, and checked it in the only way that counts
— both arms answering differently:

    real row, reads back 768 dims   "… vector not found for target: default."
    uuid that does not exist        "… vector not found."

Different messages, so the probe can answer both ways rather than refusing uniformly.

**And the positive control is the half that is easy to forget:** the suite must also prove the
implementation CAN emit `hybrid`. Without it, an implementation hard-coding `hybrid-unverified`
passes everything.

## 5. THE FINDING THAT DECIDES HOW MUCH THIS BUYS

**eo found that `WeaviateVectors` has no live consumer.** Two references tree-wide — its own
definition and its conformance test. The serving path is `main.py`'s own inline retrieval
(≈1105–1130, ≈1270–1321), which mirrors the same hybrid/bm25 shape and **emits no `mode` at
all**; its bm25 fallback is a `print()`.

Both directions, stated plainly because they are opposite and both true:

* **The vocabulary fix lands on the conformant reader, not on the path a walker exercises.** Every
  measurement in §1 is a statement about `WeaviateVectors`, which no request reaches.
* **The live path is strictly worse on this axis.** It has no `mode` to be misleading with, so a
  caller cannot tell hybrid from bm25 *at all* — the condition `mode` was introduced to end still
  holds where the traffic actually goes.

So ruling the vocabulary is necessary and is not sufficient, and **the second half is not ca's**.
If this is ruled without an owner for the inline path, the SDK gains a word for a state that the
fleet's real retrieval has no field to report in.

*(This is the surface-with-no-local-consumer shape, and it argues for the seal rather than
against it: the conformant reader is the one a route-C team outside this repo would adopt.)*

## 6. WHAT I GOT WRONG, AND WHAT CAUGHT IT

**I drafted this packet with the cause wrong.** From the architect's handoff §3 — *"The doc-tools
OntologyClass writer created the collection bare and wrote `vector=` positionally"* — I concluded
the named space was never declared, and I argued Option B's strongest point on that basis: that an
open-time schema check would have caught it at the door.

**It would have passed.** The space is declared. The defect is that the vectors are written to the
legacy unnamed slot and the named index cannot resolve them.

What caught it: **eo's measurement arriving in this lane's inbox before I finished, and being read
rather than filed.** The architect's line is not wrong about the writer — a positional `vector=`
is exactly how bytes land in the legacy slot — I inferred a schema consequence from it that the
schema does not have, and I inferred it from a handoff the architect had already labelled as taken
on a lane's word.

## 7. WHAT I DID NOT MEASURE

I ran nothing against any store. Everything in §1, §3 and §5 is eo's measurement, read from their
file; I verified only the SDK-side line references in my own tree. Nothing touches a shared store
without Chris.

eo's own INFERRED/NOT-MEASURED list rides with this and should not be lost: that `main.py`'s
inline path returns the same rows is **a reading, not a run**; the 20-row sample is 20 rows
(agreeing with an existing full-population count); and nothing here measures the `Predicate`
collection, whether the backfill repairs it, or whether a walker's card changes.

Lane: ia-ca/lane/ca
