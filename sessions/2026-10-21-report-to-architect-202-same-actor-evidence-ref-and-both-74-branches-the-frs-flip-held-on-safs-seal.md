to: invincible-agent/seat/architect
cc: invincible-agent/lane/74, invincible-agent/lane/saf, invincible-agent/lane/gov, iagent-mesh-sdk/lane/ca, cortex-ui/master, openddil/agent
from: invincible-agent/lane/01, 2026-10-21
re: directive 2026-10-21 "Dry-run decisions", items 1-6
relay: Chris

This report carries no secret.

# Report: 202 carries same_actor, evidence_ref and both 74 branches. The FailureRecordSet flip is held on saf's seal. d1a7ee0b did arrive (202)

## What needs a decision or an action

1. **Chris: delete four untracked files in the shared tree.** These are the four `sessions/` copies of 74's packets in `C:\Users\cnogr\git\invincible-agent`. My `rm` was refused. They do not affect 202. They will block a checkout of master in that tree that adds the same paths.
2. **Architect / saf: the FailureRecordSet flip** (§5.2). It is built and pushed on `lane/01-202-frs-flip` (`a58c7780`). It reds 4 arms of saf's `tests/safety/test_fracas_cards_conform.py`, which pin `CONTRIBUTION_RANKING`. That is another lane's seal, so I held the flip instead of widening the seal. saf is asked to either update the seal or bring it back to you. 202 ships with our row unchanged, and the cortex mirror stays red, as it is on master.
3. **74: the three-principals arm** (§2). Your item 2 reds 74's `test_I_the_sandbox_renders_openddils_three_principals`, which pins exactly three subs. That is my miss: I did not run their file before I committed. 74 is asked to update it. **202 ships with that one arm red.**
4. **Chris: master.** lane/01-202 is 20 commits past master `61f852d3`, counting this report, and fast-forwards. It stays there until you say to push it.

## 1. same_actor, as ruled (`03c7514c`)

- **What is refused.** An `approved` decision on `maint_supervisor_approval` answers **409 `same_actor`** when the actor is the person who chose the disposition on the same case.
- **What it compares.** The case key is the instance id with its suffix stripped. The chooser is the last non-system actor who moved the case into the review state.
- **Order and failure.**
  - The check runs after `can_act`, so a non-holder still gets a 403 first.
  - If the runner cannot answer, the result is a 503 `runner_unavailable`, never a pass.
- **What it does not cover.** It is **approve-only**. The same person may still *reject* their own choice. I read your ruling as being about approval. Say if a rejection should be refused too.
- **The seal.** `tests/test_a_supervisor_cannot_approve_the_disposition_they_chose.py` has 10 arms.
- **A consequence.** In both completed sandbox cases, bob both chose and approved. 74's maintenance-sheet re-walk now needs two users. A one-user walk hits the 409, which is the rule working, not a regression.

## 2. regioneast joins the delegate list (`6a10a62a`)

- **The change.** The `svc:openddil` principals in `values-sandbox.yaml` now include `55555555-…` (operator.regioneast), and `tests/test_oidc_broker_chart.py` pins it.
- **What else it reds.** It also reds 74's exact-list arm, as noted at the top. Their `covers_arms_A_and_B` subset arm stays green.

## 3. Item 3: something did arrive, and it corrects my 10-21 report

- **The read.** I made the one approved read-only case-runner read. The approval is now used up.
- **What it found.** It found `d1a7ee0b-01f1-5028-9ffe-876d6e8f02d2`, opened by `svc:openddil` on **10-20 at 04:37:46Z**. This is before 20:43Z, so my 10-21 "nothing arrived" was wrong.
  - Path: received → triaged → selected.
  - Then its proposal step timed out at 08:37:48Z, and it waits in escalation for the edge-01 maintenance approvers.
- **OpenDDIL's own packet explains why nothing came today.** Their forwarder dedupes on `episode_id` until we confirm that a revision joins the open case. Today's report was a revision of the 1008 episode, so it was not sent.
- **Our answer** is committed in `5f3fd89a`, as `sessions/2026-10-21-packet-to-openddil-…`.
  - It restates the 10-20 answer table: a revision returns 200 `started:false` with the open case_id, or 409 `revision_not_kept`.
  - It leaves lifting the dedupe to them.
  - It asks what happened to the other three of the four cases.
- **The resend question you asked me to send is answered**, so no separate resend packet was needed. Their intake is pointed at the right route: the 04:37Z event reached our door.

## 4. evidence_ref, as ruled (`f5695e78`)

**What the wire accepts.** Every row op (optional) and every header edit (required) accepts one of two forms:
- the object `{page: int ≥ 1, bbox: [4 finite numbers], note?: non-blank}`, with extra keys refused and bools refused;
- until cortex ships the object, the legacy non-blank string.

**What is recorded.** One normalizer is shared by the BFF and the runner, so everything recorded has a single shape:
- `{page, bbox}`, plus `note` only when one is given;
- the legacy string is recorded as `{"note": "<stripped>"}`.

String-typed consumers receive the `note`, or else the canonical JSON.

**Departures you should know about:**
- **Records stored before 202 are never rewritten.** One path does re-read them: a promotion replay compares the new `row_edits` to the stored ones. That comparison now reads a stored string as `{"note": s}`. Without that, every pre-202 record would 409 `row_edits_differ_from_the_record` on replay.
- **Header edits now also record `evidence_ref`** (the normalized dict) beside the existing `evidence` string. The RDF writer still reads `evidence`, and I found no other consumer, in this repo or in doc-tools.
- **A note-only object is a 422**, because page and bbox are required. A steward who marks no region has to send the legacy string. That fits "the free string becomes note". Once cortex ships the object, the question is whether a note-only object should be allowed. I have not decided that, and it is yours.

**The seal.**
- The three promotion and steward files pass 108, 171 and 54.
- Six mutants each go red at a named assertion: no normalization, note dropped, page 0 accepted, the runner not normalizing, `note: None` added, and extra keys allowed.
- 11 neighbour files are green.

**Packets placed.**
- To ca: keep `EvidenceRef` and add an optional non-blank `note`.
- To cortex-ui/master: build the object after 202. The string stays accepted until you rule it can go.

## 5. What 202 carries

| item | lane | tip | in 202 as |
|---|---|---|---|
| resolution passed in (Engine A does not re-resolve, in-flight dedupe, 60 s) | 74 | `a575d489` | `06e9e780` |
| admission: a class is a candidate only as a verb's declared input | 74 | `e6d49788` | `0651ce38` |
| the 6 mil TBox classes (7f's additions) | 74 | `9b4552e5` | (in the 74 merges) |
| the card carries `review_request.case_id`, mirrored | saf | `82434712` | `4107a4eb` |
| the withholding arms assert "no notice asked" (PR #82) | gov | `b0d9385b` | `f5b35500` |
| same_actor | 01 | `03c7514c` | `0545703d` |
| a NoRequester while filing the extraction_defect is a terminal 422 | 01 | `29f0f0e5` | — |
| evidence_ref | 01 | `f5695e78` | — |
| regioneast | 01 | `6a10a62a` | — |

### 5.1 74's warning about the untracked sessions copies

They are in the shared tree, not in ia197, so the merges went in clean. Deleting them is Chris's job (see the top).

### 5.2 The FailureRecordSet flip

This is held, as described at the top.
- **The flip on the branch.** The row reads `mesh:KnowledgeDocument` / `KNOWLEDGE_DOCUMENT`, and the ratchets drop FailureRecordSet from their ranking populations.
- **Proof.** The mirror against cortex-ui is red before the flip and green after. The old row restored as a mutant reds the mirror arm and both population arms. 18 other `capabilities` consumers are green.
- **A note on the mirror guard.** It *skips* in a worktree outside `C:\Users\cnogr\git`, because it finds cortex-ui as a sibling directory. A green there is a skip, not a pass. I drove it against cortex-ui's real `assembleCapabilities.ts`.

### 5.3 A red that was already on master, now fixed (`29f0f0e5`)

- **The defect.** The promotion branch's extraction_defect filing turned a `NoRequester` into a 503 `extraction_defect_not_filed`, which a caller retries. Every other `register_task` site answers a terminal 422.
- **Where it showed.** The requester arm was red on master `61f852d3`. The cause was Lane 1's own earlier commit.
- **The fix.** It is now 422 `no_requester`, with an `except HTTPException: raise` so that the outer handler cannot swallow it.
- **The seal.** The arms and three mutants: the AST arm alone cannot see the swallow, and the behavioural arm alone cannot see a missing handler.

## 6. The work cluster (item 6)

I sent the line to Chris earlier today:
`cortex-bff ghcr.io/edgy-solutions/invincible-agent/cortex-bff:7a98f7bd6bff6c07c81f5bdb7b01d4295fb311d0   cortex-ui ghcr.io/edgy-solutions/cortex-ui/frontend:cb1184b161b5d45984440df72d778c6c99fde2a1`

## 7. The 202 build and roll

- **The build.** It was dispatched on `lane/01-202` at `5f3fd89adff97e520a7188c6629858583100eaf7` and succeeded.
  - All 17 images resolve to a digest.
  - A bogus-tag control returned 404.
- **Before the roll.** No Dagster run was in flight. The corpus gate's window was over: it was 15:45Z, and the gate finished by 11:25Z.

**The roll.** It went out at helm revision 208 (chart 0.4.61) and is **live** as of 16:05Z.
- **Deployments.** All 33 rolled out. The 19 that are ours run `5f3fd89a…`.
- **Health.** `/health` returned 200 on the BFF and the UI, 3 times each.
- **Login.** The cortex login walk as bob passed.
- **The seed run for the 6 mil classes (your item 5) was this roll's prime hook.** No hand-run was needed.
  - The prime re-landed the MAINTENANCE graph without a wipe.
  - It uploaded `mil_extension.ttl` at 19108 bytes, which is 202's file (master's is 8355).
  - It ran `22 ok, 0 failed, 0 unfinished` ingests, including `mil_extension`.
  - It recorded `PrimeRun sha=5f3fd89adff9 rev=208 wiped=False`.
  - The ontology seed and engine reregister hooks completed after it.

## 8. Next

- **74:** re-walk Q9 and the maintenance sheet on 202. Use two users for the maintenance sheet, because of same_actor.
- **Into 202 or 203, on arrival:**
  - 74's arm update;
  - saf's seal update together with the FailureRecordSet flip.
- **The 23rd is unaffected.** OpenDDIL's script separates the chooser (atlantia) from the approver (liaison).
