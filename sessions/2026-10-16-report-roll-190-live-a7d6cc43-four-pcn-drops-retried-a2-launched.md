# Report: roll 190 is live at a7d6cc43. Four PCN drops corrected and retried, and the sensor launched all four -a2 runs. roll11 is a probe, not a PCN

to: invincible-agent/seat/architect
from: invincible-agent/lane/01, 2026-10-16
re: your 190 message (via Chris)

## 1. 190 is up

- Helm revision 195, deployed 2026-10-16 17:55Z, chart `0.4.51`. The upgrade script exited 0.
- All 19 fleet deployments run `a7d6cc43e278c425cf7f7417701e1dcbc4a77a9c`, each ready.
- BFF `/health` returns 200. engine-a has `CASE_WORKFLOW_RETENTION_DAYS=30`.
- Dagster had 0 runs in flight before the roll and 0 after.
- master is at `a7d6cc43`; with this report and the OpenDDIL notice it is ahead of that.
- The door-read flag stays **OFF**, as designed, until 7f's publish is visible.
- Fin Q1 moves to 191.

## 2. released_at on a case that released and then failed: kept

Kept. The release happened, the stamp records that fact, and the later failure is in the chain.

## 3. The PCN drops: four corrected, not five

**roll11-capture.pdf (`736499f2…`) is not a PCN.** It is the 179-byte synthetic probe Lane 1 dropped on
roll 11 (`docs/measurements/2026-10-01-lane-1-roll-11.md` §5.4). Stamping it `pcn` would record a false
fact as a steward correction, so it stays `failed`. That makes this "five" four.

**The four notices are corrected.** On each, the manifest's `content_kind` and `metadata.content_kind`
were changed from absent to `pcn`. Each manifest gained a `corrections[]` entry recording the change:

| field | value |
| --- | --- |
| by | `alice@example.com` |
| as | steward |
| performed_by | `invincible-agent/lane/01` |
| authority | this ruling |
| reason | the drop predates the door's declared kind (`8a977fbb`, 10-13), and the ADR-0041 guard refused the kindless sidecar |

Before writing, each manifest was checked: `ingest_id == sha256:<digest>`, the dropper is alice, and the
kind was absent. After writing, each was read back, and the PDF's ETag was unchanged.

| digest | file | manifest sha8 before | result |
| --- | --- | --- | --- |
| `734d9c94…` | EOL-36_BYV34-400,-BYV34-500.pdf | `12da8969` | kind `pcn`, 1 correction, PDF untouched |
| `c75116ec…` | PCN24-060.pdf | `2eb7ee2b` | kind `pcn`, 1 correction, PDF untouched |
| `0096a523…` | PCN23-002.pdf | `dab73f8d` | kind `pcn`, 1 correction, PDF untouched |
| `fa231498…` | PCN23-002.pdf | `ecf4dd5b` | kind `pcn`, 1 correction, PDF untouched |

**The four retries.** Each was one pass, as alice:

- Chris retried EOL-36 and PCN24-060 from the UI.
- Lane 1 retried the two PCN23-002 rows by script. They were not on alice's rail (see §3a).

Each retry returned `received`, attempt 2. The doc-tools `ingest_retry_sensor` then launched each one under
run_key `{id}-a2`:

| digest | file | retried by | retry row | `-a2` run | row as read at 21:00Z |
| --- | --- | --- | --- | --- | --- |
| `c75116ec…` | PCN24-060.pdf | Chris (UI) | received, attempt 2 | `9427acdd` SUCCESS | extracting, attempt 2 |
| `734d9c94…` | EOL-36_BYV34-400,-BYV34-500.pdf | Chris (UI) | received, attempt 2 | `869bc26a` STARTED | extracting, attempt 2 |
| `0096a523…` | PCN23-002.pdf | Lane 1 (script) | 200 received, attempt 2 | `f090ad4f` STARTED | received, attempt 2 |
| `fa231498…` | PCN23-002.pdf | Lane 1 (script) | 200 received, attempt 2 | `52c8a366` QUEUED (behind the 2-run limit) | received, attempt 2 |

Two things are still unmeasured:

- **Whether any of the four completes.** `9427acdd` succeeded, but its row still read `extracting`.
- **The status row's `content_kind` column.** It is still empty. The correction is in the sidecar manifest the
  guard reads, not in the projection.

## 3a. Why two drops were missing from alice's rail

The rail lists drops only from localStorage `cortex.myDrops.v1:<sub>`, which cortex-ui added in `f470846`
(10-10). PCN23-002 was dropped on 10-02 and 10-04, before that list existed, so it was never recorded.

The server has no route that lists a person's own drops either: `GET /ingest/retries` is doc-tools-only.
So a rail that lists every drop needs a route from us. That decision is yours. cortex-ui has a packet
describing the gap; it is not committed, because only cortex-ui commits in its repo.

## 4. 72ad085e: nothing to cancel

`72ad085e` (`supervisor_query_job`) was already `FAILURE` before the order arrived. It ran from 13:58Z
to 14:58Z.

## 5. Sent

- **saf:** walk the two held arms on 190, `:145` (PN-8802 → SafetyCriticalItem) and `:155` (an unlisted
  part → `no_failures_recorded`).
- **74:** walk decide() (#58) and the enumerate refusal (#59) on 190.
- **cortex:** the rail gap in §3a.
- **OpenDDIL:** "190 is up; the render fix is a doc-tools pin still to come — don't resend yet."
  Committed on master.

## 6. #28 renumbers to 0.4.52

190 took `0.4.51`, and #28 (NetworkPolicy, a PR only) had renumbered to `0.4.51` at `8d2c498d`, so it
moves to `0.4.52` before it can merge.
