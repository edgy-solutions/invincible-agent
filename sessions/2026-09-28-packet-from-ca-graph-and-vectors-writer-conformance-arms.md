# Packet from ca — MeshGraphWriter and MeshVectorsWriter conformance arms, and the fixtures they need

to: ia-74/lane/74
from: iagent-mesh-sdk / `lane/ca`, 2026-09-28
re: the overnight order, item 1 — "Conformance arms for MeshGraphWriter and MeshVectorsWriter (the
worker builds against them tonight); packet the fixtures."
cites: `iagent_mesh/conformance.py::check_graph_writer_contract`,
`iagent_mesh/conformance.py::check_vectors_writer_contract`,
`tests/test_writer_conformance.py` (all on `lane/ca`, **UNRELEASED — no tag, not in any pinned
SDK, no release of v0.9.5 without Chris's word**), `check_ontology_writer_contract` for the shape
both mirror

## What the SDK ships (on `lane/ca`, not cut)

    check_graph_writer_contract(*, call_write_edge, call_read_written_edge, call_read_unwritten_edge)
    check_vectors_writer_contract(*, call_write_with_failing_embedder,
                                     call_write_with_failing_embedder_opted_out,
                                     call_relocate_matching_dimension,
                                     call_relocate_wrong_dimension,
                                     embed_call_count)

Both proven against a conforming in-memory fake plus deliberately broken variants (14 new tests;
566 in the suite, 0 failed, no regressions). Same discipline as `check_ontology_writer_contract`:
a write's reported outcome is never trusted on its own — each arm verifies the mutation applied by
an independent read or an independent measurement, and each arm's own fixture is checked to
discriminate the fix from the defect before either check runs.

## `check_graph_writer_contract` — what it asserts, and why

`call_write_edge` writes one edge for a `(subject, verb)` pair you bind. `call_read_written_edge`
and `call_read_unwritten_edge` are both `MeshGraph.edge()` calls bound to a PERSON initiator — one
for the pair just written, one for a DIFFERENT pair you never wrote.

1. **The write must actually apply** before anything is verified — a `refused`/`failed` write
   fails here by name, before any read runs.
2. **A written edge must read back `answered`.** A `write_edge` that reports `written` while the
   edge is not actually reachable is caught here, not trusted.
3. **An unwritten edge must read back `empty`.** A read that answers regardless of what was
   written cannot prove the write above took effect at all.
4. **The fixture must discriminate**: if both reads come back identically (both `answered`, or
   both `empty` because nothing was ever really stored), the arm refuses on that basis before
   either specific message is reachable.

Note this arm proves something narrower than the ontology arm: `MeshGraph.edge` has no scope
parameter the way `MeshOntology.ask(graph=...)` does, so there is no equivalent
within-scope-vs-default-scope claim to make. What's proven is "the write took effect, full stop" —
written-vs-never-written, not written-correctly-scoped-vs-leaked.

### The fixture you need to supply

    person = Initiator(subject="user:cnogradi", kind="person")
    written_subject, written_verb, written_object = "<iri>", "<verb>", "<iri>"
    unwritten_subject, unwritten_verb = "<a different subject>", "<a different verb>"

    check_graph_writer_contract(
        call_write_edge=lambda: graph_writer.write_edge(
            person, subject=written_subject, verb=written_verb, object=written_object
        ),
        call_read_written_edge=lambda: graph_reader.edge(person, written_subject, written_verb),
        call_read_unwritten_edge=lambda: graph_reader.edge(person, unwritten_subject, unwritten_verb),
    )
    # and, as for the read side: check_writer_offline(graph_writer, operations=[("write_edge", ...)])
    # for identity admission (person + delegate; service refused) and the MeshWriteResult return type.

The unwritten pair must be a pair your store has genuinely never seen — not merely one you didn't
write in this test run, if your store persists across runs.

## `check_vectors_writer_contract` — what it asserts, and why

`MeshVectors.nominate` (semantic search) is fuzzy and ranked — not a deterministic oracle for "did
this exact write land" — so this arm proves structural properties directly against your own
fixture rather than a read-side round trip. You supply a deliberately-failing `Embedder` for the
`write` calls, a matching/mismatched vector pair for the `relocate` calls, and a call counter on
your Embedder.

1. **`vector_required`'s default (`True`) must REFUSE a failed embed**, not silently complete
   without a vector — the sixty-seven-day silent-BM25 defect (`write_results.py`), replayed at
   write time. Checked by name: a default-path write that still `.applied` is caught before the
   outcome string is even read.
2. **`written_without_vector` is reachable ONLY by the caller's own `vector_required=False`
   opt-out** — a writer that reports a clean `written` for an opted-out vectorless write is
   caught; so is one that refuses the opt-out anyway (caught by fixture-discrimination, since both
   calls would then read `refused` identically).
3. **`relocate` must refuse a dimension mismatch.** A relocate that stores a mismatched vector
   under any outcome that still `.applied` is caught, whether it reports a bare `written` or tries
   to flag the mismatch while still storing it.
4. **`relocate` must never call the Embedder.** Proven by `embed_call_count` — your own counter,
   read before and after both `relocate` calls — not by inspecting outcomes, since a relocate that
   quietly re-embeds and still returns the right `MeshWriteResult` values would otherwise pass.
5. **The fixture must discriminate** at both pairs (default-vs-opted-out, matching-vs-mismatched)
   before either pair's specific checks run.

### The fixture you need to supply

    embedder = YourEmbedder(should_fail=True)   # or a stub wrapping the real one to force a failure
    good_vector = [<a vector at your Embedder's declared dimension>]
    wrong_vector = [<a vector at any OTHER length>]

    check_vectors_writer_contract(
        call_write_with_failing_embedder=lambda: writer.write(
            person, collection=collection, id="fixture-1", text="anything"
        ),
        call_write_with_failing_embedder_opted_out=lambda: writer.write(
            person, collection=collection, id="fixture-2", text="anything", vector_required=False
        ),
        call_relocate_matching_dimension=lambda: writer.relocate(
            person, collection=collection, id="fixture-3", vector=good_vector
        ),
        call_relocate_wrong_dimension=lambda: writer.relocate(
            person, collection=collection, id="fixture-4", vector=wrong_vector
        ),
        embed_call_count=lambda: embedder.calls,   # or however your Embedder tracks it
    )
    # and, as for the read side: check_writer_offline(writer, operations=[("write", ...), ("relocate", ...)])

The failing-embedder fixture needs to fail DETERMINISTICALLY (raise, not flake) for both `write`
calls — a real endpoint you point at a bad URL, or a stub that always raises, both work; a
timing-dependent failure would not discriminate reliably.

## One reading of mine you should overrule if it's wrong

`check_graph_writer_contract`'s "never written" fixture is a genuinely different `(subject, verb)`
pair, not the same pair before the write happens — I did not build a "read-before-write" variant,
since `MeshGraphWriter` has no ordering guarantee across calls the way a single upsert-then-ask
does, and a store that answers a pending write early would be a separate, weirder defect than the
one this arm targets.

Lane: ia-ca/lane/ca
