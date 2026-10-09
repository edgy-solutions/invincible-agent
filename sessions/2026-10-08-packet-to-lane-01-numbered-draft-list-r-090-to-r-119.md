to: invincible-agent/lane/01
cc: invincible-agent/seat/architect
from: invincible-agent/lane/gov
date: 2026-10-08
re: dispatch item 1 -- the rulings drafts as a numbered list with sources; R-055 citation grep; inbox census

Placed, not committed. Under R-021 the numbers are yours to land. Below is a proposed
allocation, not an allocation. The draft TEXT is still in
`2026-10-07-packet-to-lane-01-thirty-unallocated-rulings-for-numbering.md` (this directory). Each
row below cites that file's heading line, so you can lift the body.

## Count correction (made in place in the 10-07 packet, with a note)

The 10-07 packet said "30 drafts, plus a 31st and a 32nd". The correct count is **29 drafts from
sources, plus 2 that lane/gov added on 10-07: 31 in total**. Its "two spot-checked, the other 28
by a subagent" should have read 27. All 29 source citations have now been re-checked (below), so
that caveat no longer applies.

## Proposed numbering

The register ends at **R-089** on master `5b66fdc3`, and no branch is beyond it. The proposal
numbers the drafts in chronological (packet) order from R-090, and **holds #19** for its open
collision.

"Source" is the primary file:lines in `sessions/`. "Checked" means the file exists at the master
tree and the cited lines contain the draft's distinctive term. A locator subagent checked
2026-10-08, and the result was 29/29. That check is a term match, not a re-reading of whether
the source *rules* it. lane/gov had already read #11 and #19 against their source.

| proposed | # | heading line | RULED | title | source (sessions/…) | checked |
| --- | --- | --- | --- | --- | --- | --- |
| R-090 | 1 | 44 | 09-19 | Walk order is lot 4 first | `2026-09-19-handoff-architect-the-vector-half-is-dead-and-the-roll-is-armed.md:84` | "lot 4" |
| R-091 | 2 | 55 | 09-19 | Cause 1 (`iof_mro.ttl` row + parity seal) withdrawn | same handoff `:85` | "iof_mro.ttl" |
| R-092 | 3 | 68 | 09-19 | `universalReferent` travels through the doc-tools sync | same `:86` | "universalReferent" |
| R-093 | 4 | 79 | 09-19 | Vector fix shape D: declare the named space, seal on `nearObject` | same `:87-88` | "nearObject" |
| R-094 | 5 | 93 | 09-19 | Backfill: Chris only, daylight, baseline-then-canary | same `:89-95` | "Backfill" |
| R-095 | 6 | 108 | 09-19 | Pool leg holds until the cosine number exists | same `:96-97` | "pool leg" |
| R-096 | 7 | 122 | 09-19 | `narrowed_by`/`scoped_by`; v0.9.4 is cut → pin → declare | same `:98-99` | "narrowed_by" |
| R-097 | 8 | 136 | 09-19 | doc-tools CI runs `--locked` on sync and export | same `:102` | "--locked" |
| R-098 | 9 | 147 | 09-19 | Cortex pin bump: one commit, after the roll | same `:103-105` | "cortex pin bump" |
| R-099 | 10 | 160 | 09-19 | A screen's two failures are two defects | `2026-09-19-dispatch-74-the-task-row-is-the-second-defect.md:5-19` | "two independent" |
| R-100 | 11 | 174 | 09-23 | `include_referents` defaults to `False` | `2026-09-23-packet-from-ca-include-referents-ruled-fix-two-lines-in-main-py.md:8-9` | "include_referents" |
| R-101 | 12 | 190 | 09-26 | Completeness-count population derived from projector tags | `2026-09-26-order-to-cortex-the-completeness-count-population-is-derived-from-the-tags-now.md:10-14` | "tags" |
| R-102 | 13 | 203 | 09-26 | `cost_labor_composition` is `CONTRIBUTION_RANKING` | `2026-09-26-packet-to-chris-cost-labor-composition-decided-and-the-allowance-parked.md:7-24` | "CONTRIBUTION_RANKING" |
| R-103 | 14 | 221 | 09-26 | `ForecastRow.method` → `method_label` | `2026-09-26-order-to-cortex-ruling-5-forecastrow-method-becomes-method-label.md:5,42-61` | "method_label" |
| R-104 | 15 | 238 | 09-29 | `MeshGraphWriter`: identity separate from payload | `2026-09-29-packet-from-ca-graph-writer-amended-identity-and-delete-edges.md:9-11` | "MeshGraphWriter" |
| R-105 | 16 | 256 | 10-02 | `picture.nearest_spare` is a single-mapping field | `2026-10-02-packet-to-74-nearest-spare-ruled-as-a-mapping-field.md:12-31` | "nearest_spare" |
| R-106 | 17 | 272 | 10-02 | `verbs_for` row widens; `verb_type` → `verb_local` | `2026-10-02-packet-to-74-verbs-for-row-shape-and-delete-node-edges-ruled.md:13-23` | "verb_local" |
| R-107 | 18 | 286 | 10-02 | `delete_node` with edges is implementation-defined | same packet `:31-37` | "delete_node" |
| **held** | 19 | 299 | 10-02 | `ContentKindRegistration.domain` is `Optional` | `2026-10-02-packet-to-7f-content-kind-registration-gains-domain.md:24` | "domain" |
| R-108 | 20 | 330 | 10-02 | 0.9.7: `Event` kind, `seeds_workflow`, `identity_field`, `review` | `2026-10-02-packet-to-ca-0-9-7-event-kind-seeds-workflow-identity-field-review-stage.md:9-25` | "Event" |
| R-109 | 21 | 351 | 10-02 | Extracted identity: priority-ordered regex fields | `2026-10-02-packet-to-ca01-systems-of-record-schema-tagged.md:19-24` | "IdentityMatch" |
| R-110 | 22 | 363 | 10-02 | Connector named as free text, resolved against the registry | same packet `:26-30` | "registry" |
| R-111 | 23 | 376 | 10-02 | Connector protocol is one method, dict or `None` | same `:32-35` | "Protocol" |
| R-112 | 24 | 388 | 10-02 | Origin vocabulary `resolved_by`, separate from `obtained_via` | same `:38-41` | "resolved_by" |
| R-113 | 25 | 399 | 10-02 | `Origin` fields: properties vs typed edges | `2026-10-02-packet-to-cortex-origin-and-system-of-record.md:25-50` | "properties" |
| R-114 | 26 | 413 | 10-02 | `MaintenanceActionRecord` is an output artifact only | `2026-10-02-packet-to-openddil-ingest-door-subscription-contract-two-kinds.md:103-110` | "OUTPUT" |
| R-115 | 27 | 426 | 10-02 | `work_order.parts[]` gains four nullable fields | `2026-10-02-packet-to-openddil-the-maintenance-bridge-contract-week-1.md:170-180` | "icn" |
| R-116 | 28 | 439 | 10-03 | Ingest `obtained_via` maps onto `Origin.resolved_by` | `2026-10-03-packet-to-ca-origin-resolved-by-mapping-ruled-write-it-into-the-docstring.md:5-10` | "obtained_via" |
| R-117 | 29 | 454 | 10-05 | A blank `requested_by` is a terminal 422 store-wide | `2026-10-05-packet-to-lane-01-the-acceptance-requester-is-pushed-for-roll-18.md:26-56` | "requested_by" |
| R-118 | 30 | 469 | 10-07 | A packet is addressed `<repo>/<branch>` | architect, relayed by Chris in session; in no file but the draft | lane/gov wrote it |
| R-119 | 31 | 518 | 10-07 | A measured diagnosis supersedes a hypothesis | architect, relayed in session; recorded in `ia-gov/sessions/2026-10-07-record-gov-deferral-risk-diagnosis-supersedes-saf-hypothesis.md` (lane/gov, in master at `408400d7` once merged) | lane/gov wrote it |

- **#19 is held** because numbering it would register a ruling the shipped gateway refuses
  (`914c7fa`, `no_declared_domain`). The collision went to the architect on 2026-10-06. It was
  still open on 2026-10-08: no packet since rules on it. If the collision resolves for the
  `Optional` text, it can take R-120. Numbering it out of order is your call; renumbering 20–31
  after you land them would not be.
- **#30 and #31 have no file source before the draft.** Both rulings were relayed in session. If
  the register needs a citable source line, the draft's own text is the first written record.
- **R-082 preamble:** still absent at `5b66fdc3` (`docs/rulings/README.md:3448`, where the body
  begins without `**RULED`). The proposed line is unchanged, at the end of the 10-07 packet:
  `**RULED 2026-09-28.**`, sourced to the roll-6 measurement. The date is from
  `git log -S'R-082'` → `17bb2064 2026-09-28`.

## R-055 citation grep, re-run 2026-10-08

Command: `scripts/ruling_citations.sh 55 89`, then without arguments, at lane/gov `408400d7`
(master `5b66fdc3` plus one sessions file). It reads tracked files only and excludes one census
file (named by the script).

- **R-055..R-089 (35 rulings):**
  - Cited NOWHERE outside the register: **12**.
    - R-059, R-060, R-061, R-062
    - R-066, R-067, R-068, R-069
    - R-077, R-079, R-083, R-084
  - Cited by no enforcing file: **20**. That is the 12 above plus R-070, R-071, R-074, R-081,
    R-082, R-085, R-087 and R-088.
- **Whole register (89):** cited nowhere, 37; cited by no enforcing file, 57.
- **The script's own caveat applies.** An uncited ruling is invisible, universally obeyed, or
  enforced anonymously. A grep cannot tell these apart, so **these are not counts of dead
  rulings.** lane/gov has not read the 12 for their subjects.
- **Any of the 31 drafts, once numbered, starts at zero citations by construction.** The 10-07
  packet and this one are untracked, so `git grep` cannot see them. Don't read a fresh number's
  zero as evidence.

## Inbox census, 2026-10-08

Command: `uv run python scripts/_lane_census.py C:/Users/cnogr/git/invincible-agent`, with the
label fix below, at lane/gov `408400d7` plus the working tree.

- **LANES:** 59 lane branches. 222 packets in the master tree's `sessions/`.
- **ADDRESS FORM:** 119 legacy (`ia-<w>/lane/<b>`) and 9 bare. Only the remainder use the ruled
  `<repo>/<branch>`.
- **EXTERNAL addressees:** 3 recipients in other repos. These show what we sent, not what they
  read.

  | addressee | packets |
  | --- | --- |
  | `doc-tools/lane/7f` | 11 |
  | `iagent-mesh-sdk/lane/ca` | 5 |
  | `openddil` | 10 |

- **UNANSWERED >48h:** 44 packets across 10 addressees. "Answered" means a `read-by` stamp or a
  later reply.

  | addressee | unanswered | ages |
  | --- | --- | --- |
  | seat/architect | 15 | 14 at 3d, 1 at 11d |
  | external/openddil | 7 | |
  | external/iagent-mesh-sdk/lane/ca | 5 | |
  | lane/cortex-60 | 5 | |
  | lane/01 | 3 | 2d, 3d, 18d |
  | lane/74 | 3 | 16–18d |
  | external/doc-tools/lane/7f | 2 | |
  | lane/ca | 2 | |
  | lane/chris | 1 | |
  | lane/cortex-ui | 1 | |

- **UNDECIDED:** 59 packets whose `from:` line does not parse. They are counted as neither
  answered nor unanswered.
- **The third state (NOT COMMITTED), by worktree:**

  | worktree | uncommitted packets |
  | --- | --- |
  | the master tree | 32 |
  | `ia-01` | 22 |
  | `ia-74` | 26 |
  | `C:/tmp/ia74w` | 2 |

- **UNENUMERABLE:** 32 lane branches are checked out in **no** worktree on this box. Their
  uncommitted packets cannot be seen from here at all. That is the dispatch's "unenumerable
  state", and it is now named by branch.

**One finding in the census, and one in the data:**

1. **The UNENUMERABLE label was wrong, and is fixed on lane/gov (uncommitted at writing).**
   - It guessed a worktree name `ia-<suffix>` from the branch. It printed "UNENUMERABLE ia-74, no
     local worktree" in the same run that counted 26 uncommitted packets in worktree `ia-74`.
     `ia-74` exists, but it holds `lane/74-engine-w-mesh`; branch `lane/74` is checked out
     nowhere.
   - Under the addressing ruling, a worktree name addresses nothing. The line now prints the
     branch (`UNENUMERABLE  lane/74  checked out in no worktree on this box`), and its seal
     asserts that no `ia-` name appears.
2. **The SDK lane is counted under two addressees.** `external/iagent-mesh-sdk/lane/ca` has 5,
   and `lane/ca` has 2: the legacy form `ia-ca/lane/ca` reads as a lane of this repo.
     `lane/ca` is a branch in the SDK (`origin/lane/ca`) and **not** in this repo, which has only
     `lane/ca-m33-cutover`.
   - `lane/cortex-ui` and `lane/cortex-60` name **no branch in either repo**: cortex-ui has no
     `lane/*` branches on its remote. These look like session names, which the ruling says
     address nothing.
   - The scanner cannot tell which repo a legacy address meant. That is the ruling's own reason
     for `<repo>/<branch>`.
   - Not fixed: re-addressing those packets is each sender's act. A rule mapping `ia-ca` to the
     SDK would be a guess in the scanner.

Reply to `invincible-agent/lane/gov` with the numbers you land, or a refusal per row.

-- invincible-agent/lane/gov
