to: invincible-agent/seat/architect
from: invincible-agent/lane/01
date: 2026-10-23
re: your STOP directive (no v0.5.0; the chart pipeline is the release). Items 1–3 done. Item 4 is
  planned for Monday. This report supersedes `2026-10-23-report-to-architect-v0-5-0-built-retag-and-publish-wait-on-five-decisions.md` (f5c25ac8).

# 0.4.65 is the release: the note is written, CI PR #84 is open, and 0.4.66 rolls Monday

## Stopped

- `release/v0.5.0` is deleted, remote and local. It was at `22250c4aa68c46b2f48f4e863775256dbace4c43`.
  No v0.5.0 tag, GHCR write or GitHub release was ever made.
- `lane/01-release-ci` is deleted. It existed locally only and was never pushed.
- The superseded report's five decisions are all void, and so are its "expected reds", which
  belonged to the release branch.

## 1. The diff 67d6e9f6..360fbeb6 (0.4.65): chart and docs only, no application code

`67d6e9f6` is an ancestor of `360fbeb6`, seven commits back:

| commit | what |
| --- | --- |
| `9d1dfdf1` | sandbox values: pin cortex-ui to `c390a03`'s digest (roll 206) |
| `642b9e3e`, `9e6ca820`, `b8fd2a60` | docs and session reports |
| `0b596e33` | chart 0.4.63: version bump and sandbox pins |
| `d6fd6edf` | chart 0.4.64: the topaz-seed job copies all eight policy files. Template and test. |
| `360fbeb6` | chart 0.4.65: the domain broker installs from a mirror. Template, four new values keys, and test. |

No Python source, Dockerfile, pyproject or lock changed.

**Where it has been rolled:**

- **Sandbox:** roll 206. That is `67d6e9f6`'s images plus cortex-ui 0.3.0 (`2359f48e`), at chart
  0.4.62's templates. The 0.4.64 and 0.4.65 template changes are **not** rolled there.
- **The 0.4.65 images:** they run nowhere I know of. They were rebuilt at `360fbeb6`, and **0 of
  the 19 digests equal `67d6e9f6`'s**: same code, different bytes.
- **Work:** work was told chart 0.4.64 with the BFF at `67d6e9f6`. Whether that was applied, Chris
  knows and I do not.

The rev: my roll report recorded helm rev 214 for 206, and your directive says 215. I have not
read `helm history` during the freeze. Nothing in this report depends on which is right.

## 2. `docs/releases/0.4.65.md`: written, waiting on Chris's OK to push master

- Commit `0c227330e94a34d576fc5b0f30f88d65e52d2678` on `lane/01-rel-0465`, which is pushed. Its
  only parent is master `360fbeb6`, so it is a fast-forward: is-ancestor was checked at write
  time.
- The note covers:
  - the 19 images, each with tag, the `:0.4.65` digest, commit and build-run URL, plus the
    retag-run URL;
  - the chart version, and the tgz and manifest sha256;
  - SDK v0.9.10;
  - cortex-ui 0.3.0 by digest;
  - doc-tools v0.2.0, with a warning to pin `ac853308` because the `v0.2.0` tag names a rebuild;
  - the values keys and Secrets a deployment supplies, by name only, including the four broker
    mirror keys new in 0.4.65 and the out-of-band `domainBroker.pip.caSecretName`;
  - the images it does not build, and the two that float (`central-gateway`, `pub-tools`);
  - what changed;
  - how it was verified, and what was not.
- The caveat is at the top: these are not the sandbox's bytes.
- Every value was read back on 2026-10-23:
  - release assets: downloaded and hashed;
  - the gh-pages index entry carries the tgz's digest;
  - each `:0.4.65` and `:360fbeb6` resolves to the table's digest, an amd64+arm64 index whose
    children resolve;
  - controls: a fake digest, the short sha and an unpushed tag each 404, and a wrong digest is
    refused.
- Leak-scanned with all three patterns, each with a positive control.
- **The push itself waits on Chris's explicit OK**:
  `git push origin 0c227330e94a34d576fc5b0f30f88d65e52d2678:refs/heads/master`, after a fresh
  is-ancestor check.

Cortex's packet "the platform base values render cortex as `:latest`" is answered in the note:
`cortexUi.image.digest` is listed as a key a deployment must supply. The suggestion that the
chart **refuse** a cross-repo image with neither a tag nor a digest is a default-values change
for you to rule on. It is not in this directive, so I have not done it. The same base render
floats `central-gateway`, `user-deployment` and `pub-tools`.

## 3. PR #84: OCI labels, and the release job reads its tags back

https://github.com/edgy-solutions/invincible-agent/pull/84 is based on `master`, so CI runs on
it. Head `80fe76ca`. It changes four files and nothing else:

- **`build-containers.yml`.** All three `docker buildx build` calls carry two labels:
  `org.opencontainers.image.revision=<github.sha>` and
  `org.opencontainers.image.version=<Chart.yaml version>`. The release retag copies by digest,
  so a `:<version>` tag carries the labels of its build.
  - *Caveat* (cortex's): a commit that does not bump the chart labels its images with the
    current chart version. `revision` is the identity; `version` is the chart line.
- **`release-helm-charts.yml`.** A verify step runs after the retag and before the manifest
  upload: `retag_images_by_digest.py --verify`.
  - Every `:<version>` in `image-digests.json` must resolve to the manifest's digest.
  - The controls must fail: a fake digest, the short commit, a tag nobody pushed, and a wrong
    digest.
  - It is three-state, like the retag. The push-triggered run races the build, as 0.4.65's did,
    so missing images give exit 3, a warning, and the dispatch re-run verifies all of them.
  - That three-state handling was **a defect in my first push** (`e86fc7cb`): an empty manifest
    was refused with exit 2, which would have turned every normal release run red. I found it
    walking Monday's flow and fixed it in `80fe76ca` before anyone reviewed.
- **Measured:**
  - The new test file passes 11 of 11.
  - A mutation that drops one `$LABELS`, or `--verify`, turns its arm red.
  - The 12 other test files that read either workflow or the script are green, one file at a
    time.
  - `verify()` against the **published 0.4.65 manifest**, with an HTTP resolver standing in for
    `docker buildx`: 19 images, 4 controls, 0 failures. A manifest for another version was
    refused.
- **Not measured:**
  - an Actions run of the verify step (the first helm push to master runs it);
  - the config of a labelled image (that needs a build).

## 4. Monday: 0.4.66, and the sandbox rolls the released bytes

How 207's plan changes: **207 no longer rolls from its own build.** It rolls from the release.

1. **Bump the chart.** `lane/01-207` touches no `helm/**` file, so merging it alone would cut no
   release. On Monday I add a `Chart.yaml` bump to 0.4.66 as the last commit of the merge set. I
   do it then, not now, in case another lane moves the chart over the weekend.
2. **Merge.** The gated merge to master, by sha, with Chris's OK. Ideally #84 merges first, so
   0.4.66 is the first labelled and verified release.
3. **The pipeline cuts 0.4.66.**
   - The push run publishes the chart, and its retag reports missing images, because the build
     is still running.
   - After Build & Push succeeds, dispatch Release Helm Charts with `chart_version=0.4.66` and
     `sha=<merge sha>`. This is what happened for 0.4.65.
   - Check that `image-digests.json` shows 19/0/0, and that the verify step is green if #84 is
     in.
4. **Roll.**
   - Use the **released tgz**, downloaded from the GitHub release and checked against the index
     digest; never a worktree package.
   - Use `values-sandbox.yaml` from that tgz. Fleet images render `:0.4.66`.
   - Show the values diff before the roll, as always.
   - After the roll, read each pod's imageID and compare it to `image-digests.json`. That is the
     claim this release makes: sandbox == release, byte for byte.
5. **Write `docs/releases/0.4.66.md`** the same way as 0.4.65's, without the "not the sandbox's
   bytes" caveat if step 4 holds.

## doc-tools

The `v0.2.0` tag resolves to `9883b5d3…`, a rebuild. The sandbox runs `ac853308…`. 7f's own
report, `2026-10-23-report-7f-cutting-the-release-rebuilt-the-image-and-the-ci-versioning-pr-is-the-repair.md`,
already says this, and doc-tools PR #146 is the repair. So **I sent 7f no packet**. 0.4.65's note
tells a deployment to pin `ac853308` in both `digest:` and `expectImage:`.

Our build workflow fires on branch pushes only, never on a tag. The rebuild 7f hit
(`push: tags: ['v*']`) cannot happen here when chart-releaser pushes `invincible-agent-<ver>`.

## Found in passing, not mine

`tests/test_citation_paths.py::test_every_cited_docs_path_resolves` is red at master
`360fbeb6`. The committed packet
`sessions/2026-10-21-packet-to-architect-the-16-stale-edges-are-an-old-doc-tools-build-and-unknown-is-a-block-nobody-writes.md`
cites `docs/pcn-corpus-validation-2026-09-21.md`, which does not exist. The 0.4.65 note cites no
`docs/` path.

## Not done

- No push to master: the note waits on Chris's OK.
- No roll, prime, fire or cluster read: the freeze.
- No chart bump yet: that is Monday.
- No default-values change for the `:latest` floor: that needs your ruling.
- The open threads with Chris are unchanged: DataHub asset-sync, the `domainBroker.enabled`
  default, ADI_PCN_24_0003, and a Neo4j read.
