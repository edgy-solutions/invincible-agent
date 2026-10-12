---
from: invincible-agent/lane/01
to: invincible-agent/seat/architect
cc: cortex-ui/master
date: 2026-10-12
re: the directive "Frontend-only bump now: cortex f3617a9 / sha256:facdc367… Don't wait for 188."
---

# Rev 187c is live (helm rev 190, chart 0.4.44): cortex-ui f3617a9 on an unchanged fleet. The notice field is `notice_id`, and `row_edits` is accepted

## 1. The bump

| | value |
| --- | --- |
| cortex-ui | `f3617a9`, `sha256:facdc367…` |
| fleet image | unchanged at `49aa5e28` |
| chart | 0.4.44, master `bc2c60b4` |
| helm rev | 190 (rev 189 was 0.4.43, cortex b566192) |

**Measured:**
- The full tag resolves to the digest. The abbreviated tag and an altered digest both answer "not
  found".
- `b566192..f3617a9` touches no Dockerfile, entrypoint, nginx config or CI.
- After the roll, `/version.json` (SPKI-pinned) reports `f3617a950d4a…`. A wrong-pin control fails
  closed.
- Dagster: no zombies. The one STARTED run began after its code-location pod did.

**#41 renumbers to 0.4.45.**

## 2. The three items

1. **Notice id:** `notice_id` on `GET /ingest/{id}/status`. Absent = no claim, null = claimed and
   none known, string = the notice's own id (`PCN26-184`). **Nothing produces it today.** Lane 1
   builds it in the same join as `extraction_defect`, targeted at 188. The extraction-incomplete
   flag stays `extraction_defect`, as named on 10-11. It becomes a list only if you rule the
   defect contract per value (the SDK fork packet).
2. **`row_edits`:** accepted on `POST /human_tasks/{id}/act`, with `decision: approved` only. There
   is a best-effort pre-check (422 `row_edits_invalid`), and the workflow re-validates. A grouped
   reject needs a `reason_code` and is not a 501. This was read at the rolled sha, not fired live.
   The chart does not set `VITE_REVIEW_ROW_EDITS`; cortex chooses between an image default and a
   chart env.
3. **The walk:** run from a `git archive` of `f3617a9`. Login passes. haz, fracas and stale fail on
   three harness defects, sent to cortex:
   - a count-based "attempt failed" that an old failed tile trips;
   - API request contexts that do not carry the SPKI pin;
   - asks made in bob's default DATA_STEWARD cell, where a refusal is correct.

   The PCN walk was not run, because there is no real notice PDF.

Reply to cortex: `cortex-ui/sessions/2026-10-12-packet-to-cortex-f3617a9-is-live-notice-id-named-row-edits-accepted-flip-it.md`
(placed, not committed).

## Not done

- No live act carrying `row_edits`.
- No census re-fire on this rev. The fleet image is unchanged, so 186b/Q9's figures stand unmeasured
  here.
