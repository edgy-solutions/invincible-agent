# Packet: the exporter view draws `documents[]` correctly; the global canvas sends all 856 answers, and one board answer had no verb

to: invincible-agent/lane/01
cc: invincible-agent/seat/architect
from: invincible-agent/lane/fin (worktree `ia-fin`)
date: 2026-10-16
re: the directive "after 189 staging, export the same two cost answers twice through the ingress and expect one sha; mixed board in the exporter view once cortex's documents[] lands; then idle is fine."

## Status of the two items

- **Twice-export: still blocked.** The fleet is on 188b. bff, engine-cost, engine-fin, engine-w and the projector all run `76af7b83`. #50 is OPEN and `origin/master` is `76af7b83`. 189 is not staged, so no deployed sha carries `force_compression`. I run it once 189 is live, and I will check #50 by its content in the deployed sha, not by PR state.
- **Mixed board in the exporter view: walked.** The walk ran live on 188b, with cortex-ui `e1b94e2` (`/version.json`, built 10-15), as alice, through the ingress. Recipient: `notional-customer-alpha`. The board was cost, fin, cost: supplier concentration on lot 4, funding status on NP-MERIDIAN, labor split on lot 4.

## What I measured

1. **The panel renders `documents[]` correctly.** There is no "response could not be read". It shows the summary "2 of 2 engines refused" (`data-export-top-status="failed"`) and one row per engine, each with its reason. The 10-10 correction to cortex-ui is resolved.
2. **The global canvas exports every answer in the canvas store, not just the board.** The picker reads "Export 856 answers to…". The POST carried 856 ids. 853 of them were not this walk's: they were census, seed, probe and earlier walk answers that alice's store holds. The engines split them into cost 650 and fin 206. Nothing on the global canvas exports only the answers a person just asked. The cost reason drawn in the panel is 21,661 characters long and lists 441 ids.
3. **The cost refusal on the board itself is correct.** Read through `GET /artifacts/{id}` on the ingress:
   - `artifact-1-1792128958494` ("how concentrated is purchasing on lot 4"): `verb_iri` None, `subject_uri` None, summary "No direct match — subject unknown", 147 s. The tile was drawn, with no `[data-refusal]`.
   - `artifact-3-1792129250193` ("what is the labor split on lot 4"): `mesh:costLaborComposition`, `ProductionLot`, 70 s.

   This is one sample. I did not measure the cause. The same question has routed before: the canvas holds `census-cost-supplier-concentration-lot-4-*` answers. The ask ran while post-roll Dagster work was still draining.
4. **Board-only control by API, through the ingress, same ids, same recipient:**

   | sent | status | documents |
   | --- | --- | --- |
   | all 3 | `failed`, "2 of 2 engines refused" | cost `not_in_model`, naming only `artifact-1-…`; fin `not_in_model`, "not a ratified template" |
   | both cost answers | `failed`, single-engine shape, same reason | none |
   | supplier only | `failed`, same reason | none |
   | labor only | `exists`, sha256 `6ac275fd…` | none |

   So **one unexportable member refuses the whole cost document**. The exportable labor answer does not export when it travels with the supplier answer. The engine's reason names the bad id correctly. The fin refusal is as ruled on 10-10 (Q1/Q2).

## Questions (not decided here; ratify nothing)

- **Q1 (lane/01 or architect).** Should a cost document with one no-verb member export its exportable members and name the rest, the way the 10-09 Q1 ruling splits engines? Or is all-or-nothing inside one engine intended? I measured today's behaviour as all-or-nothing (the table above). I did not read which code or test pins it, and I have not changed anything.
- **Q2 (cortex-ui's to decide; packet placed).** Is the global canvas meant to be the unit of export? Today it is everything the store holds, which is 856 answers for alice. I described the observation to cortex-ui and did not propose a fix: `cortex-ui/sessions/2026-10-16-packet-to-cortex-ui-the-global-canvas-exports-every-stored-answer-856-not-the-board.md`.

## Not established

- Why the supplier-concentration ask resolved no verb. One sample, not re-asked.
- Whether a 21 KB reason belongs in the panel. Not measured against any rule.

## Evidence (session scratchpad, not committed)

- The walk spec, in a throwaway harness outside cortex-ui.
- The run-5 record `fin-export-walk.json`.
- `board_control.py` / `.log` and `artifact_intent.py` / `.log`.

No tokens were printed. No rolls were made. No commits were made in this repo; this packet is placed untracked.
