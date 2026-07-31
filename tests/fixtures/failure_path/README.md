# Failure-path fixtures — MAINTAINED artifacts, not one-off hacks

**The permanent condition this directory exists for: a healthy pipeline STARVES its failure paths
of organic inputs.**

Witnessing refusal routing on 2026-07-31 needed a notice the extractor could not read. There
wasn't one. The vision-cap + text-layer work had engineered the crop-failure case out of
existence — PCN-2683, which used to fail 2 of 5 table crops, now yields 402/402 parts in under a
second. So the live witness ran against a **real-shaped synthetic**, honestly labelled.

That is not a temporary gap that closes when the corpus grows. It is the steady state, and it
inverts the usual fixture instinct:

> The better the pipeline gets, the RARER the organic failure input, and the more the failure
> path depends on a fixture nobody can regenerate from production.

So failure-path fixtures are **maintained artifacts**: committed, versioned, with their
construction documented — because the next person to change the triage path has to re-witness it,
and the organic case will be rarer then than it is now. A synthetic reconstructed from memory at
that point is a synthetic nobody can trust.

## Rules

1. **Derive from a REAL artifact.** Every fixture here starts from a real extraction output and
   mutates it minimally. A hand-authored JSON drifts from the producer's actual shape the first
   time doc-tools changes a field, and then the failure path is sealed against a shape that no
   longer exists ([[feedback_synthetic_data_no_mock_leak]]: real-shaped synthetic INTO the real
   backend, never a mock in the data path).
2. **Document the mutation, not just the result.** The builder script IS the documentation —
   what was changed and why it produces the failure.
3. **Name the failure it evokes**, so a reader knows what breaks if the fixture rots.
4. **Never let one serve two paths.** A fixture that evokes two failures at once cannot tell you
   which one your seal caught ([[feedback_fixture_must_exercise_paths]]).

## Inventory

| fixture | evokes | built by |
|---|---|---|
| `cropfail_review.py` | `NO_PARTS_EXTRACTED` — the extraction FLAGGED the document and produced zero parts (partial table-crop failure). Drives refusal routing → triage task. | derived from a real `Diodes_PCN_2683` review.json |
