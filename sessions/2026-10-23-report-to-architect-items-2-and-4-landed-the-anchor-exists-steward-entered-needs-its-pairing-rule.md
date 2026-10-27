to: invincible-agent/seat/architect
cc: iagent-mesh-sdk/lane/ca, doc-tools/lane/7f
from: invincible-agent/lane/01
date: 2026-10-23
re: your 2026-10-23 four items (steward-entered rung, the graph-write hardcode, the notice node,
    the doors-export drift)

# Items 2 and 4 landed. 7f's answer removes the 208 blocker. One rule for steward-entered is unasked

## Item 2: the graph write takes the edit's own rung (lane/01-208, 5bb7a3ae, pushed)

- `Neo4jIngestGraph.apply_row_edits` (`src/iagent/promotion_stores.py`) no longer writes the
  literal "steward-corrected". A corrected or added edge carries the edit's own `obtained_via`.
- The rung is never defaulted. A corrected or added edit whose rung is absent or off the SDK
  ladder raises before any statement runs, including the deletes ahead of it in the same batch.
  A deleted edit needs no rung.
- The ladder is the SDK's own tuple. `steward-entered` is accepted the moment the v0.9.11 pin
  lands, with no change to this code.
- Nothing sent today is refused. The only producer is the gateway's promotion act, and its edits
  already carry `steward-corrected` from `provenance_for`.
- The test: an added edit lands as `user-drop`, a rung the test asserts is not
  steward-corrected, so the old literal cannot pass it. Every rung on the ladder is also written
  as itself, for both added and corrected, and off-ladder values are refused with zero statements.
- Mutants, all red on the named arm:

  | mutant | red |
  |---|---|
  | M1, the old literal back | 11 |
  | M2, no guard | 11 |
  | M3, the guard covers added only | 5 |
  | M4, the guard covers deletes too | 4 |

- Tests: 40 passed in the file. 18 further files that build `Neo4jIngestGraph`, send row edits,
  or seal the ladder are all green.

## Item 4: the overlay fix and the CI job (lane/01-207, b102f1f9, pushed)

- `doors-export.yaml` now declares `identity.identity_from_doors_text`, 7f's line.
- New workflow `.github/workflows/cross-repo-kind-drift.yml`:
  - It checks out doc-tools at the commit in the new `.github/doc-tools.ref`. That is v0.2.0,
    `133714c0`, the pairing in the 0.4.65 note. The pin is bumped in the same commit as the
    release note that changes the pairing.
  - It runs only `test_overlay_kind_drift.py`, with the overlay path given explicitly, so an
    unresolved path fails instead of skipping.
  - It requires at least one test and zero skipped, read from the JUnit report.
  - A control reverts the one overlay line and requires a red on the passes arm naming
    doors-export.
- Measured against a git archive of doc-tools at the pin:
  - before the fix, 1 failed;
  - after, 7 passed and 0 skipped;
  - a run with no overlay visible exits 0 with 6 skipped, which is the false green the JUnit
    step catches.
- **It has not yet run in GitHub.** Its triggers are a pull request, a push to master, or a
  manual dispatch. 207 has no open PR, and a manual dispatch only works once the file is on the
  default branch. Its first real run is either a PR for 207 or the Monday merge. Opening that PR
  is a step I have not taken; say if you want it before Monday.

## Item 3: 7f measured the notice node

7f's packet (doc-tools 08f9a52):
- Of 27 SustainmentNotice nodes in sandbox, three have zero components, and each still has its
  notice node and its parent edge. The notice MERGE runs before the parts UNWIND, so that is how
  the query is built, not luck.
- The RDF anchor is missing for one of the three. 7f owns that.

What that means for hand entry:
- **It is not a 208 blocker.**
- 7f warns that a zero-row notice's `n.id` can be a path fragment. That does not bite here:
  `apply_row_edits` finds the notice by `provenance_ingest_id`, not by id or notice number.
- Doc-tools stamps that key in its own query, gated on `provenance` and not on row count
  (`doc_tools/plugins/sustainment.py:2127-2138`). That is a code reading. I have asked 7f to read
  the key on the three nodes, because I cannot read the cluster during the freeze.
- 7f offers the doc-tools half of the drift seal: a job in their repo that checks out this
  overlay at a pinned ref. I have said yes in their packet. My job sees a doc-tools change only
  when this repo bumps its pin; theirs sees it on their own PR.

## Item 1: steward-entered shipped untagged, and ca asks one question

- ca has `steward-entered` as the seventh and last rung on `lane/ca-0.9.11` (e5cf070), not
  tagged. The tag is Monday, after 207 merges.
- ca's question: your ruling says a hand-entered row lands with `corrected_by` set. As shipped,
  the SDK's pairing rule still refuses `corrected_by` on every rung but steward-corrected. So a
  steward-entered block that names its steward raises.
- **This repo's `src/iagent/provenance.py` has the same rule** (`:118-128` and `:163-173`). The
  ruled shape would raise on our side too.
- My reading is that ca has to widen the SDK rule (ca's option (b)), and I have told ca so. I
  propose this rule:

  | rung | corrected_by | extracted_value |
  |---|---|---|
  | steward-corrected (unchanged) | required | required |
  | steward-entered | required | must be absent (nothing was extracted) |
  | every other rung (unchanged) | refused | refused |

  I asked ca to put it in the same tag. Otherwise 208 would pin a release that refuses the
  rung's ruled shape.
- **Yours to confirm:** that pairing rule, before ca tags Monday.
- I make the same change to the local validator in the hand-entry build, with the pin bump.

## What 208 waits on now

1. The SDK v0.9.11 tag (Monday), which should carry the pairing rule above.
2. 7f's read of `provenance_ingest_id` on the three zero-row nodes.

Then I build hand entry on 208:
- bump the pin;
- move `test_a_fifth_obtained_via_rung_lands` to the seven-tuple;
- widen the local pairing rule;
- turn the 409 `add_missed_part_not_built` into a parts entry: `promotion.act` with `added`
  edits at steward-entered, behind the promotion grant.

208 still rolls only with cortex's empty-confirm card and 7f's force-text reader.
