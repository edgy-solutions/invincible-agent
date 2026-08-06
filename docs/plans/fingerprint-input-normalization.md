# BOARD ITEM — fingerprint input normalization

**Must land BEFORE the first real promotion.** Not because the fingerprint is broken today, but
because promoting against a pre-normalization key mints a key that normalization will later orphan
— the identity-key-transition class, and it is avoidable purely by ordering.

## Why this became load-bearing

`format_fingerprint()` was a recording device: it stamped decision records so a future corpus could
say which way it was wrong (ADR-0034 open question 3). As of phase 1.3 it **routes** — it is half
the trust key, derived from the artifact, deciding supervised vs autonomous. Inputs that were merely
untidy are now trust-key material.

## The corpus facts (measured across all 16 real artifacts, 2026-08-06)

| fact | count | consequence |
|---|---|---|
| no `header.mfr` → `unknown/...` | 4 of 16 | one key spanning unrelated vendors — now **unpromotable** by the sentinel-fingerprint guard |
| `onsemi` vs `ONSEM` | 2 spellings, 1 vendor | **two fingerprints**; trust earned under one silently excludes the other |
| `doc_type` absent → defaults `pcn` | 9 of 16 | third segment is an assumption wearing a fact's clothes |

## The two pieces

### 1. Manufacturer canonicalization

`onsemi` and `ONSEM` are the same vendor and must produce the same key. A promotion for one spelling
silently excludes the other — fail-safe and legible via `admitted_by`, but a **trust decision
fragmenting on orthography**, and evidence never accumulates for the split-off variant.

Apply the phonebook discipline: a small, git-asserted mapping table through the rails, because `mfr`
strings are now trust-key material and a mapping that lives in code is a mapping nobody can audit.
Deliberately NOT fuzzy matching — a canonicalization that *guesses* would merge vendors that merely
look alike, which is the opposite failure and a worse one.

**THE PRECEDENT, and it dictates the shape.** This exact disease was solved once already in this
codebase as the **compact→full-IRI canonicalization** class-fix (`scripts/merge_compact_into_canonical.py`,
`scripts/migrate_compact_to_full_iri.py`; named as a class at
`src/iagent/defs/dynamic_supervisor.py:1539`). Its lesson: storage-form variation splits one logical
entity into several records, and **the durable defence is canonical-form resolution at the
comparison boundary — not cleaning up each duplicate.** `onsemi`/`ONSEM` is the same disease in a
new organ: spelling divergence splitting one logical vendor into two trust keys.

So: **canonicalize INSIDE `format_fingerprint()` itself**, which IS the comparison boundary. Then no
storage-form variation in `header.mfr` can produce two keys for one vendor, by construction. A
cleanup pass over artifacts is explicitly the wrong shape — you would never run it faster than
extractions accrete.

**Misses fail safe by construction:** an unmapped vendor canonicalizes to its own literal segment,
which is simply a key nobody has promoted yet. And the degenerate end is already contained — the
sentinel-fingerprint guard makes `unknown/*` unpromotable.

### 2. `doc_type` explicit-or-sentinel

Today a missing `doc_type` silently becomes `pcn`. That default is **indistinguishable from a
genuine PCN**, which is exactly why the sentinel guard does not — and cannot — cover this axis: per
the default-collision rule, a guard whose asserted value the system produces by default cannot tell
"identified" from "defaulted".

So the fix is upstream, at emission: emit the real `doc_type` or an explicit sentinel. Once the
default is distinguishable, extending the sentinel guard to this segment becomes possible **and only
then is it meaningful.**

## Ordering constraint

Both pieces change what `format_fingerprint()` emits for existing artifacts. Any promotion ratified
before them is keyed on a fingerprint that will not match afterwards — the promotion silently stops
applying (safe direction, invisible), and the accumulated evidence is orphaned.

So: **normalize first, promote second.** The corpus is currently unpromotable anyway
(`pipeline_version` is `(none)` on every real artifact until doc-tools rebuilds), which makes this
window free — the ordering costs nothing if taken now and costs a migration if taken later.

### SEQUENCE RULING — a CROSS-REPO constraint, stated as one

> **Normalization merges before the doc-tools rebuild rolls.**

The free window is real, but **it closes from the other repo's side.** The orphaning hazard is
currently zero only because no artifact carries a stamp; the moment doc-tools is rebuilt and
re-extracts, real artifacts start deriving full keys — and any promotion against a
pre-normalization fingerprint becomes orphanable.

Nothing in `invincible-agent` signals when that happens, which is exactly why this is written as an
ordering constraint between repositories rather than as a preference. Whoever rolls the doc-tools
rebuild needs to know this item gates it.

## Related

- The sentinel-fingerprint guard (`unknown/*` unpromotable) is landed and is the *containment*, not
  the fix: it stops the degenerate key being promoted; it does not make the fingerprint partition
  correctly.
- ADR-0034 open question 3 predicted exactly this needed corpus data. This is that data.
