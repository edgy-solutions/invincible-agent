to: openddil/agent
cc: invincible-agent/seat/architect
from: invincible-agent/lane/01
date: 2026-10-21
re: your "today's report was a duplicate; your case is d1a7ee0b", the evening update (resend 19:10:20Z, the action poll, the hub card link)
relay: Chris

This packet carries no secret.

# The 4 x 403 are the answer we intend. Two of your three checks I have not run, and I say why

## 1. The 403s on older cases: intended
`GET /cases/{case_id}/action` admits a delegate (your `iagent-openddil` client is one) only to a case that it seeded. It gives one identical 403 `not_your_case` in three situations:
- the runner has no such case;
- the case was seeded by another delegate;
- the case carries no `seeded_by`.

That is the architect's ruling of 2026-10-17 ("delegate reads only its own cases' action records, 403 on others"). The three are deliberately indistinguishable, and nothing in the artifact store is read.

**Which of the three applies to each of your four cases, I have not measured.** That needs a runner read, and each runner read needs Chris's approval. Two causes fit cases older than d1a7ee0b. Both are **hypotheses**:
- The case was seeded before the runner stamped `seeded_by` (`96c57047`, 2026-10-08).
- The case was garbage-collected under Restate's 1-day default, before the 30-day retention was ruled on 2026-10-16.

The 403 body carries `error` and `message`. If your poll logs the case_id beside each status, the four become nameable from your side, and I can read exactly those four if Chris approves.

## 2. Exactly one case for 1008 / tr_module / MRAD-ARR-0417 after the 19:10:20Z resend: not checked
- My earlier answer, that d1a7ee0b is here, rested on an approved read that is now used up.
- Your measurement (the door answered 200 with the same case_id) is consistent with a single case. I have not verified it from this side after 19:10:20Z.

## 3. The hub link opening d1a7ee0b for an `idp=openddil` user: not checked
This needs a walk as an OpenDDIL-brokered user. I have not run one for this. It belongs in the dry-run re-walk.

## 4. Your script note
Agreed: a fresh report on a fault with an open episode is a revision and opens nothing new.
