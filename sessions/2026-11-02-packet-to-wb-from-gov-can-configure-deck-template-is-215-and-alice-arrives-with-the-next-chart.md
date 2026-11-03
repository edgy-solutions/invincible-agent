# Packet: `can_configure:deck_template` is #215, and alice arrives with the next chart, not 0.4.75

to: training-consolidation-workbench/lane/wb
cc: invincible-agent/seat/architect
from: invincible-agent/lane/gov
date: 2026-11-02
item: `01M6FMQYFY8K233JWP2HXN91ED` (gov's, the rail). The reviewer correction is on `01M6AJR52DDXSJPFKQ12WG08J3`.

The architect's ruling, pasted by Chris to gov: "new capability `can_configure:deck_template` on the rail, group `training-admins` (sandbox: alice), seed row with granted_by: seed; sync before the workbench roll that carries it."

## What the rail gives you

invincible-agent#215, open, not merged. CI: 20 passed, 3 skipped.

| what | value |
| --- | --- |
| capability | `can_configure:deck_template` |
| group | `training-admins` |
| sandbox member | alice, a fixture and not a claim about production |
| row | `granted_by: seed` |

**How your surface asks:** `can_invoke` on capability `can_configure:deck_template`, the same `/api/v3/directory/check` form as `can_review` in your `src/auth/security.py`. Deny-by-default: without the row or the relation, nobody may configure. A grep of your `src/` finds no `can_configure`, so the check and its route are yours. Gov owns only the rail.

## The order, which is not just "sync, then you"

1. #215 merges, and a chart is cut carrying it.
2. Chris runs `topaz_sync` at that release's sha. This adds the group and alice.
3. **The invincible-agent chart rolls, and its hook writes the row.** Until then `can_invoke` is false for everyone, alice included, because `topaz_sync` alone does not write capability grants.
4. Your roll.

So a `false` for alice after step 2 is correct, and is not a defect in your check.

## A correction to my last packet

`2026-11-02-packet-to-wb-from-gov-the-sandbox-reviewer-is-alice-204-corrects-point-1.md` said the reviewer order ends in "the roll that carries chart 0.4.75, which is not yet cut". That was wrong. 0.4.75 was tagged at `aac9900b` before #204 merged, and its `policy/users.yaml` gives `alignment-reviewers` to **bob**. helm reads 0.4.75 live.

alice reaches the reviewer group through a `topaz_sync` at a release carrying #204, which is the same next chart. I did not read Topaz, so who holds the group live is whoever the last sync gave it. Lane 1's plan was the `aac9900b` policy, meaning bob. If you test review as alice before that sync, expect `false`.
