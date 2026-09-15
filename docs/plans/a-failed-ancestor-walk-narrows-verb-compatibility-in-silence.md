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

## The shape when it lands

1. `_get_subject_ancestor_chain` raises on a substrate failure; an absent subject still returns `[]`.
2. `/classify_predicate` decides, explicitly and in this packet before the change: refuse, or
   proceed with a recorded degradation the answer carries. **Proceeding silently is the one option
   ruled out**, because it is today's behaviour.
3. `MeshGraph.ancestors(iri, max_hops)` inherits whichever is chosen — the interface's failure
   semantics are decided here, which is why this waits for the contract.
4. The seal's fixture must distinguish the two empties: an unknown subject (legitimate `[]`) and a
   driver that raises (refusal). A fixture that only exercises one of them cannot tell the fix from
   the defect.
