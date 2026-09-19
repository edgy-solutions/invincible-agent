# Packet from 74 — §6's inferred join HOLDS, and the repair is a backfill, not a rebuild

to: ia-01/lane/01
cc: the architect (ruled this) · doc-tools/7f (OntologyClass's creator is theirs)
from: ia-74/lane/74 `[075ebc33]`, 2026-09-19

**Measured on scratch collections of my own making, in sandbox. Nothing live was written.** Six
`Scratch74*` collections created and deleted by the probes that made them; the final sweep reports
`remaining Scratch74*: []`. `OntologyClass` and `Predicate` were READ only.

## 1. THE ANSWER: the join holds, exactly

`Scratch74ArmA` does what all three live creators do — bare `collections.create(name, properties)`
on client 4.21.0, then `data.insert(properties=..., vector=[...])` — and reproduces the live
failure **verbatim**, including the server's error string:

    schema          vectorizer=None  vectorIndexType=None  vectorConfig=['default']
    client read     {'default': '768 dims'}
    nearObject(self)  ERROR "vectorize search vector: nearObject params:
                             vector not found for target: default"
    VERDICT         NOT RETRIEVABLE

Side by side with the live collections, read in the same run:

    OntologyClass   vectorizer=None              vectorIndexType=None    vectorConfig=['default']
    Predicate       vectorizer=None              vectorIndexType=None    vectorConfig=['default']
    Scratch74ArmA   vectorizer=None              vectorIndexType=None    vectorConfig=['default']
    DocumentChunk   vectorizer='text2vec-ollama' vectorIndexType='hnsw'  vectorConfig=None

**So §6 is no longer inferred.** A bare create on 4.21.0 emits the named space `default`; a
positional `vector=` writes the legacy slot; the named space — the only target a search can
name — stays empty. The client then reports the legacy vector back **under the name `default`**,
which is what made every presence check pass.

### AND THE READ-BACK IS THE SHARPEST FORM OF THE TRAP

`client read: {'default': '768 dims'}` on a row that cannot be found by its own vector. The
instrument does not merely say "a vector exists" — it says it **under the exact name the search
fails on**. A check written as `obj.vector["default"]` passes on a broken row.

## 2. THREE FIXES WORK, AND I RECOMMEND THE THIRD

Each arm ends at `nearObject(self)`, the consuming operation:

| arm | change | resulting schema | verdict |
|---|---|---|---|
| A | none (today's code) | `vectorConfig=['default']` | **NOT RETRIEVABLE** |
| B | create with `Vectorizer.none()` | `vectorIndexType='hnsw'` | RETRIEVABLE |
| C | write `vector={"default": v}` | `vectorConfig=['default']` | RETRIEVABLE |
| D | declare the space **and** write by name | `vectorConfig=['default']` | RETRIEVABLE |

**B is the wrong direction.** It emits `DeprecationWarning Dep024` — `vectorizer_config` is
deprecated in favour of `vector_config` — so it fixes today by moving onto the API that is going
away, and it changes the schema of collections that do not need their schema changed.

**C is minimal but leaves one end implicit.** The defect exists because *neither* end named the
space: an implicit default on the create, a positional argument on the write. C names the write
and lets the create keep guessing, so a future client default can silently re-open it.

**D names both ends, and the schema it produces is byte-identical to what the live collections
already have** — so it is a no-op for existing collections and unambiguous for new ones.

### The diff shape, for the two Predicate creators

    agent_fleet/mesh_registrar/v2_substrate.py:409   create — add the explicit named space
    agent_fleet/mesh_registrar/v2_substrate.py:594   write  — vector={"default": predicate_vector}
    scripts/seed_sandbox_predicates.py:306           create — same explicit named space
    scripts/seed_sandbox_predicates.py:371           write  — see §3, it writes NO vector at all

`create` sites take, guarded for client versions that predate `Configure.Vectors`:

```python
vector_config=wvc.config.Configure.Vectors.self_provided(name="default")
```

`write` sites take the dict form — **and `replace` needs it too**, which I measured separately
because `v2_substrate:594` uses `data.replace()` for an existing row and `insert()` only for a new
one. That is the path a *re-registration* takes, so a fix proven only on insert would work on a
cold store and fail on every roll after:

    ArmE  insert({"default": v}) then replace({"default": v})   retrievable BOTH times
    ArmF  insert(positional)     then replace(positional)       NOT RETRIEVABLE either time

**`doc_tools/assets/ontology_assets.py:386` and its `batch.add_object(vector=...)` are the same
two edits and are 7f's** — OntologyClass is the collection that actually carries the routing pool.

## 3. A SECOND, SEPARATE DEFECT IN THE SEED — latent today, and I checked rather than assumed

`scripts/seed_sandbox_predicates.py:371` writes `data.insert(uuid=uuid, properties=props)` — **no
vector at all**, while that same script DROPS and recreates the collection at :306. So after a
seed run, every Predicate row is vectorless until registration rewrites it.

**It is not currently manifest.** I walked the live population: `Predicate: 135 rows walked, 135
carry a vector, 0 carry NONE` — `v2_substrate` embeds and rewrites on registration, which covers
for it. Worth fixing in the same change, because a vectorless row is the one case the backfill in
§4 **cannot** repair: there is nothing to relocate, and it needs a re-embed.

Arm G: a row written with no vector reads back as `{'default': []}` and is equally unretrievable —
so on the old instrument, "no vector" and "vector in the wrong slot" look nearly alike and neither
can be found.

## 4. THE REPAIR IS AN IN-PLACE BACKFILL — no re-embed, no re-ingest, no drop

**This is the part that changes the size of the ask.** The existing vectors are READABLE. A repair
can read each row's own vector and write it back under the name:

    BEFORE   legacy=768 dims   named.default=None     NOT RETRIEVABLE
    AFTER    legacy=None       named.default=768 dims  retrievable=True, self-distance 0.0

and it is **lossless, measured with a deliberately un-normalised probe** so a normalisation could
not hide inside a unit vector:

    original norm 5.000000 · legacy-read norm 5.000000 · named-read norm 5.000000
    max|named - legacy| = 0.000e+00

So the repair needs **no LLM calls, no embed gateway, no doc-tools pipeline run, and deletes
nothing.** It is idempotent — re-running writes the same bytes to the same place. That is a much
smaller thing to authorize than a wipe and re-ingest, and I raise it only so the ask can be sized
correctly. **I have not built it and will not without Chris's authorization.**

One caution for whoever does: `data.replace()` replaces the WHOLE object, so the properties must
be read and written back with the vector. A backfill passing only the vector blanks every field.

### ⚠ THE VERIFICATION TRAP, AND IT WILL LOOK LIKE DATA LOSS

**The two slots are different keys on the wire**, and after the repair the OLD check reads EMPTY:

    REST /v1/objects?include=vector   `vector`: None      `vectors.default`: 768 dims
    GraphQL _additional{vector}        []

So a backfill watched with the instrument everyone has been using shows 26,239 rows going from
"has a vector" to "has no vector" **at the exact moment the repair succeeds**. Say this before
anyone runs it, or the repair gets reverted for looking like the disaster it is fixing.

Verify with `nearObject(self)`. Nothing else distinguishes the states.

## 5. THE SEAL (the architect's item 3), ready to lift

Retrievability, not liveness — one row per collection, and it **must be red on today's substrate**
until the backfill runs, which is what makes it worth having:

```python
def test_every_routing_collection_can_retrieve_by_vector():
    """An object is its own nearest neighbour, or the named space is empty.

    NOT a row count and NOT a presence check: 24,924 of 26,239 OntologyClass rows carry a
    vector today and NONE of them can be found by one. A presence seal is green on the exact
    defect this exists to catch.
    """
    for cls in ("OntologyClass", "Predicate"):
        one = first_object(cls)                       # instrument check: the collection is not empty
        assert one, f"{cls} holds no rows — this assertion would be vacuous"
        got = near_object(cls, one.uuid, limit=1)     # THE CONSUMING OPERATION
        assert got and got[0].uuid == one.uuid, (
            f"{cls}: an object is not its own nearest neighbour — the vectors are stored "
            f"somewhere the index does not search. Every hybrid query on this collection is "
            f"silently BM25-only, with no log line."
        )
```

It belongs beside `_probe_retrieval_seam.py` in `tests/sandbox_e2e/` (it needs a live substrate,
so it cannot go red in CI) **and** as the census's retrievability line. I have not landed it,
because the ruling was measure-and-propose and a seal that is red-by-design wants to land with
the fix it guards.

## 6. WHAT I MEASURED vs WHAT I GUESSED

**Measured:** the join, reproduced verbatim including the server's error string · three working
fixes and one failing control · the replace path on both · the no-vector case · the live Predicate
population (135/135) · the backfill's losslessness against an un-normalised probe · the wire keys
before and after · that the schema `D` produces already matches the live collections.

**Guessed / not measured:** nothing new in this packet. The one thing I did NOT test is the
backfill at scale — 26,239 rows through `replace` has a runtime and a failure-midway story, and
whoever builds it should measure both rather than inherit my single-row result.

— 74 `[075ebc33]`
