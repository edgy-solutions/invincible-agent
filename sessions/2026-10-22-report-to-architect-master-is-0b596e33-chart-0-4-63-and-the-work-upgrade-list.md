to: invincible-agent/seat/architect
cc: doc-tools/lane/7f
from: invincible-agent/lane/01
date: 2026-10-22
re: "Approved: merge lane/01-202 to master … bump the chart version … give Chris the work upgrade as one paste-able list", via Chris
relay: Chris

Committed on lane/01-202. This report carries no secret and no infra detail.

# Master is `0b596e33`, a fast-forward. Chart 0.4.63 is published. Work needs one image change: the BFF

## Your two questions

| question | answer |
| --- | --- |
| Did roll 206 happen? | **Yes.** Helm rev 214 went live at 17:41Z with BFF `67d6e9f6` and cortex `c390a03`. Every gate held (report `642b9e3e`). |
| Did the amber test pass? | **It has not been run.** The lab BFF log for the 3 h since the roll has no `ingest_kind_unidentified` line and no document drop at all; the only ingest call is a `POST /ingest/events`. The TI drop is still Chris's to make. It can now be made at work (check 2 below) as well as in the lab. |

## What I did

- **Fast-forward.** `origin/master` `42f9945c` was an ancestor of the lane head: 10 commits, with nothing on master that the lane lacked. I pushed the agreed sha to `refs/heads/master`, without force: `42f9945c..0b596e33`.
- **Chart 0.4.63** (`0b596e33`): the only change is the version line. `tests/test_chart_version_tracks_chart_content.py`: 8 passed, 1 skipped.
- **Release Helm Charts** (run 39831304813): succeeded. Release `invincible-agent-0.4.63` exists with the `.tgz` and `image-digests.json`.
  - Its image retag warned: "some images were missing". It ran while the container build for `0b596e33` was still going, which is the step's documented exit-3 case.
  - I re-run the retag by `workflow_dispatch` once the build is green. The result is under "CI after the push" below.

## Diagnosis that led here (work, today)

- **Work's PCN drop ran as a plain PDF.** On the run at attempt 4, the Dagster log reads the sidecar as `content_kind='pdf'`, `domain_type=None`, then "ORIGIN UNRESOLVED … Writing nothing". The run succeeds and posts nothing more, so the row sits at `extracting`.
- **Work's BFF `42f9945` cannot do otherwise.** On it, a pick at `received`/`extracting`/`failed` only records the leaf on the row, and nothing rewrites the sidecar: `_apply_leaf_to_sidecar` does not exist before `7bd00941`. Each Retry re-ran the same PDF sidecar.
- **The relaunch itself was never broken at work.** The 5-minute wait before it starts is doc-tools' sensor floor (300 s).

## The work upgrade, as one list for Chris

**Images**
1. **BFF: the only image whose code changed.** `42f9945..0b596e33` touches `src/iagent/gateway.py` and `src/iagent/ingest_status.py`, plus SQL, tests, docs and the chart. Mirror `cortex-bff` at tag `67d6e9f6b26d91d05d29e400ea5427576111df0f` into Artifactory. That is the image rev 214 rolled and gated in the lab.
2. **cortex-ui: no change.** Work already shows `ui c390a03`, which is digest `sha256:2359f48e70bfe44fa8f43a709bd6773d007769c81ffb2d56f7921bba96a2f9ce`, the same one the lab runs.
3. **doc-tools: no change.** Work stays on `809963c`; 7f's report says nothing in it ships differently.

**Chart:** `invincible-agent` **0.4.63**.

**Values (work's own values file)**
- **Set:** `cortexBff.image.tag: "67d6e9f6b26d91d05d29e400ea5427576111df0f"`.
  - If work drives every image from `global.imageTag` instead, every image must be mirrored at that tag. Only the BFF's code differs, so the per-service key is the smaller change.
- **Added since `7a98f7bd`: nothing for work.**
  - `values.yaml` and every template are byte-identical between `7a98f7bd` and `0b596e33`.
  - No new secret.
  - The only values changes are in `values-sandbox.yaml`: the sandbox cortex digest, and a sandbox Keycloak test user and delegate role (`operator.regioneast`). Neither applies at work.
- **New env, all optional:** `INGEST_LEAF_RELAUNCH_INTERVAL_SECONDS` (default 60) paces the relaunch pass and the finished-run-with-no-kind pass. Leave it unset.
- **Keep yours (do not take the sandbox's):**
  - `USER_ENTITLEMENT_CLAIM` (employee id);
  - the OIDC issuer and its client settings;
  - the image registry and repository paths (Artifactory);
  - `DOC_TOOLS_SERVICE_IDENTITY`, if work set one;
  - the DataHub PAT;
  - the policy repo and seed CronJob settings;
  - `overlayEnums`;
  - every `*.secret.yaml` / Secret.
- **Database:** one new nullable column, `ingest_status_projection.hold_reason`. The BFF adds it at startup (`ADD COLUMN IF NOT EXISTS`, idempotent), as it did for the leaf columns work already has. Nothing is run by hand.

**Order**
1. Mirror the BFF image (item 1).
2. In Dagster, confirm no runs are QUEUED or STARTED. A STARTED run from a dead worker holds one of the 2 slots for ever.
3. Render the upgrade and diff it against `helm get values` for work's release. Expect exactly one changed path, `cortexBff.image.tag`, plus the chart version.
4. `helm upgrade` to chart 0.4.63 with work's values.
5. Wait for the BFF rollout. Its startup log must show no migration error. Then `/health`.

**Checks after the upgrade**
- **0. The stuck row heals itself.** `MAR053_NDC_20240403_008.pdf` (`sha256:8691f4d8…`) is leafed PCN, its sidecar says pdf, and its run has finished. That is exactly what the relaunch pass looks for.
  - Within about 60 s of the BFF starting, its log shows `ingest_leaf_relaunch ingest_id=sha256:8691f4d8… … decision=relaunched`.
  - The row goes to `received` at attempt 5.
  - Within about 5 min (the sensor floor) a Dagster run starts, and its first ADR-0041 line reads `content_kind='pcn'`.
- **1. A drop.** Drop a PDF work has **never seen before**: a re-drop is a duplicate and shows the old row. Pick no kind. The row goes `received`, then `extracting`, with `? · not read yet`.
- **2. Amber after run 1.** When that run finishes (Dagster SUCCESS), the BFF logs `ingest_kind_unidentified ingest_id=… decision=awaiting_kind` within about 60 s.
  - Cortex turns the row amber with `Needs you: what kind is this?`, the header shows `Needs you 1`, and the card shows PCN and PDN as buttons.
  - Work's doc-tools has no title read (`leaf_read.py` is not in `809963c`), so every unpicked drop should take this path.
- **3. A pick that relaunches as PCN and reaches review.** Click PCN.
  - The answer is 200. The row goes to `received` at attempt 2, and the BFF has rewritten the sidecar first.
  - Within about 5 min a run starts whose log reads `content_kind='pcn'`, **not `'pdf'`**. The row reaches `review` and a review task appears.
  - A `503 sidecar_unwritable` on the pick means the BFF cannot write the drop's manifest in S3 (it uses the same bucket and credentials as the drop upload). Nothing is written to the row in that case.

**If a check fails:** roll the BFF back to `42f9945`. Nothing else changed, and the new column is nullable and ignored by the old code.

## CI after the push

- **Build & Push Container Images on `0b596e33`** (run 39831304818): success.
- **The retag re-run** (`workflow_dispatch`, chart 0.4.63, sha `0b596e33`; run 39832309868): success, with no missing-images warning.
- **GHCR `cortex-bff`, read anonymously:**

| tag | answer |
| --- | --- |
| `0.4.63` | 200, `sha256:5457fdac…` |
| `0b596e33…` (full) | 200, `sha256:5457fdac…` (the same bytes, so the retag landed) |
| `67d6e9f6…` (full) | 200, `sha256:c10ad307…`. This is the image rev 214 rolled and gated, **and the one work should take** |
| `0.4.62` | **404** |
| `0.4.99` (negative control) | 404 |

- **`0.4.63` and `67d6e9f6` are different bytes of the same BFF code.** Between the two commits, only the chart, `values-sandbox.yaml` and docs changed. Work takes `67d6e9f6` because that build is the one that was measured live.
- **0.4.62's image tags were never retagged.** Its push-time retag would have hit the same race (the build still running), and nobody re-ran it. Nothing pulls `0.4.62` by tag today. I have not re-run it: whether to is yours.
