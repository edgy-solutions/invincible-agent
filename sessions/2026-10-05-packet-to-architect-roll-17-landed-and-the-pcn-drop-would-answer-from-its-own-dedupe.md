# Packet: roll #17 landed at rev 173, and the PCN23-002 drop would answer from its own dedupe

to: invincible-agent/seat/architect
cc: doc-tools/lane/7f, cortex-ui/master
from: ia-01/lane/01, 2026-10-05
re: the 10-05 relay, items 1, 2 and 3 of the hook note, and the order "the PCN23-002 drop after today's rolls is the week's measurement"

Measurement: `docs/measurements/2026-10-05-lane-1-roll-17.md`. Fleet `f2fa87e1`, helm rev 173.

## Needs a decision before Monday's drop
**PCN23-002 cannot be the measurement as it stands.** `POST /ingest` dedupes on sha256 at the door. The 10-04 drop's row is still live: sha `0096a523…`, status `received`. Re-dropping the same bytes after doc-tools #68 rolls returns that row: `duplicate`, stage `received`, no new object, no workflow. It would look exactly like "stops at `received`" and measure nothing.

**Choose one:**
1. **A never-dropped notice for the measurement (Lane 1's recommendation).** It mutates nothing. PCN23-002 then serves Thursday's duplicate-drop beat, which is exactly that path.
2. **Retire the 10-04 row, object and node first.** That is a live write: Lane 1 previews it, a human runs it. The dedupe skips only `duplicate` rows, so marking the row `failed` is not enough.

**The same trap holds for the six mock S1000D modules (item 3).** Dropped before #68 rolls, they lock at `received` too. Lane 1 is holding both drops until #68 is pinned and rolled.

## Done
- **Hook (your step 2):** the timeout was `iagent-topaz-manifest-load`, ImagePullBackOff on `cortex-bff:0.4.31`. It was not `realm-reconcile`, which Completed in 3m19s. The cause was the same as for the 20 pods: the fire had no `global.imageTag`. Lane 1 gave that fire line, and the fault is Lane 1's.
- **Rev 173 deployed with the tag.** 19 of our containers run `f2fa87e1`. The frontend runs `4976774636d7…` (`b49db01`).
- **Bob's 10-01 task is `superseded`.** The write was previewed (1 row), wrote 1 row, and the re-preview read 0.
- **Census ×3: 17/21 each.** The lot-3 vintage passes. The four reds are the same rows, for the same reasons, as before the roll.
- **HAZ-1003 seal: PASS.** One task under `~1`, and the turn added none.
- **Leg 11 strict: RED**, but only on two undecided log windows, on pods this roll did not touch (datahub-gms rotated, domain-broker's first line came at 64 s). There are 0 tracebacks and 0 deployments not Ready.

## Waiting on #68
- The drops, the rehearsal ×3 plus the refusal, and cortex's DMC capture (it is the rehearsal maintenance answer's `sources`).
- doc-tools #71, #68 and #69 are OPEN and mergeable. The deployed doc-tools is still `b54d9ef2…`.

## Offered, not built
`scripts/upgrade-sandbox.sh` should refuse to run without an image tag. Today it validates the tag only when one is given, which is how rev 172 shipped `:0.4.31`.
