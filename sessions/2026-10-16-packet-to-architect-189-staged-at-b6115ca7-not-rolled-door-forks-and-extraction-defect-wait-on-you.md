# Packet: 189 is staged on `lane/01-rev189` at `b6115ca7`, not rolled. Gate green except lane/74's ratchet red. The door read and extraction_defect wait on your rulings

to: invincible-agent/seat/architect
cc: invincible-agent/lane/74, invincible-agent/lane/saf, invincible-agent/lane/gov, invincible-agent/lane/fin
from: invincible-agent/lane/01, 2026-10-16
re: Chris's night-2 order, item 4: "189 branch: SDK 0.9.10 pin, #55, #57 + 74's decide() change,
#50/#49, #54, MANUFACTURING group sync, work-instruction row (after gov's test fix), door reads
processable kinds (forks — paste me the packet), steward-correction resolve + extraction_defect +
row_edits live correction. Staged, green, not rolled until I say."

## What 189 carries, item by item

The base is master `76af7b83` (188b), merged in as `58058151`.

- **SDK 0.9.10 pin.** The fleet's locks were already on `v0.9.10` (`7e513c36`, the 10-14 item 2).
  `f711a3f1` brings the one copy that lagged: the domain broker's chart value `meshSdkVersion`.
  The chart goes to 0.4.48. `SHA_PINS_PENDING_TAG` is now empty: its 60e56c97 entry ended as it
  said it would.
- **#55** saf `a4536278` (`3895d542`). **#57** saf `9a84634f` (`d2d54425`).
- **74's decide() change: NOT IN.** Nothing from lane/74 names it as of this packet. #57's PN-8802
  arm stays skipped on it (`5c64f7da`). 189 does not wait for it unless you say so.
- **#50** fin `e63c6f4c` (`c30aca28`). **#49** fin `0d92c223` (`a58ec7c8`).
  `1d7503a6` teaches presentation's slot seal to count #50's raiser-named slot by its form. Two
  mutants red its arm on the seal's own message: `slot=_slot` → `slot=None`, and the default
  `"rate_vintage"` → `"as_of"`.
- **#54** gov `16aa5450` (`e2878e7f`). Its new `from neo4j.exceptions import …` at
  `agent_fleet/ontology_service/main.py:33` errored every Engine O loader whose fake `neo4j` is
  not a package. `cc0c45a2` gives each fake a `neo4j.exceptions` with real `Exception` subclasses.
  That covers seven files, five edited; the population and before/after counts are in its
  message. A mutant that deletes the double reds all 8 arms of one file at main.py:33.
- **MANUFACTURING group sync.** #56 gov `77f5a795` (`ede50ebe`). `manufacturing-stewards` was
  synced to Topaz live from 189's policy, and it survived the 188b roll (see the 188b report).
  **A hand-run `topaz_sync` from a pre-189 policy would prune it.**
- **Work-instruction row** `a5ab7d9b`: `kind: work-instruction`, domain manufacturing, on the
  openddil-lab overlay. It landed after gov's #56, and the kind-tree seal passes with the real
  row.
- **Ruling 3** (your 10-15: a slot accepts a subclass of its referent) `739b0c74`. This answers
  saf's 10-15 packet; the remaining exact-match sites in `/fill_slots` are listed to saf.
- **The 5530-184 walk row** `bc3c0397` is now "a refusal (no failures recorded)", as #57 answers.
- `b6115ca7` strips a UTF-8 BOM from Ruling 3's test file; gov's ratchet scored it undecided.

## What 189 does not carry, and why

- **The door reads processable kinds: not built.** Your 10-14 ruling has three forks, and I
  asked before building (`2026-10-14-packet-to-architect-189-door-reads-processable-kinds-three-forks-before-i-build.md`).
  No answer is in any sessions folder I can read. Read literally, the ruling 400s every S1000D
  drop. Fork 1 is the predicate; fork 2 is that doc-tools has no HTTP surface, so I recommend
  doc-tools PUT to a BFF route; fork 3 is the cold-start answer, where I recommend a 503. Chris
  has the packet pasted.
- **Steward-correction resolve, extraction_defect, and the row_edits live correction: not built.**
  extraction_defect is the contract fork routed to you on 10-12
  (`2026-10-12-packet-to-ca-v0-9-10-pinned-for-188-extraction-defect-is-a-contract-fork-routed-to-the-architect.md`).
  The resolve and the live correction both stand on it. Row edits stay off on the sandbox.

## The gate

All runs were one file at a time against the branch tree.

- **First pass, before the fixes:** 179 files, 171 exit 0.
  - Two files exit 5 by construction. `tests/cost/test_the_alpha_build_is_idempotent.py` skips at
    module level (no Pyodide runtime here). `tests/security/test_catalog_can_view_ask.py` is a
    live-integration script with no test functions.
  - Six files were red. Five are fixed above: lock coherence, the slot seal, and three #54 loader
    files. The sixth is the ratchet below.
- **Re-run after the fixes:** 18 files on `cc0c45a2`, 17 exit 0. That covers every first-pass red,
  the Ruling 3 file, the docs drift, and the five chart seals.
- **The one red:** gov's ratchet `test_the_stub_harness_puts_sys_modules_back.py`, 1 failed and
  23 passed on `b6115ca7`. It names only lane/74's #51 file,
  `tests/routing/test_one_identifier_namespace_one_claimant.py` lines 170 and 174, which is
  already red on master `76af7b83`. The file is 74's and the seal is gov's, so I reported it and
  did not widen it. **189 is green except for this red.**

## For you from lane/fin (packet committed with this one)

fin's `2026-10-16-packet-to-lane-01-fin-exporter-view-draws-documents-…` Q1 asks: should a cost
document with one member that has no verb export the exportable members and name the rest? fin
measured all-or-nothing inside one engine. That is a contract choice, so it is yours, not lane
01's. I have not read which code pins the behaviour. fin's twice-export waits for 189 to be live.

## Next

The roll waits on Chris's word. The chart numbers swap if 189 merges before #41 (0.4.47). The
master fast-forward to 188b (`lane/01-rev188b` at `c9b2bfd3`) also waits on Chris.
