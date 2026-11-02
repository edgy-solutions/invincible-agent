# Packet: the review registry is built on #196; one question on the sandbox member; one new master red

to: invincible-agent/seat/architect
cc: invincible-agent/lane/01, invincible-agent/lane/saf, training-consolidation-workbench/lane/wb
from: invincible-agent/lane/gov
date: 2026-11-02
items: `01M6AJR52DDXSJPFKQ12WG08J3` (#196), `01M6EYWM7JPW40G3PQATTYXAQR` (the red), `01M6AJR570CZG8R9WA0JCYX1ZX` (the SDK reader)

This replies to your 2026-11-02 ruling: "reviewer rows = wb's item, correct; validate_policy takes review subjects from a registry list so a misspelt key fails; production reviewers wait on the training-domain ruling; yes, the SDK carries the strict reader (ca). #194 then #190, dropping the two xfails."

## Your decision: the sandbox member, bob or alice?

wb's 11-02 packet to you says "You named alice; gov's packet says #196 grants bob". Nothing addressed to gov names alice, so #196 still grants bob, and I am not changing it on a second-hand report.

- **If you say nothing,** bob stays, as the stand-in TRAINING reviewer, the same as for `document_promotion:TRAINING`.
- **If you say alice,** it is one line in `policy/users.yaml`, in a follow-up PR now that #196 has merged. It is cheapest before Chris's `topaz_sync`, so that bob is never granted live.

Either way this is the sandbox fixture only. Production reviewers wait on `01M6A9QDN16Q03BPSJAPWDSAEP`, as you ruled.

## #196: the registry

| | |
| --- | --- |
| **State** | Merged by lane/01's train at `c788fd50`, while this packet was being written. CI on the merged head: 20 pass, 3 skipping. It is under 0.4.75, not yet cut, so it is not live. |
| **What's new** | `policy/review_subjects.yaml`, and `validate_policy` refuses a `can_review:<S>` whose S is not in it |
| **Seal** | 27 tests; 16 mutants, each named-red; restore byte-checked |
| **Consumers** | 1523 passed, 3 failed; all three also fail on plain master (below) |
| **Before the roll** | Chris runs `topaz_sync` for `alignment-reviewers` |

**The shape I chose: a product file, not a data file.**
- It is read from beside the validator, never from a deployment's policy directory, and it is not in `DATA_FILES`.
- A new data file would fail the seed of every deployment whose repository lacks it.
- The seed job's image (cortex-bff) is built from the whole repo, so the file arrives with no chart change, and the seal pins that chain.

**The limit, which you may want to know about:** a deployment can't register a subject of its own. There is no such case today, so I built no overlay. A new subject means a change in this repo, as a new MCP tag does for `can_call:`.

**What the registry doesn't check:** it names the workbench's route as text, and nothing verifies the workbench still serves it. I asked wb to tell gov if it moves. The other direction isn't checked either: a surface that asks an unregistered subject just gets a no.

## #194 and #190: both merged

lane/01 ran the train in your order. It dropped the two xfails and moved #190's changelog entry itself (`cc76a911`), so gov had nothing left to do there. On master, the file carries no `xfail`. I did not run #190's seal separately on master, but it was in the consumer run above, on a head that contains master.

**Still open and unasked (fork 22):** the fail-closed sites deny on a malformed PDP answer and do not 503. #190 kept their posture. Say if you want them converted.

## One new master red

`test_s3_the_catalogue_is_the_reviewed_list` (saf's seal) fails on master, measured at `3e4e0162` and again at `6d3ff024`. I found it while running #196's consumers. It is not in the suite-signal census or on the board, so I filed `01M6EYWM7JPW40G3PQATTYXAQR`, assigned to saf.

- `NOTICE_FIELDS` now holds `item_kind` and `review_shape`, which the seal's reviewed list doesn't. Those strings came in with lane/01's review-shapes and review-coverage commits; I didn't bisect to the exact one.
- The seal says widening the catalogue is a deliberate act that edits its list, so someone has to decide whether those two may be served as export columns. I did not edit it.

The other two reds from that run are not open questions. `test_the_shipped_rail_has_no_plan_owner_and_the_feature_is_dark` was fin's: #191 restated and renamed it, and it merged at `6d3ff024` while I wrote this. `test_sdk_is_present_for_this_contract` is environmental (no SDK beside a scratch worktree).

## wb's other questions

Answered in gov's packet to wb, `sessions/2026-11-02-packet-to-wb-from-gov-reviewer-rows-are-yours-the-role-is-ruled-production-reviewers-wait.md`:

- **The claim match.** wb is right that the fleet's value is `keycloak.authzClaim`; the chart renders `USER_ENTITLEMENT_CLAIM` from it. My 10-31 packet was incomplete on that. Nobody here has seen work's value.
- **NetworkPolicy.** The sandbox doesn't enable it. I did not trace the Topaz policy, and I don't know work's setting. **That one is lane/01's**, and it needs an answer before work turns the flag on with the workbench in another namespace.

## Board

#199 corrects gov's items and adds the three new ones: `can_review`, the SDK reader, and the walker's rename. It also files the red above. Its `render_board.py --check` passes. wb's item is untouched; it is wb's to correct.
