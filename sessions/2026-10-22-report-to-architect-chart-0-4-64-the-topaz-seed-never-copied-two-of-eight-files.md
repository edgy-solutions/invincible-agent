to: invincible-agent/seat/architect
from: invincible-agent/lane/01
date: 2026-10-22
re: Chris, "ok now I am struggling getting topaz to run its ingestion" (the work seed refused with 4 errors); Chris approved the merge and release
relay: Chris

Committed on lane/01-202. This report carries no secret and no infra detail.

# Master is `d6fd6edf`, chart 0.4.64. Since 10-02, the topaz seed has refused every run that reads policy from a ConfigMap or git. Work takes 0.4.64, not 0.4.63

**This replaces the chart version in my report `9e6ca820` ("the work upgrade list"). Work upgrades to chart 0.4.64. Every other item in that list is unchanged, including the BFF at `67d6e9f6`.**

## What work's seed reported

The seed found every file and validated it, then REFUSED with 4 errors:

1. `domain_consumption.yaml: MISSING`
2. `program_members.yaml: MISSING`
3. A `task_grants.yaml` grant to `33333333-…` under `document_promotion:MAINTENANCE` names a user who is not in `users.yaml`.
4. Audience `document_promotion:MANUFACTURING` grants group `manufacturing-stewards`, which has zero members, so the task would route to nobody.

## Errors 1 and 2 are a chart defect, now fixed

- **The cause:** in `configMap` or `git` mode, the seed CronJob builds `/work/policy` with a hand-kept `for f in …` copy loop and then runs `validate_policy.py`. On 2026-10-02, `82ed0b7f` added `domain_consumption.yaml` and `program_members.yaml` to the validator's `DATA_FILES` but not to the loop.
  - So from that day, every run in those two modes was refused `MISSING`, whatever the overlay held.
  - The sandbox reads policy from the image, never builds the directory, and so could not see it.
- **The fix** (`d6fd6edf`): the loop copies all eight files, and the template's comments now say eight.
- **The test:** `tests/test_topaz_seed_compose_copies_every_validated_file.py` reads `DATA_FILES` from the validator (parsed with `ast`, not restated) and renders both modes. It requires the loop to equal that set exactly.
  - Against the unfixed template: 2 of 5 red, naming the two files.
  - After the fix: 5 of 5 green.
  - Neighbouring tests, run one file at a time, are green: the task-grant startup sync renders (10), the chart renders on bare defaults (6), `test_validate_policy.py` (7), and the chart version tracks chart content (8 passed, 1 skipped).
- **Work's policy repo must also hold both files.** With the fix, a file absent from the overlay makes the build step itself fatal. I checked that these empty forms pass `validate_policy.py` (exit 0), and that a missing file is still refused (exit 2):
  - `domain_consumption.yaml` containing `domain_consumption: {}`
  - `program_members.yaml` containing `programs: {}`

## Errors 3 and 4 are work's data, and they are Chris's to fix

Work's `task_grants.yaml` carries sandbox grants:

- **Error 3:** `33333333-…` is a sandbox test user's id. It must become a work user's `id`, or the audience must grant a group that has members.
- **Error 4:** `manufacturing-stewards` needs at least one member in work's `users.yaml`. Otherwise that audience should be removed.

The validator is right to refuse both, so nothing changes on our side.

## Merge and release

- **Fast-forward:** `0b596e33..d6fd6edf` (2 commits: my report `9e6ca820` and the fix). I checked `is-ancestor` first, pushed the full sha, and did not force.
- **Release Helm Charts** (run 39856062579): succeeded. Release `invincible-agent-0.4.64` exists with its `.tgz` and `image-digests.json`.
  - Its retag step ran before the image build finished, the same race as at 0.4.63, so it tagged 0 of 19 images.
  - The result of the re-dispatched retag is under "Retag" below.

## Retag

- **Build & Push Container Images on `d6fd6edf`** (run 39856062500): succeeded.
- **The retag re-run** (`workflow_dispatch`, chart 0.4.64, sha `d6fd6edf`; run 39856884177): succeeded, with **19 of 19 images tagged**.
- **GHCR `cortex-bff`, read anonymously:**

| tag | answer |
| --- | --- |
| `0.4.64` | 200, `sha256:0c99bcf5…` |
| `d6fd6edf…` (full) | 200, `sha256:0c99bcf5…` (the same bytes, so the retag landed) |
| `0.4.63` | 200, `sha256:5457fdac…` (unchanged) |
| `0.4.99` (negative control) | 404 |

- **I checked the released chart itself:** the `invincible-agent-0.4.64.tgz` on the release reads `version: 0.4.64`, and its copy loop lists all eight files.
- **Work still pins the BFF at `67d6e9f6`**, the build that rolled and passed every gate in the lab. Between `67d6e9f6` and `d6fd6edf` the BFF code is the same. `git diff --name-only` lists 3 files under `helm/`, 1 under `tests/` and 2 under `sessions/`, and nothing else. Work needs no image beyond the one in `9e6ca820`.

## Still open (unchanged)

- The amber test has not been run.
- `retry_reason`; the replacement pairs, pending your rulings; the walk's keep-alive fix.
- 0.4.62's retag is still yours to decide.
