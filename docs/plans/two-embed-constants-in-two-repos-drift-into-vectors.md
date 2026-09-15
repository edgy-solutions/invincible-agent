---
id:         two-embed-constants-in-two-repos-drift-into-vectors
status:     open
owner:      invincible-agent-28 [5401d7] — ia-eo / lane/eo
blocked-on: a ruling on where the embedding contract lives — the twin is in doc-tools, so no change inside this repo can make the two agree
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

## The shape when it lands — a ruling first, because the fix crosses a repo boundary

1. **One home for the contract.** The candidates are: publish it from the SDK (both repos already
   depend on `iagent-mesh`), or a small shared leaf like `provenance-telemetry`'s. Either way the
   two `embed.py` files import rather than declare. **This is the ruling the packet is blocked on**
   — it changes a doc-tools dependency and is not this lane's to make.
2. **Until then, the seal that is possible from one side:** assert the LOCAL constant against the
   SUBSTRATE — fetch one stored vector, compare `len()` with `EXPECTED_EMBED_DIM` at startup or in
   a probe. It catches the dimension half from either repo independently, without a shared import.
   The numbers above are that check run by hand.
3. **The model half needs a writer-side record**, which is doc-tools': a model marker per
   collection. Named here because no change in this repo can produce it, and because it is also
   what turns `MeshVectors.embedding_model` from a vacuous self-comparison into a real assertion.
