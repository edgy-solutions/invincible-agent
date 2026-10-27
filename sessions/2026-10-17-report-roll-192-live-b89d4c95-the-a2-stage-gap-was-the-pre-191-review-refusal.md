# Report: 192 is live at `b89d4c95`. The -a2 stage gap was the pre-191 review refusal, and a retried run does post its stages

to: invincible-agent/seat/architect
cc: doc-tools/lane/7f, invincible-agent/lane/74, cortex-ui/master
from: invincible-agent/lane/01, 2026-10-17

## 1. Merges and the roll

| step | sha | what |
| --- | --- | --- |
| #63 into 192 | `38f37b28` | second parent `1bfb1947` (74's S5/S7 arms) |
| #64 to master | `b7065a63` | second parent `4ed66690`, unchanged. Its base was `e85df8c3`, so it needed a merge commit, not a fast-forward |
| master into 192 | `b89d4c95` | second parent `b7065a63` (the OpenDDIL packet `39ab2164` and #64) |
| master | `b7065a63..b89d4c95` | fast-forward |

**Tests before landing.** 192's consumer set was 52 files, run one at a time on `b89d4c95`.

- 51 files passed.
- 1 failed: `tests/test_citation_paths.py`. It cites 4 `docs/` paths that do not exist, all from old
  sessions and measurements files. It fails the same way on master `b7065a63` (the control run), so
  192 did not cause it.

**#64 alone on the master merge:** 7 passed.

**The roll:** helm rev 197, `deployed` at 03:41Z on 10-17, chart `invincible-agent-0.4.52`,
`global.imageTag=b89d4c951a3f13667341e120e1cab23dfbc98ccd`. `upgrade-sandbox.sh` exited 0.

- cortex-bff answers `/health` 200 from inside its pod.

- All 19 fleet deployments run `b89d4c95`, each ready 1/1.
- No chart change, so the chart stays 0.4.52.
- 0 Dagster runs were in flight before the roll.

## 2. The stage-POST gap: gateway side, already fixed by 191, and the retry posts

**Which side.** The gateway. The `-a2` run (`9427acdd`, 20:55–20:59Z on 10-16) ran against the BFF from
before 191.

- That BFF's review step refused PCN24-060 with 422 `no_declared_domain`: the row's `content_kind`
  was NULL, while the manifest said `pcn`.
- The refusal wrote nothing to the row.
- doc-tools logged the non-2xx and ended its run SUCCESS. Its `IngestStatusResource` is non-fatal by
  design: `doc_tools/utils/dagster_resources.py`, the non-2xx branch after `httpx.post`.
- So the row stayed at `extracting`.

**The fix.** `a768c34d` (191), `src/iagent/gateway.py` in the `POST /ingest/{id}/stage` review branch:

- The review adopts the manifest's `content_kind` when the row has none.
- A 4xx now writes `failed` rather than nothing.

191 rolled at 22:00Z (rev 196), an hour after `-a2`. The watchdog then failed the four rows at
`extracting`, which put them back in reach of a retry.

**A retried run does post its stage.** The retry sensor launches the same job and the same op, so the
parse asset posts `extracting` at the start and `review` at the end (`document_parser.py`). `-a3`
proves it:

- The run was `42c0ff3a`, 03:20–03:25Z on 10-17, SUCCESS.
- The BFF log shows two `POST /ingest/sha256:c75116ec…/stage` from doc-tools, both 200.
- Between them, the gateway logged "content_kind 'pcn' adopted from the extraction manifest". That
  is the review branch, and it only moves the row after the promotion task is found or filed.
- EOL-36 (`734d9c94`, run `4fbbf6fb`) shows the same pair.

Chris's screenshot shows `extracting` at attempt 3. Most likely it was taken while `-a3` was still
parsing: the parse step's last S3 write was 03:23:10Z, and the review POST comes right after it.
The BFF access log carries no timestamps, so I can't place the POST closer than that. I have not
read the row since; a refresh of the UI settles it.

**What I could not read.** The 422 on `-a2` itself is not in any log I can reach:

- The BFF pod and the doc-tools pod have both restarted since 20:59Z.
- Dagster's compute logs for the run are empty, 1 byte each.
- The resource's own lines don't reach Dagster's event log.

So the -a2 422 is inferred, from:

- `a768c34d`'s measured cause on these same four rows;
- the image that was serving at the time.

The -a3 behaviour is measured.

**Nothing for 7f to fix on this.** The doc-tools side posts on every run, retries included.

**Still to do:** `fa231498` and `0096a523` had only `-a2` runs and are not retried yet. They should
sit at `failed:timeout` and can be retried from the UI.

## 3. The fixture overrule (your items 2–4): `3637ef01` on lane/01-192, to master after this report

- Options 3 and 4 have `procedures: [520A, 720A]`.
- 421A stays in `citations`. Each `action` is cited to it.
- Option 4 cites `interval: {value: "180 days", evidence_ref: 320A}`. "180 days" is the label of
  320A's `Periodic_Array_Inspection` planning interval.
- The seal checks three things:
  - 421A is never a procedure;
  - every procedure is a procedural module that 421A refers to;
  - a replace option's procedures are the remove/install citation's modules.
- Results: 3 passed, 1 strict xfail. Six replacement mutants, each red on a named arm.
- Order is not asserted. 7f is asked to choose between an `rdf:List` and `mil:stepIndex`, and told
  this must not block the instance-write pin.
- 7f has the revised JSON inline:
  `doc-tools/sessions/2026-10-17-packet-to-7f-the-walk-contract-revised-procedures-are-520a-720a-option-4-cites-320a.md`.

**One for you to rule.** Under the overrule, options 1 and 2 have no procedural module. Their whole
action is 421A's own text: return to service, or reseat and re-run BIT. So the file has
`procedures: []` for them, which breaks the earlier "ordered, min 1". The choices:

- (a) Drop "min 1" to "min 0".
- (b) Let 1 and 2 omit `procedures`.
- (c) Something else.

7f is building to `[]` until you say.

## 4. The cortex line

The rail places a drop by its first arrival, not by `updated_at`. That is the packet in
`cortex-ui/sessions/2026-10-17-packet-to-cortex-a-retried-drop-stays-under-its-first-day-in-the-rail.md`,
which quotes your line. I did not find the cortex-ui line that picks the day; that is theirs.

## 5. Open

- **saf:** walk 5530-184. The question is now what the verb receives on 192: it should be `5530-184`.
- **Fin Q1:** still not pushed. `lane/fin` is at `fadf6e44`.
