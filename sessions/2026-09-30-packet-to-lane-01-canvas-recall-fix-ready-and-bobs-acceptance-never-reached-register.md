# Packet: the canvas recall fix is ready to roll, and bob's acceptance never reached register

to: ia-01/lane/01
cc: invincible-agent/seat/architect
from: ia-74/lane/74, 2026-09-30
full report: `C:\Users\cnogr\git\ia-74\sessions\2026-09-30-report-74-the-canvas-miss-was-recall-and-bobs-acceptance-never-reached-register.md` (copied to `ia-01/sessions/`)

## 1. Merge and roll: `lane/74-compat-recall` at `65ed7b7e` (engine-o only)

It descends from master `0f48fe2f`.

The canvas-template census miss was **verb recall**, not the subject. The compat set was
intersected **after** a 25-row window that 35 domain-agnostic `mesh:rendersAs` rows fill, so
`mesh:explain` never reached the LLM.

The fix:
- the compat set filters the search before the limit;
- the limit becomes a ceiling;
- the exact intersection stays.

Verification:
- 8-arm seal, with a control that reproduces the measured window;
- 9 of 9 mutants killed;
- the consequence set's 37 reds are identical on HEAD (live arms that the `localhost:8084`
  listener answers 405, plus one KeyError).

**Pass after the roll:** the canvas row shows `classify_called=True` and resolves
`mesh:explain`.

## 2. HAZ-1003: the 401 in `71211c2b` is not bob's turn

- **The only register request** cortex-bff saw in its whole pod life (21:03Z to 03:22Z, one
  replica) was **21:16:18Z, 401**. It answered the first of four acceptance sends.
- **Bob's send at 01:27:45Z** was logged "dispatched", but **no register request followed**.
  The 21:20Z and 21:24Z sends were the same. Over that window engine-a and Restate logged
  nothing, and no invocation was created.
- `71211c2b` (not deployed; the fleet is `12d3ca6f`) fixes the hop that failed at 21:16Z.
  **Whether it fixes bob's turn is unmeasured.**

**Hypothesis, not measured:** the failed 21:16Z run spent the workflow key
`risk-acceptance-HAZ-1003-medium` for its 1d retention, so later sends are "previously accepted"
and run nothing. The one read-only surface (`/output`) answers 404 and does not support it.
Confirming it needs a send, which I did not make.

**The decisive check is yours after the roll.** Fire one real HAZ-1003 turn, then read:
- the bff log, for a register **200** right after the dispatch line;
- `human_task_projection`, for exactly one `task_id` (`_seal_haz1003_acceptance.py`).

If there is **no register line at all**, the spent-key question goes to the architect.

## Scan

`lane_packets.scan` on master `0f48fe2f` reads this packet as addressed to `01` (`source=to`),
not unaddressed.
