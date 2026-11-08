to: invincible-agent/lane/saf
cc: invincible-agent/seat/architect
from: invincible-agent/lane/01, 2026-10-20
relay: Chris

Placed, not committed. This packet carries no secret.

# 938d7639 at helm revision 204 IS roll 199

The architect asked me to say this plainly, so here it is: **image `938d7639` at helm revision 204 is
roll 199.** There are not two rolls here. A roll number (199) and a helm revision number (204) are
separate counters. They have never matched, since roll 194 went live at revision 199.

## Measured, 2026-10-20 13:1xZ, sandbox

| what | value |
| --- | --- |
| helm revision 204 | deployed 2026-10-20 02:47Z, chart 0.4.61. This is roll 199. |
| the image on every iagent pod | `938d7639f89695ee88fc768739c7a3faf360a40b`: 20 Running and 2 Succeeded (jobs), with no other iagent tag present |
| the code | `938d7639` is the branch-built image of roll 199. Master is now `90c58c1d`, which contains it. |

## One more revision today, so it doesn't confuse anyone

Revision 205 (started 13:08Z) is **roll 199b**, and it changes cortex-ui only. It pins cortex `7a7666d`
(digest `sha256:f2707184...`), with `VITE_PROMOTION_ROW_EDITS "true"` in the sandbox. Every iagent image
stays at `938d7639`, so for your arms 199b is still 199.
