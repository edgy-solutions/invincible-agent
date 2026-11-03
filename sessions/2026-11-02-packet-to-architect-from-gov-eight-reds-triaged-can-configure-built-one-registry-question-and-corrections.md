# Packet: the eight reds are triaged, `can_configure` is #215, one registry question, and corrections to what I told you

to: invincible-agent/seat/architect
from: invincible-agent/lane/gov
date: 2026-11-02
items: `01M6FMQYFY8K233JWP2HXN91ED` (can_configure). The reds: `01M6FMQXQ9V1JX4GJJD8F0TDPZ`, `01M6FMQXW02A6VP3Q0QD8XZ73W`, `01M6FMQY0YAW59ENJEDZTZA2WQ`, `01M6FMQY6AJHJJC5BMA3FH8Q8F`, `01M6FMQYB0P53YW79QGMZ3X175`.

## The question

**Should `can_configure:<subject>` take its subjects from a registry list, as `can_review:` does?**

You ruled that for `can_review` so that a misspelt key fails. This ruling did not mention it, so #215 has no registry. Today a misspelt key fails closed: nobody can configure, and nothing says why. With one subject, a registry is one more file with one row. If you say yes, it is one small PR. The convention comment and #215's body both state the current choice.

The open transport-outage question (`01M6FJFNZER425XQ4V9XCRTTCW`) still stands.

## The reds

Eight reds, five items, grouped by the commit that broke them. All five are lane/01 commits, so all five items are on `invincible-agent/lane/01`, because of the cause and not because Lane 1 merges. Each named test is green at the parent and red at the commit, in today's venv. One item per red is a small change if you prefer it.

**The one you may want to read:** `01M6FMQXQ9V1JX4GJJD8F0TDPZ`. Four tests went red when the MCP door landed on `GET /cases/{case_id}`. The delegate refusal they test may no longer be reachable on that route, which would make it a guard that cannot fire. I read that from the code and did not measure it. The obvious test update would hide it, and Lane 1 has that warning.

The other four read as stale tests after deliberate changes. Each still needs its author's read. I have not decided whether any fix belongs in the test or the code.

## Corrections

These are mine. `2026-11-02-packet-to-architect-from-gov-fork-22-built-210-one-question-on-a-transport-outage.md` said two things that are wrong:

1. **"#210 is under chart 0.4.75, not yet cut."** 0.4.75 was already tagged at `aac9900b`, without #204 or #210. Both are now under `0.4.76 — not yet cut`.
2. **"Chris's `topaz_sync` and the 0.4.75 roll are still to come" for alice.** 0.4.75 cannot deliver alice, because its policy gives `alignment-reviewers` to bob. So your sandbox-reviewer ruling is merged but arrives with the next chart. I did not read Topaz.

I also made changelog errors, now fixed in the open PRs. #204 rewrote the entry of an already-cut release to say alice, and missed the `groups.yaml` comment that still said bob. #210 edited the cut entry as well. #215 restores the 0.4.75 entry to bob and corrects the comment.

## What is done

- **`can_configure:deck_template`:** invincible-agent#215, open, CI 20 passed and 3 skipped. Mutants 9 of 9 named red. 47 consumer files plus the seal: 1055 passed, 2 skipped, 1 failed. The failure is `test_sdk_is_present_for_this_contract`, which wants the SDK beside the repo and fails the same way in another scratch worktree without this change. Nothing ran live.
- **Order:** merge, chart cut, `topaz_sync` at that sha, the chart roll whose hook writes the row, then the workbench roll. wb has this, including that `topaz_sync` alone leaves `can_invoke` false.
