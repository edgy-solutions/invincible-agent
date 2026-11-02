# To the architect, via Chris: hand-entered parts are built as a promotion with `added` edits. The rung is asked of the SDK. Also, the decision test's red was mine, and it is fixed.

from: invincible-agent/lane/01 · 2026-10-23 · answers the 10-23 ruling (items 1 and 2)

## Done

- **The 0.4.65 note is on master.** The push was `360fbeb6..0c227330`, a fast-forward checked
  with is-ancestor just before it.
- **The `test_the_status_is_the_decision` red was mine.** It is red on 207 and on master too.
  - The test read `mark_task_resolved` through a fixed 3000-character slice.
  - My 204 (`d0f80092`) pushed the UPDATE past the end of that slice. That turned one arm red,
    and it left the coercion arm blind to the function's tail.
  - It is fixed on `lane/01-208` at `a3b05618`: all three arms now read the whole function.
  - Measured with two mutants:
    - A coercion to `rejected` written at the tail now reds `EVERY_DECLARED_VERB_IS_STORABLE`.
      Under the old slice it did not.
    - Renaming the decision column reds the decision-column arm.
- **The roll order is noted as ruled.** 207 goes Monday. 208 goes only with cortex's
  empty-confirm card and 7f's force-text reader.

## Hand-entered parts: how they land (read, then decided; overrule if you meant otherwise)

What the code does today:

1. **Promotion never writes extracted rows.** Doc-tools writes them at ingest as `SUBJECT_TO`
   edges onto the `SustainmentNotice` node.
2. **Approval reconciles those edges against the reviewed set.** `promotion.act`, in
   `src/iagent/promotion.py`, does this.
3. **An `added` row edit already MERGEs a new Component and its edge onto the same notice.**
   The edge carries `obtained_via` and `corrected_by`. This is `apply_row_edits`, in
   `src/iagent/promotion_stores.py`. The edits also go to `corrections/` for doc-tools' RDF.

So I read "land as extraction rows on the same notice … promote like any other row" as follows.
The steward's hand entry on the add-missed-part task **is** a `promotion.act`, with zero reviewed
rows and N `added` edits:
- each edit has `obtained_via=steward-entered`, `evidence_ref {page, bbox: null}` and
  `corrected_by`;
- an `extraction_defect` is filed with those edits. They use the existing op `added`, which is
  your "op=add".

In the graph these are `SUBJECT_TO` edges on the same notice, the same as a promoted extracted
row, except for `obtained_via`. This path needs no second artefact and no merge into
`/ingest/{id}/extraction`.

The other reading I rejected: write the rows first, then file a separate `document_promotion` for
a second act. It needs a second artefact, a merge path in the extraction route, and a second
review of rows the same steward pool just typed.

Two consequences of this design:
- **Who may enter parts.** Hand entry is a promotion-grade write, so it needs the promotion
  audience's `check_can_act`. **The dropper may confirm "no parts" but may not enter parts**,
  unless they hold that grant.
- **A latent defect gets fixed in the same build.** `apply_row_edits` writes the literal
  `"steward-corrected"` onto the edge and ignores the edit's own `obtained_via`. Today every edit
  is steward-corrected, so nothing is wrong yet. Without the fix, a steward-entered row would be
  stored as corrected, and the one field you said tells them apart would be wrong.

## Blocked on the SDK, and one question to 7f

- **The SDK.** `steward-entered` is a seventh rung in the SDK's closed ordered tuple. I have asked
  `iagent-mesh-sdk/lane/ca` to ride it on v0.9.11, the tag 205's null bbox already waits on. The
  packet is `iagent-mesh-sdk/sessions/2026-10-23-packet-to-ca-a-seventh-obtained-via-rung-steward-entered-ride-v0-9-11.md`.
  The build starts when the tag exists.
- **7f.** `apply_row_edits` refuses when no `SustainmentNotice` node exists. Doc-tools appears to
  MERGE the notice per section even with zero rows, but I inferred that and did not measure it.
  I will ask 7f to confirm it for a header-only notice.

— invincible-agent/lane/01
