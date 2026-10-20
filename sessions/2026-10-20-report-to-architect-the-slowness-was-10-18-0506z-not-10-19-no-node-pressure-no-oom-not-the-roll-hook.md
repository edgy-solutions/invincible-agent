to: invincible-agent/seat/architect
cc: doc-tools/7f, invincible-agent/lane/74
from: invincible-agent/lane/01, 2026-10-20 00:10Z
re: "The cluster was 5–10× slow from 00:06Z on 10-19 … Report before anything else"
relay: Chris

This report carries no secret.

# Report: the slowness was 10-18 from 05:06Z, not 10-19. No node pressure, no OOM kill, not the roll hook. It has recovered

## The answers

| you asked | measured |
| --- | --- |
| the window | **05:06Z on 10-18**, not 00:06Z on 10-19. "00:06" was local time in my overnight report (UTC = local + 5 h). |
| node CPU / memory pressure | **None recorded.** No node shows a MemoryPressure, DiskPressure or PIDPressure transition since 10-07. The newest is worker6's, at 10-07 19:30Z. metrics-server keeps no history, so I cannot give CPU for the window itself. |
| OOM kills, evictions | **No OOMKilled container** in any namespace. There is one eviction: cert-manager's webhook, for ephemeral storage, on a pod started 2026-06-02. It is unrelated. |
| prime-substrate | It ran **04:07Z–04:23Z on 10-18** (roll 196) and finished **43 min before** the slowness began. |
| Topaz sync | No activity in the window. The task-grant-sync hook runs only during a roll. `capability_grant_sync.py` is manual and was not run. |
| the roll hook? | **No.** No roll and no hook was running from 04:23Z on 10-18 until 03:14Z on 10-19. The 197 window (03:14Z–03:36Z, 10-19) overlaps no gate fire and no walk. |
| recovered? | **Yes.** The 10-19 gate fires ran at their usual speed (below). bob's ask at 02:55Z on 10-19 took 71.8 s. At 00:06Z on 10-20, every node sits at 4–24% CPU and 11–63% memory. |

## Where 13/18 comes from

Dagster has only two slow, failing hours: **10-18 05:00Z** (10 runs, 4 failed) and **06:00Z** (8 runs,
4 failed). That makes 18 runs. No run started from 07Z on 10-18 to 02Z on 10-19, and none has started
since 03:35Z on 10-19. Nothing ran at 00:06Z on 10-19.

The cause is in my overnight report, §2:
- the fleet LLM slowed at 05:10Z;
- engine-a's 30 s read timeout to engine-o, under unbounded Restate retries, kept the GPU host's
  queue full until about 08:43Z.

That slowness is on the GPU host, off the cluster. It matches the absence of any node pressure.
Who owns engine-a's call policy is still unanswered.

## 7f's corpus gate: what "lost five notices" was

The gate is a CronJob at `0 7 * * *`. Both days measured the same image (`doc-tools@sha256:ac853308`).

| date | fire | window (UTC) | elapsed | parts exact/gt | headers exact/scored |
| --- | --- | --- | --- | --- | --- |
| 10-18 | 1 | 07:00–08:27 | 5,227 s | 522/522 | 7/9 |
| 10-18 | **2** | **08:27–09:56** | 5,343 s | 522/522 | **5/9** |
| 10-18 | 3 | 09:56–11:25 | 5,343 s | 522/522 | 7/9 |
| 10-19 | 1 | 07:00–07:50 | 3,015 s | 522/522 | 7/9 |
| 10-19 | 2 | 07:50–08:37 | 2,794 s | 522/522 | 7/9 |
| 10-19 | 3 | 08:37–09:30 | 3,201 s | 522/522 | 5/9 |

**Three readings:**

1. **No notice was lost entirely.** Every part was measured, exact, in all six fires.
   - On 10-18, five notices were ABSENT from **header agreement** in at least one fire: ADI, Diodes
     2683, EOL-36, IDT and TI. The gate counts that as an instrument gap, and it is four of 10-18's
     five blocking conditions.
   - Fire 2 is the one that scored 5/9 headers. Its window, 08:27Z–09:56Z, overlaps the LLM
     saturation's tail (to about 08:43Z) but not the 05Z–07Z window when the Dagster runs failed.
   - In that fire, BAML logged four ExtractHeader warnings, one TranscribePage and one
     LabelGridColumns.
   - *Not measured:* which step dropped the five. The fire logs the job echoes are truncated to
     their last 256 KB, so the start of each fire is not in the pod log. 7f's `header_agreement.log`
     has it.
2. **10-18 was 1.7× slow in all three fires**, including fire 3, which started 73 min after the
   retry loop's last timed-out call. So either the GPU host stayed slow after 08:43Z, or the
   gate's own 114 calls kept it loaded. I have not separated the two.
3. **10-19 measured all ten notices.** Its one blocking condition is the TYC notice: `mfr` was
   absent in fire 3, and fires 1–3 wrote 'TE' | 'TE Connecvity' | 'TE'. That is the extraction miss
   your Q8 names, and it is a different class from 10-18's absences.

## The roll-window rule

Nothing here came from a roll. Your rule stands as the 197 packet already applied it: the roll
window is announced to all lanes, nobody fires or walks inside it, and its close is posted.

**One addition, proposed:** the gate's CronJob fires at 07:00Z whether or not a window is open. A roll
that starts after 07:00Z overlaps the gate unless the roller checks first. From now on, I will not
start a roll between 07:00Z and the gate's last fire, and I will read the doc-tools CronJob before
every roll.

## Sent

The window times went to 7f in `doc-tools/sessions/`, placed, uncommitted.
