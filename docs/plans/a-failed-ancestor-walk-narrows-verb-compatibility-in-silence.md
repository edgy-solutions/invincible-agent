---
id:         a-failed-ancestor-walk-narrows-verb-compatibility-in-silence
status:     open
owner:      invincible-agent-28 [5401d7] — ia-eo / lane/eo
blocked-on: the MeshGraph contract — ancestors() is one of its named operations, and this decides what its failure means
trigger:
closed-by:
repo:       invincible-agent
summary:    A Neo4j failure in the subClassOf walk returns an empty chain, and /classify_predicate then judges verb compatibility against the raw subject alone — which is the inheritance gap ADR-0018's amendment was written to close, reappearing as a failure mode rather than a design gap.
---

# A failed ancestor walk narrows verb compatibility, in silence

**RULED 2026-09-14** with its two siblings, held for the same stated reason.

    _get_subject_ancestor_chain (L4260)   except Exception -> return []
    /classify_predicate         (L4439)   ancestor_chain = await _get_subject_ancestor_chain(...)

## What the consumer does with an empty chain

The chain is what the LLM in `/classify_predicate` sees *"in order to validate a verb's
compatibility against inheritance rather than against the raw `input_uri` string — addresses the
subClassOf-LLM-gap ADR-0018 amendment"*. An empty chain does not error and does not abstain: it
silently returns the model to the pre-amendment behaviour, judging compatibility on the subject's
own IRI alone.

**SO THE FAILURE MODE IS A NARROWER ANSWER THAT LOOKS LIKE A CONSIDERED ONE.** Verbs declared on an
ancestor are judged incompatible; the refusal that follows is well-formed, confident, and wrong,
and nothing in it mentions a graph read that did not happen. **The remedy for this defect already
shipped as a design change — this is the same gap arriving through the error path**, which is
exactly the class of hole a design fix does not close.

Its own docstring documents the benign reading — *"Empty list when subject doesn't exist as
`:OntologyClass` (or Neo4j …)"* — and that parenthesis is where the two states were merged.

## Why an empty chain cannot simply be made a refusal

`hops=0` is the subject itself, so a **legitimate** empty chain means "this subject is not a known
class", which is a real and common answer. A refusal on every empty chain would turn an unknown
subject into a 503. The distinction has to be drawn on the FAILURE, never on the emptiness — the
same line the Weaviate fix drew, and the same control it kept.

## RULED 2026-09-14 — IT REFUSES. NO FALLBACK.

`/classify_predicate` **refuses, naming the substrate**, when the walk fails. This is the only one
of the three packets with no middle option, and the reason is what the failure does: **the
pre-ADR-0018 behaviour arriving through the error path is the design change undone by an
exception.** A degraded answer here is indistinguishable from a considered one, so there is nothing
to carry a degradation marker to — the answer itself would be the wrong shape.

## RATIFIED 2026-09-14 — THE SHARED RESULT TYPE, built before any interface has a method

This packet's three states are not this packet's invention any more. **One result type in the SDK
carries both axes and `MeshGraph`, `MeshOntology` and `MeshVectors` all return it:**

    outcome   answered | empty | failed | unreachable     -- WHETHER it was answered
    mode      how it was answered, where a mode exists    -- e.g. hybrid | bm25

ca builds the type first; this packet lands ON it. The reason it is cheap now: there are not two
converging decisions (a status field on the graph side, a mode field on the vector side, meaning
one thing in two vocabularies) — **there is one decision, and it is only one because the `mode`
axis had no implementation yet to be consistent with.** That is the correction that made it a
single type instead of a later reconciliation.

## The shape when it lands

1. `_get_subject_ancestor_chain` raises on a substrate failure; **an absent subject still returns
   `[]`**, because "this subject is not a known class" is a real and common answer and `hops=0` is
   the subject itself.
2. `/classify_predicate` refuses with the substrate named. Proceeding silently — today's behaviour
   — is ruled out, and so is proceeding with a marker.
3. `MeshGraph.ancestors(iri, max_hops)` inherits that refusal semantic; the interface's failure
   behaviour is decided here, which is why this waits for the contract.
4. **THE SEAL RULE, shared by all three packets:** *a fixture that exercises only the legitimate
   empty cannot tell the fix from the defect.* Both empties in the fixture — an unknown subject
   (legitimate `[]`) and a driver that raises (refusal) — asserted to produce different returns.
