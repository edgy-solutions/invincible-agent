to: invincible-agent/lane/01
from: invincible-agent/lane/01
date: 2026-10-26 (about 04:45Z)
re: in-flight state after rev 217 by hand. 208 is five PRs and a merge order.

# Handoff: 208 is five PRs and a merge order

## Next step

Merge the 208 set in this order:

| step | PR | branch |
| --- | --- | --- |
| 1 | #106 | trailer registry |
| 2 | #105 | the 202 flip, re-trailered |
| 3 | #104 | register 422 |
| 4 | #109 | 409 checker reads AnnAssign |
| 5 | fin #102 and #103 | |

- **Merge rules:**
  - Use `gh pr merge --merge --match-head-commit`. Never squash.
  - Read the second parent after each merge.
  - These PRs need the architect's ruling or Chris's OK; "208 merges" covers #102/#103/#104 and
    the flip. #106 and #109 are new since that ruling.
- **Why #106 comes before #105:** #105's first commit, `a58c7780`, carries `ia197/...`. Master's
  current seal arm passes it only while that worktree exists.
- **After the merges:** cut 208 and roll cortex-bff and presentation-agent under the lock, from
  a roll worktree **under the scratchpad**, never `C:\tmp`. All the standing roll gates apply.

## Open, waiting on others

- **#108** (rev 217 report): asks whether to run four hooks (topaz-manifest-load, task-grant-sync,
  restate-init, ontology-seed) by hand, or let Monday's roll run them. realm-reconcile's failure
  on 217 is the open root cause.
- **#101** (ask the manual): the architect answers the nine asks when Chris pastes them.
- **a1 (normaliser):** the architect named `doc_tools/utils/parts_text_list.py` (#148), which has
  no normaliser in it. This was asked in the saf 208 packet, cc architect. Do not build a1
  until the function is named.
- **a4 (critical delete):** three proposals to saf, cc architect: saf seeds `safety_critical`
  and deletes the lists; pending state goes on the ledger; after expiry, an act is a new first
  approval. Order: seed, then gate, then delete the lists.

## Owed by this lane, not started

- wb's audience mapper on `training-workbench` (wb 10-25 packet). It touches three template
  sites: the realm import at `keycloak-configmap.yaml:154`, the reconcile at
  `realm-reconcile-job.yaml:445` and the readback at `:822`. realm-reconcile is the hook that
  failed on 217, so ask whether it rides 208 or waits.
- ca's ADR-0060 note: `11be1ec4` folded ca's review verdicts into the draft's own prose, against
  the directive that findings be comments. Decide between walking §5 back to open questions
  (a new commit on `lane/01-adr-0060`) and standing behind it.
- cortex's `document` review shape (cortex PR #33). Ratify or rename the field names, name the
  task kind, and say what `flagged` does; this needs 7f and the architect.
- Two builds: a3 (promotion writes go through the SDK writer) and a2 (`NOTICE_PARTS_CYPHER`'s
  anonymous `SUBJECT_TO`).
- The cortex PRODUCER_REF packet, owed since #99 merged.
- ca has no row in `.githooks/lanes`; its shared-tree commits carry `invincible-agent/master`.
  This needs a ruling. AGENTS.md's roster has no rows for saf, gov or fin.

## Fixed dates

- **Monday:** Chris's brokered run on case `da479c74`, which stays read-only until then.
  OpenDDIL's Tuesday script is in `sessions/2026-10-24-packet-to-lane-01-the-tuesday-script-...`.
- **Monday 18:00 CT:** 320A is cut from `lane/74-planned-inspection-interval` at `d412c8b6`.

## Worktrees (all under the session scratchpad)

| worktree | branch | state |
| --- | --- | --- |
| wkc | `lane/01-409-checker-reads-annassign` | clean |
| w208 | `lane/01-trailer-names-the-lane` | clean |
| wadr | `lane/01-adr-0060` | |
| wask | `lane/01-ask-the-manual` | |

The roll worktree `C:\tmp\ia193` predates the rule. Retire it after 208's roll.
