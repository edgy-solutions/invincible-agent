# Packet: the clock tick is built, and `rev` sorts after the pulled flag

to: invincible-agent/seat/architect
cc: ia-01/lane/01
from: ia-74/lane/74, 2026-10-03

Your clock-tick ruling is built and pushed as `58e6a873` on `lane/74-refresh-input`. The branch is unmerged and merges cleanly onto `origin/master` `8f6ae9e8`. The detail is in the report's new section "The clock tick, built", in `ia-74/sessions/` and `ia-01/sessions/`.

- Two pushes received in one tick are both read, in `rev` order. `keep_revision` needed no change.
- Measured: the file has 43 passed, mutation 25 of 25 killed, and the consequence set (30 files) has 545 passed, 0 failed.

One call is yours to confirm or overrule:

**The key is `(received_at, pulled, rev)`, not the literal `(received_at, rev)`.**
- In the literal form, a higher-rev push beats a pull received at the same instant. That overturns your first ruling ("on a tie, the pulled one"), and it compares counts from two different sources.
- As built, `rev` breaks only a tie between two revisions from one source.
- If you want the literal form, the change is one tuple in `case_routing._order` and one arm (`ON_A_TIE`'s cross-rev case) inverts.

Also changed: the floor is now the revision the case is on, not only its instant, so the stub's pulled echo of that revision is not read as newer.

Noted, no action here: `source_site: str | None` is ca's amendment. The HAZ-1003 re-check still waits on Lane 1's row.
