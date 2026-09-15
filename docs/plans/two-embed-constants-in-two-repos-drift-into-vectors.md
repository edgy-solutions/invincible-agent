---
id:         two-embed-constants-in-two-repos-drift-into-vectors
status:     open
owner:      invincible-agent-28 [5401d7] — ia-eo / lane/eo
blocked-on: the writer half — doc-tools-7f records the model as collection metadata; the reader half is this lane's and waits on SDK v0.9.0
trigger:
closed-by:
repo:       invincible-agent
summary:    DEFAULT_EMBED_MODEL and EXPECTED_EMBED_DIM are hand-duplicated across agent_fleet/utils/embed.py and doc_tools/utils/embed.py, enforced by "code review on either constant catches drift". A model divergence produces VECTORS rather than an error, and Weaviate's dimension lock — the only real net — cannot see it.
---

# Two embed constants, two repos, and a divergence that produces vectors

**The writer embeds. The reader embeds. Nothing asserts they agree.** `doc-tools` writes vectors
into Weaviate; engine-o computes a query vector at read time and hands it to Weaviate as
`vector=`. Both derive their model and dimension from a file called `embed.py` — **and there are
two of those files, in two repositories, with the constants copied by hand.**

    agent_fleet/utils/embed.py        DEFAULT_EMBED_MODEL = "nomic-embed-text"   EXPECTED_EMBED_DIM = 768
    doc_tools/doc_tools/utils/embed.py   (the twin, per this repo's own comment)

The enforcement is written into the comment, verbatim: *"cross-repo agreement enforcement:
`doc-tools/doc_tools/utils/embed.py` declares the SAME `EXPECTED_EMBED_DIM` constant. **Code
review on either constant catches drift.**"* And the migration note instructs: *"Update
`EXPECTED_EMBED_DIM` in **BOTH** embed.py files. Update `DEFAULT_EMBED_MODEL` in both files."*

**A LESSON WRITTEN BESIDE A LIST DOES NOT MAINTAIN THE LIST.** This repo has retired that
construction three times for exactly this reason; here it is guarding the numerical compatibility
of every stored vector.

## Why the existing safety net covers the harmless half

The comment names a real net, and is honest about its reach:

> *"Weaviate v4 collections WITHOUT a vectorizer_config (our pattern) lock the dimension on the
> FIRST write. Subsequent writes of a different dim are rejected loudly … that's the cross-repo
> safety net on top of this constant."*

and, two paragraphs earlier, the sentence that makes this packet:

> *"vectors stored under the old model are not numerically compatible with vectors from a new
> model, **even if the dimensions match**."*

**So the net catches a DIMENSION change — loudly, on write — and cannot see a MODEL change at the
same dimension.** A swap from one 768-dim model to another writes cleanly, reads cleanly, and
returns neighbours computed in a different space. **The failure mode is not an error. It is
plausible-looking results**, which is the failure this fleet has the least defence against.

## Measured, so this is a drift RISK and not a live break

Read from sandbox Weaviate 2026-09-14, read-only:

    OntologyClass   stored vector dim 768        EXPECTED_EMBED_DIM 768   agree
    Predicate       stored vector dim 768        EXPECTED_EMBED_DIM 768   agree
    vectorizer      None on both collections     moduleConfig {}          no model recorded

**The constants agree today.** Nothing is broken. What does not exist is anything that would say
so tomorrow.

## And the interface cannot fix it, which is why this is separate

`MeshVectors` (SDK `4113cfd`) declares `embedding_model` and requires an implementation to verify
it against the collection before searching. That is the right requirement and it does not close
this: **the collections record no model at all** (measured above), and even once a writer records
one, the assertion is *implementation vs collection*. **Nothing in it makes the reader's constant
and the writer's constant agree with each other** — they are two copies in two repos, and the
interface only sees one of them.

## RULED 2026-09-14 — IT CLOSES AT THE COLLECTION, NOT IN CODE REVIEW

The ruling does not try to make the two copies agree. **It gives both sides one witness they must
each agree with, and puts it where the vectors are:**

* **The WRITER records the embedding model NAME AND VERSION as collection metadata**, when it
  creates the collection or first writes to it. That is `doc-tools`' ingest, since it creates them.
* **`MeshVectors` asserts its `embedding_model` against that metadata AT OPEN** — before a single
  vector is written or read. A mismatch is a **refusal naming both**, not a warning and not a
  degraded search.

**Then the two hand-copied constants may drift all they like.** They stop being the contract; the
collection is. A reader embedding with the wrong model cannot reach the vectors at all, which is
the property the dimension lock gives for the dim and could never give for the model.

**AT OPEN is the load-bearing half.** Asserting per query would spend a round trip on every search
and still leave the first write unguarded — and the failure this prevents is a WRITE with the
wrong model just as much as a read. Open is the one moment both sides pass through.

**ADDED WHILE THEY STILL AGREE, which is the only time it is cheap.** 768 on both sides today. A
check added after a divergence has to be a migration; added now it is a constant and an assertion.

**The halves have owners:** the reader half is this lane's (waits on SDK `v0.9.0`, which carries
the Protocol). The writer half is `doc-tools-7f`'s.

## The shape when it lands

**Superseded note:** this section previously proposed ONE HOME for the contract — both `embed.py`
files importing from the SDK or a shared leaf. **The ruling rejected that framing**, and the
reason is worth keeping: a shared constant makes the two sides agree with *each other*, which
still leaves nobody agreeing with the VECTORS. The collection is the only witness that has seen
what was actually written.

0. **THE KEY AND VALUE SHAPE ARE DECLARED IN THE SDK, as part of the `MeshVectors` contract.**
   Ruled 2026-09-14, and it corrects something I had proposed: I asked doc-tools to pick a key and
   tell me so I could match it. **That would have reproduced this packet's defect inside its own
   fix** — a contract kept as two hand-agreed spellings in two repos, enforced by remembering a
   message, which is the same shape as two hand-copied constants enforced by code review. *A key
   two lanes agree on is an agreement; a key the Protocol declares is a contract both
   implementations conform to*, and the conformance suite asserts it. **Both sides read the
   declaration, neither reads the other.**
1. **WRITER (doc-tools-7f):** record the embedding model **name and version** as collection
   metadata at create-or-first-write, under the declared key. Both collections carry none today — `vectorizer: None`,
   `moduleConfig: {}`, no property that could hold one (measured above).
2. **READER (this lane), on SDK `v0.9.0`:** `MeshVectors` reads that metadata **at open** and
   asserts it against its own `embedding_model`. A mismatch **refuses, naming both** — the
   configured model and the collection's — so the message says which side to change.
3. **Sequencing:** the reader's assertion must tolerate metadata being ABSENT until the writer
   lands, and that tolerance is the one thing to be careful with. **Absent must not be silently
   treated as matching** — that is the vacuous self-comparison this packet exists to prevent. It
   is a distinct, named state: *the collection cannot say*, reported once at open rather than
   swallowed.
4. **The seal, both directions:** metadata matching the model opens; metadata naming a different
   model refuses and the message contains both names; metadata absent opens with the gap reported.
   Three fixtures, because a fixture that only exercises the matching case cannot tell the
   assertion from its absence.
5. **What this deliberately does NOT do:** make the two `embed.py` constants agree. They may drift;
   the collection is the contract. If they drift apart, the first side to open against a collection
   written by the other refuses — which is the outcome, not a gap in it.
