---
id:         generalist-verbs-bulk-declared-on-content-kinds
status:     open
owner:      unassigned
blocked-on: **which registration path types these verbs against content kinds** — engine-w and engine-e each register their own verbs, and the leak is either (a) an `input_uri` declared too broadly in one of their manifests, or (b) a saga/sensor path materialising kind-class edges as a side effect. Those have different fixes and guessing between them is how the wrong one ships. Trace the four edges' provenance before editing anything.
closed-by:
code-site:  tests/routing/test_b2_ingest_sandboxrtx.py
repo:       invincible-agent
summary:    engine-w's `mesh:retrieveKnowledge` is typed against three `mil:*DataModule` content kinds and engine-e's `mesh:queryKnowledgeGraph` against a fourth, putting all four into the resolver candidate pool. B0 §3's Wave-3 rule is one verb per demonstrated question; this is a bulk sweep. B4 has NOT shipped — the guard that catches it (`test_pool_hold_kind_classes_have_no_verbs_yet`, both ingest files) is correct and had simply never run in CI, because its file skipped on "Neo4j unreachable" until the port-forward set landed 2026-08-26.
---

# Generalist verbs are declared in BULK against content kinds

engine-w's `mesh:retrieveKnowledge` is typed against three `mil:*DataModule` content kinds and
engine-e's `mesh:queryKnowledgeGraph` against a fourth, putting all four into the resolver
candidate pool. B0 §3's Wave-3 rule is one verb per demonstrated question; this is a bulk sweep.

B4 has NOT shipped — the guard that catches it (`test_pool_hold_kind_classes_have_no_verbs_yet`,
in both ingest files) is correct and had simply never run in CI, because its file skipped on
"Neo4j unreachable" until the port-forward set landed 2026-08-26.

## THE BLOCKER IS THAT QUESTION, not the fix

engine-w and engine-e each register their own verbs, and the leak is either:

* **(a)** an `input_uri` declared too broadly in one of their manifests, or
* **(b)** a saga/sensor path materialising kind-class edges as a side effect — the
  `seeder-manufactures-declarations` shape one layer over.

Those have different fixes and **guessing between them is how the wrong one ships.** Answer it by
tracing the four edges' provenance before editing anything.

Both guards now carry an obsolescence condition, so they retire honestly when B4 lands rather than
being deleted by someone who assumes `_yet` means expired.

## Guard sites

The guard named above lives in both ingest files:

* `tests/routing/test_b2_ingest_sandboxrtx.py`
* `tests/routing/test_b3a_ingest_helmet_40051.py`

`code-site:` carries the first because the header field takes a single path; the second is recorded
here so a reader looking for "both ingest files" finds both.

## Provenance of this file

**This packet's content is recovered, not authored.** It existed as a hand-added entry in
`docs/BOARD.md` — an edit to a GENERATED PROJECTION, which the board's own header warns is "a lie
the next regeneration silently reverts." On 2026-08-27 that is exactly what happened: a pytest run
regenerated the board and the entry was gone, because `scripts/generate_board.py`'s only argument
test was `if "--check" in sys.argv`, so `tests/test_board_drift.py`'s positive control — which
invokes the generator with `--help` to prove it is runnable — took the WRITE path on every suite
run.

The prose above is that entry verbatim; the frontmatter is transcribed from the fields it already
declared. The generator now refuses to write on `--help` or any unrecognised flag, so the failure
that ate this once cannot happen quietly again.

A projection's contents are owned by its sources. This file is the source.
