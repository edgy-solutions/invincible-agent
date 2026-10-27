to: invincible-agent/seat/architect
from: invincible-agent/lane/01 (release owner)
date: 2026-10-23
re: v0.5.0, built on `release/v0.5.0` at 22250c4a. No registry write and no publish yet. Five
  decisions are needed from Chris before either.

# v0.5.0: the chart, the pins and the note are built; the retag and the publish wait on five decisions

I have read cortex's packet ("0.3.0 is released by digest") and 7f's report ("v0.2.0 released,
image retag blocked on a credential"). **I never received the amendment** that both cite. All I
know of it is what those two peers quote: cortex-ui releases as 0.3.0 and doc-tools as v0.2.0.

## What is done (branch `release/v0.5.0`, pushed, tip 22250c4a)

| item | state |
| --- | --- |
| 1 fleet images | `scripts/retag_release_by_digest.py`, with modes check-source, apply [--dry-run] and verify. It GETs each index by digest and PUTs the same bytes under the tag. check-source: 17 of 17 at 67d6e9f6's digests, all amd64+arm64. Before apply, `verify` fails 17 of 17 as it should, and the short-digest and fake-digest controls are refused. `apply --dry-run`: 17 would tag. **No tag has been written.** |
| 2 chart | Chart 0.5.0 uses 0.4.62's templates. values.yaml and values-sandbox.yaml pin every image as `<tag>@<digest>`: fleet images `v0.5.0@…`, cortex-ui `0.3.0@2359f48e…`. `scripts/release_render_check.py` checks two things. First, every rendered release image carries its own tag and digest; a repo the manifest does not name counts as unpinned. Second, the release render equals the 206 render, made with both of its roll-time overrides, apart from four named rules. Each rule must hit in both renders. Result: 0 differing lines and 0 dead rules. The tgz is packaged from a `git archive` of 7137c42d, with no secret file inside: sha256 `db223467…`, 195178 bytes. **Not published.** |
| 3 note | `docs/releases/v0.5.0.md` covers: 17 image rows generated from `docs/releases/v0.5.0.images.json`; the cross-repo rows (cortex-ui 0.3.0, doc-tools v0.2.0 pending, SDK v0.9.10); the chart version and digest; the values keys and Secrets a deployment supplies (names only); what changed since 0.4.62; how each claim was verified; and what was not verified. |
| 4 labels | Not started, as ruled: the next build picks it up. It goes to Monday's 0.5.1. Cortex's caveat stands, and the ruling's wording should settle it: a `version` label baked at build time cannot equal a release tag cut later without changing the digest. |

## Since chart 0.4.62

- The code change is BFF-only: 7bd00941 and 67d6e9f6.
- The DB adds `retry_reason` and `hold_reason`, both nullable. The BFF applies them at startup.

## Decisions needed (Chris / architect) before any GHCR write or publish

1. **The platform tag: `v0.5.0` or `0.5.0`?** Cortex writes that its tag has "no `v`, like the
   platform's", but your directive says `v0.5.0`. The pins, the manifest and the note all say
   `v0.5.0`. A pushed tag is never rewritten, so I will not write either until this is
   answered.
2. **The retag credential.** The `gh` token lacks write:packages, which is the same block 7f
   hit. There are two paths:
   - (a) Port cortex's proven `retag-image.yml` (workflow_dispatch, GITHUB_TOKEN with
     packages: write). A dispatchable workflow must be on master, so this needs a gated merge.
   - (b) Chris runs `apply` locally with a write:packages PAT in `GHCR_TOKEN`.

   I recommend (a), because it is the path 7f also needs.
3. **The chart publish.** The plan is `gh release create invincible-agent-0.5.0` at the release
   commit, with the exact tgz above and the manifest, then `helm repo index --merge` onto
   gh-pages. This is outward-facing and needs an OK.
4. **The chart-version seal is red on 7137c42d.**
   `test_a_chart_change_bumped_the_chart_version` fails because 7137c42d re-pinned cortex-ui
   after f49a9fdc set 0.5.0. Nothing was published at f49a9fdc, so no two published contents
   share 0.5.0. There are three options:
   - accept the red on the release branch and record it, as the note now does;
   - bump the chart to 0.5.1, which collides with "Monday is 0.5.1";
   - touch Chart.yaml so the seal passes, which I will not do, because that games the seal.

   I recommend the first.
5. **0.5.0 lacks the 0.4.64 and 0.4.65 fixes, and outranks 0.4.65.**
   - 0.4.64: the topaz-seed job copies all 8 files.
   - 0.4.65: the broker installs from a mirror.

   The note says this, and that `--version` must be passed. A work deployment that wants
   either fix needs 0.5.1.

## Discrepancies to reconcile

- **The rev.** My roll report recorded helm rev 214 for roll 206. Your directive says 215. I
  have not read `helm history` during the freeze. Every pin was derived from 67d6e9f6's build
  run and from 206's committed values, never from a rev number, so the release does not depend
  on which rev is right.
- **Pod imageIDs were not read.** The freeze rules out cluster reads that need approval. The
  claim that the sandbox runs these digests is therefore a claim about the committed values
  and the build run. After the freeze, one `kubectl get pods -o jsonpath` imageID read closes
  it.
- **Untagged `:latest` images.** central-gateway and pub-tools render as `:latest`, and the
  release does not pin them. The note lists them under "Other images". Should they be pinned,
  or dropped from the deployment?

## Expected reds on `release/v0.5.0` (by design, not regressions)

| file | result | why |
| --- | --- | --- |
| test_the_fleet_can_be_pinned_to_one_commit | 4 failed | it asserts that one setting (`global.imageTag` or the chart version) moves every fleet image; a release pin exists to stop exactly that |
| test_sandbox_image_tags_resolve_to_a_published_tag | 2 failed | the same assertion, as the note groups them |
| test_chart_version_tracks_chart_content | 1 failed | decision 4 |
| test_chart_renders_on_bare_defaults | 6 passed | |

`master` is unaffected: nothing in the release has merged.

## Not done, by me

- No GHCR write, no GitHub release and no gh-pages push.
- Nothing has been copied to `lane/01-207` or master. Once v0.5.0 is final, the note and the two
  scripts go to master through 01-207.
