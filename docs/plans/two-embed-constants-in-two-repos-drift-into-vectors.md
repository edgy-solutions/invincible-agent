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

## WHAT THE SUBSTRATE PERMITS — measured twice, and it corrects this packet

**THERE IS NO COLLECTION METADATA DICT IN WEAVIATE.** Established by `doc-tools-7f`, who owns the
writer, and confirmed here from a different instrument before it was relayed:

    7f   weaviate-client 4.21.3, introspected: create()/config.get() expose name, description and
         the *_config blocks. A free-form key-value field: NONE.
    eo   live server schema, GET /v1/schema: top-level keys on both collections are exactly
         ['class','invertedIndexConfig','multiTenancyConfig','properties','replicationConfig',
         'shardingConfig','vectorConfig']. No unclassified dict. `description` absent on both.

**So "record the model under a key" is not expressible, and the Protocol must declare an ENCODING
rather than a key name** — `description` is a single string and it is the only carrier. A key name
declared in the abstract would leave both implementations to invent a PLACEMENT, which is this
packet's defect a third time, inside the fix for the fix.

**AND IT CORRECTS THIS PACKET'S SEQUENCING CLAIM.** I wrote that the check had to be added while the
constants still agree *"or it becomes a migration"*, believing create-time was the only path.
**`config.update()` accepts `description`**, so `OntologyClass` (21,078 objects) and `Predicate`
can be annotated **in place — no recreation, vectors untouched.** The urgency I asserted was real
in direction and wrong in mechanism, and the correction came from the lane that owns the writer,
which is the argument for establishing what the substrate permits before anyone declares anything.

### A FOURTH STATE, from the reader side — it decides the encoding

`description` is a HUMAN-FACING PROSE FIELD. Both collections hold none today, which is luck
rather than design. So the reader distinguishes four states, not three:

    matching              -> open
    mismatching           -> REFUSE, naming both
    absent                -> open, report the gap once
    PRESENT BUT NOT OURS  -> someone wrote prose here

**The fourth must collapse to ABSENT, never to MISMATCH.** A reader that treats an unparseable
description as a wrong model means **the first person who documents a collection takes routing
down** — worse than the defect being fixed, and reachable the first time anyone writes a sentence.

**THE FOURTH STATE IS READER-ONLY, AND IT CAN HIDE THE WRITER-SIDE DEFECT.** Caught by
`doc-tools-7f`: a tolerant reader is fully compatible with a writer that OVERWRITES a human's
prose — the reader sees our marker, reports agreement, routing stays green, and the sentence
someone wrote is gone with nothing red anywhere. **Safe for routing, unsafe for the text, and the
tolerance removes the only signal that would have surfaced the loss.**

I checked whether the reader can compensate. **It cannot** — a reader seeing our marker has no way
to know whether prose preceded it. That is not a gap in the reader's half; it is why the writer's
behaviour must be DECLARED rather than implemented into existence:

    reader   foreign description -> ABSENT, never MISMATCH      settled
    writer   foreign description -> overwrite? refuse? merge?   OPEN — the SDK declares it

**And "refuse" carries a known cost worth naming before it is chosen:** it turns a human's sentence
into an ingest failure, and a check that fails ingest for documenting a collection is the
over-constrained seal that gets DISABLED — the same shape as a commit seal whose only remedy its
own docstring forbids. Disabled takes the rule with it.

**A CARRIER NEITHER SIDE NAMED, which changes what is being chosen between:** the record does not
have to live on the collection it describes. A separate small collection — one object per
described collection — touches no human-facing field, needs no splice-able or self-identifying
encoding (the carrier is ours by construction), and makes overwrite/refuse/merge moot. It costs an
extra collection, a read at open, and a convention for a recreated collection — where
`description` has the genuine advantage of dying with the collection it described. **A marker
object inside `OntologyClass` or `Predicate` would be a candidate in hybrid search and must not be
considered**; only a separate collection.

**If `description` is chosen, the encoding must be SELF-IDENTIFYING**: decidably ours or not-ours without guessing.
Strict JSON with a discriminating key, a sentinel prefix, or a fenced region inside prose — the
choice is the SDK's; the required property is that *"not ours"* and *"ours, malformed"* are never
the same observation, because they want opposite behaviours. The same decision answers 7f's
question of whether the Protocol OWNS `description` or must COEXIST with prose.

## RULED 2026-09-14 — THE CARRIER IS A SEPARATE COLLECTION, NOT `description`

**All three ways of encoding into `description` are traps, and the ruling names each:** overwrite
loses a human's text with nothing red; refuse turns an ingest failure into the reason the check
gets muted; **splice is a parser over a field that was never a format.** A carrier that is ours
alone has none of them, and the encoding question closes rather than resolving — there is no
longer a field to encode into.

    one small collection, one object per described collection:
      collection name · embedding model · model version · dimension · written-by · creation stamp

Declared in the SDK as part of the `MeshVectors` contract — **the collection, the schema, AND both
behaviours**, so neither implementer invents the other's half. The writer creates or replaces the
marker **in the same act that creates the collection**, and never touches `description`.

### The two seals that travel with it

**1. The marker collection is never a search candidate.** Excluded from hybrid search and from the
routable class pool BY NAME, and the census asserts it. A marker object turning up as a neighbour
is the failure this carrier could introduce, and it is one a seal can catch. (A marker object
*inside* `OntologyClass` or `Predicate` — the cheaper version of the idea — is ruled out for
exactly that reason.)

**2. A recreated collection cannot inherit a stale marker.** The marker is written in the same act
as the collection's creation — fold-not-hand-run, the way the prime writes its own `:PrimeRun` row
— and carries the creation stamp; **the reader treats a marker older than its collection as
ABSENT.** That is the one real advantage `description` had — dying with what it described — kept
without the cost.

### MEASURED: there is no collection creation timestamp, and the proxy has two caveats

Checked on sandbox before relaying the ruling, because seal 2 depends on a value that may not
exist: **Weaviate's class schema carries nothing time-like at all.** The workable form is the
**oldest object's `creationTimeUnix`** (`OntologyClass`'s is `1780980389974` = 2026-06-09T04:46:29Z,
sorted-ascending query verified). A recreated-and-re-ingested collection has all-new objects, so
the oldest moves past a stale marker and the comparison holds. Two caveats belong in the contract
rather than in an implementer's head:

* **An EMPTY collection has no oldest object**, so its marker cannot be dated → ABSENT, report the
  gap, open. Not "valid".
* **If the writer ever PRESERVES `creationTimeUnix` on re-ingest, seal 2 is silently defeated** —
  the proxy stops moving while the vectors change underneath, and a marker for vectors that no
  longer exist reads as current. A writer-side requirement, and the one that decides whether this
  carrier is safe.

### Kept from the superseded `description` build, because it is the strongest part of it

The SDK's first declaration (`6649128`, before the ruling reached it) had **one implementation of
the write plus an admission check that REFUSES a writer whose output is wrong** — proven by
stubbing a destroying writer and watching admission reject it. *Measured, not argued.* **The
carrier changed; that mechanism should not.** One implementation of the stamp write, admission
checking its output, and neither side writing a parser.

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
