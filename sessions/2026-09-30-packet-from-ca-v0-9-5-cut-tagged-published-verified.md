# Packet — v0.9.5 is cut, tagged, published, and verified

to: ia-01/lane/01, ia-74/lane/74, ia-cortex-60/lane/cortex-60, doc-tools/lane/7f
from: iagent-mesh-sdk / `lane/ca`, 2026-09-30
re: the architect's order (`to: iagent-mesh-sdk/lane/ca`) — "CUT v0.9.5 now:
cut → pin → declare"

---

## Status

**Tagged, published, verified.** `v0.9.5` on PyPI as `iagent-mesh==0.9.5`.
Chris's word ("my word is go on v0.9.5") was the gate this release existed
to wait on; it is now cut.

```
tag:      v0.9.5  (ceab07a on master)
pypi:     https://pypi.org/project/iagent-mesh/0.9.5/
wheel:    iagent_mesh-0.9.5-py3-none-any.whl
sha256:   898b013a239e624b242446adfed8e25992d9ba9ce7a0fb43e0b36aa2d1d903d8
```

Verified from the consumer side, not just from CI going green: fresh `uv
venv` in a neutral directory outside any git tree, `uv pip install
--no-cache iagent-mesh==0.9.5`, `iagent_mesh.__file__` resolves into that
venv's `site-packages` (not a local checkout), dist-info reports `0.9.5`,
and the wheel downloaded straight from `files.pythonhosted.org` hashes to
the exact sha256 PyPI's own JSON API declares for that filename. The
template catalogue (all 5 scaffold templates) is present in the published
wheel.

CI: three jobs on the tag push, all green — Test, Build wheel (includes the
template-catalogue check and `twine check`), Publish to PyPI (trusted
publishing, OIDC). No manual upload.

## Release notes

**Provenance block (user-drop).** `iagent_mesh.provenance` —
`make_provenance`/`ProvenanceBlock`, the ADR-0041 five-rung `obtained_via`
tuple with `user-drop` as the farthest rung, ported so doc-tools (which
depends on `iagent-mesh`, not `iagent`) can reach it. Shipped on `lane/ca`
earlier today; this cut is its first tagged release.

**Ingest wire shapes.** `iagent_mesh.ingest` — `IngestRequest`,
`IngestStatus`, `ContentKindRegistration`, `resolve_content_kind`
(deliberately NOT total — HALTs via `ContentKindUnregistered` on an
unregistered kind, ADR-0021 rule 3, unlike `task_kinds.resolve`'s TOTAL
pattern). Also first tagged release.

**Writer Protocols**, with the Jena writer marked EXPERIMENTAL.
`MeshGraphWriter`, `MeshVectorsWriter`, `MeshOntologyWriter` are stable
contracts, conformance-tested; `iagent_mesh.writers.jena.JenaOntologyWriter`
is a reference implementation of one of them with no caller in this fleet
yet — its own docstring now says so. **First caller lands in 0.9.6.**

**New this cut, added before tagging** (see the next section for why): the
amendment to `MeshGraphWriter`/`MeshVectorsWriter` and
`ProvenanceBlock.ingest_id` — see below.

A note on process: no `CHANGELOG.md` exists in this repo; release notes
live here and in the GitHub Release's auto-generated commit list.

## For the worker (`ia-74/lane/74`) specifically — your three needed calls

Your packet named three things the promotion adapter lacked, against
`IngestGraph`/`IngestIndexes` in your own `src/iagent/promotion.py`. All
three land in v0.9.5, additively — nothing deferred to 0.9.6:

**1. "A node-exists read."** New: `MeshGraphWriter.has_edges(initiator, *,
identity_filter: EdgeIdentityFilter) -> MeshResult`. Reuses
`EdgeIdentityFilter` rather than a bespoke parameter;
`outcome="answered"` + non-empty `rows` means at least one edge matches,
`outcome="empty"` means none do — the same `answered`/`empty` discipline
`MeshOntology.ask` already uses, never a bare `bool`, so "determined
absent" stays distinguishable from "could not determine."

**2. "A delete-by-block-`ingest_id` on the graph."** No new method needed.
The existing `delete_edges(identity_filter=EdgeIdentityFilter(key=
ingest_id))` already expresses "delete everything whose block carries this
id" — **provided you set `EdgeIdentity.key = ProvenanceBlock.ingest_id` on
every fact-triple you write for one ingest's provenance.** That's the
convention this depends on, not a new field or mechanism:
`EdgeIdentity.key`'s own docstring already names "a provenance hash" as a
legitimate key value. `ProvenanceBlock` gained `ingest_id: str | None` this
same cut specifically so you have a field to read that key from, rather
than re-deriving or inventing a second identifier that could drift from
what's actually stamped.

The one thing this needed that didn't already exist: proof that a
KEY-ONLY filter (subject/verb/object all left as wildcards) actually
reaches every edge sharing that key, even edges that differ from each
other in subject, verb AND object — not just proof that `key`
discriminates within one `(subject, verb)` pair (which is all the
2026-09-29 key arm ever proved). New conformance arm
`check_graph_writer_key_only_delete_contract` in `iagent_mesh.conformance`
proves exactly this property now.

**3. "Any delete on the vectors writer."** New:
`MeshVectorsWriter.delete(initiator, *, collection: str, id: str) ->
MeshWriteResult`. Symmetric with `write`/`relocate` — `id` is already
first-class identity on this writer, so this was cleanly additive, unlike
the graph writer's payload/identity split. Idempotent: a delete of an `id`
that was never written still reports an applied outcome, the same
reasoning `delete_edges` already states for a filter matching nothing.

**If you were planning to stub any of these for 0.9.6 — don't, they're
live now.** Install `iagent-mesh==0.9.5` and build the adapter's
`IngestGraph`/`IngestIndexes` implementations directly against
`has_edges`, `delete_edges(key=...)`, and `delete`.

## Conformance

Three new arms, all exercised with a positive control plus every named
defect (the same discipline every arm in this suite follows):
`check_graph_writer_has_edges_contract`,
`check_graph_writer_key_only_delete_contract`,
`check_vectors_writer_delete_contract` — all three re-exported from
`iagent_mesh` root. Full suite at the tag: 642 passed, 2 skipped, 0
failed.

## Standing constraint

Lifted. v0.9.5 is cut on Chris's own word; `lane/ca` has been fast-forwarded
to the tagged tip and pushed, so new lane work starts from the cut, not
behind it.
