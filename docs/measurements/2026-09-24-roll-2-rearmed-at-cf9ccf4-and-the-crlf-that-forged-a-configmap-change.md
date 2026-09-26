# Lane 1, 2026-09-24 — roll #2 re-armed at `cf9ccf4`, and a line-ending defect in my own gate

> **SUPERSEDED THE SAME DAY, AND VOID AS AN ARM.** `lane/74` moved again mid-order (the host
> identity scrub, `99b56be`, plus a packet), that merge landed on master as `03ee440`, and an arm
> names a sha — so the gate below is a fully verified gate over the **wrong head**. It is kept
> because §2, §4, §5 and §6 are findings about the chart and the gate, not about the sha: the CRLF
> census, the instrument defect, the sibling-pin result and the remedy all carry forward unchanged.
> **Only §1's arming sha and §3's diff line counts are void.** The live arm is
> `2026-09-25-roll-2-fired-at-03ee440-and-the-unpinned-image-that-broke-the-control-plane.md`
> — named exactly, not globbed. The first version of this line globbed
> `2026-09-25-roll-2-rearmed-at-03ee440-*`, which matched **nothing**: the successor is `armed`,
> not `rearmed`. A pointer that resolves to no file reads as a pointer until someone follows it.

**Armed at `cf9ccf4c984ecac5392849a9026f2b3f4a4483f0`, chart `0.4.10`. NOT FIRED — Chris fires on go.**

The headline is not the arm. It is that the gate's flagship leg — the full-manifest diff — was
**blind by construction** on this box, and the blindness was one stage upstream of where I
controlled it. Fixing it changed what the roll would deploy.

---

## 1. The arm

```bash
helm --kube-context <ctx> upgrade iagent helm/invincible-agent -n sandbox \
  --reuse-values \
  -f helm/invincible-agent/values-roll-frontend-digest.yaml \
  --set global.imageTag=cf9ccf4c984ecac5392849a9026f2b3f4a4483f0 \
  --no-hooks
```

Byte-for-byte the dry-run command minus `--dry-run`. Context is in the out-of-repo log.

| leg | result |
|---|---|
| CI `Build & Push Container Images` at the arming sha | **completed / success** |
| CI `Release Helm Charts` at the arming sha | **did not run — and correctly so** (§5) |
| 19 built images resolve with `arm64` | **19/19**, 4 platform entries each |
| bogus-sha negative control | **19/19 correctly MISSING**, 0 control failures |
| `--dry-run` renders | **rc=0**, no stderr |
| full-manifest diff | **289 lines: 288 semantic in four categories, 1 extraction artifact, 0 unaccounted** (§3) |
| sibling digests re-read | **4/4 pinned digests resolve with arm64**; all four `:latest` have **moved off the pins** (§4) |
| **chart-file byte integrity** | **FAILED, then fixed** — 5 files were CRLF on disk against LF blobs (§2) |

The population question from the last arming still holds: **19 built, 17 deployed.**
`langgraph-support` and `swarms-scraper` are built and not rendered by this chart. The image
census is over the 19; the manifest diff is over the 17 (19 occurrences — `dagster-server` and
`cortex-bff` appear twice each).

---

## 2. The defect: a CRLF working tree forged a ConfigMap change, and my instrument hid it

### What I measured

The diff reported `checksum/broker-code` changing. That annotation is
`{{ .Files.Get "files/domain-broker.py" | sha256sum }}` — and **the file had not been committed
to in 0 commits since the live deploy tag.** An annotation that hashes an unchanged file should not
move. Rather than accept it as drift, I reconciled it:

```
live annotation      : 6a3d364f3e489c0bdf6f9879fb956ce9f6ffb953f3db854c1b953916fca6e09c
rendered annotation  : e42cfbc595968a99bf85b0f9d60420a3c0e12ed564dae0aa6f4cbddea2f7f711
sha256 of the BLOB   : 6a3d364f…   <- equals LIVE
sha256 ON DISK       : e42cfbc5…   <- equals RENDERED
bytes: disk 9429, blob 9203        CR bytes: disk 226, blob 0
```

The working-tree file was **CRLF**; the blob is **LF**. `helm .Files.Get` reads disk bytes, so it
hashed CRLF. `git status` called the file clean the whole time, because `core.autocrlf=input`
normalizes CRLF→LF in the *clean filter used for comparison* — so a CRLF working file is invisible
to `git status` by design. **That is why nobody had seen it.**

### The instrument defect, which is the part worth keeping

I extracted the rendered manifest with `sed -n '/^MANIFEST:$/,/^NOTES:$/p'`. Measured:

```
helm's raw dry-run stdout : 2342 CR bytes
after my sed extraction   :    0 CR bytes
```

**msys `sed` silently stripped every CR.** So the gate's full-manifest diff was comparing a
CR-stripped render against the live manifest, and could not report a line-ending difference at all.

I *did* positive-control this — and controlled the wrong stage. I proved `diff` can see a CR-only
difference (it can: rc=1 on a two-line fixture). The blindness was in the extractor feeding it.
**A control on the comparator says nothing about the pipeline that built its inputs.**

Re-extracted byte-faithfully with a Python reader (`open(...,'rb')`, split on `\n`, never through a
text-mode tool):

| instrument | changed lines reported |
|---|---|
| `sed`-extracted (what the gate had been using) | **290** |
| byte-faithful extraction | **2007** |

1717 of those lines were CR-only differences the old instrument could not see.

### The population, censused rather than sampled

Of **43** tracked files under `helm/`, **5** were CRLF on disk against an LF blob; 38 clean; 0
unaccounted:

| file | disk CRs | reaches the manifest how |
|---|---|---|
| `files/domain-broker.py` | 226 | `.Files.Get` → broker ConfigMap **+ its checksum annotation** |
| `files/sql/create_answer_artifact_projection.sql` | 170 | `.Files.Get` → db ConfigMap |
| `templates/keycloak-configmap.yaml` | 131 | template text → rendered resource |
| `templates/prime-substrate-job.yaml` | 401 | template text → **hook, carries inline shell** |
| `templates/realm-reconcile-job.yaml` | 215 | template text → **hook, carries inline shell** |

`files/sql/create_bpmn_catalog.sql` is the other `.Files.Get` input and was **clean** — the
odd-one-out that proves this is per-file accident, not a chart-wide property.

### Blast radius, split by what `--no-hooks` actually excludes

- **In this roll:** the broker ConfigMap (+ a checksum change that would have **restarted the
  broker pod**), the db ConfigMap payload, and `keycloak-configmap`. All cosmetic-to-harmful
  depending on consumer; the pod restart is the concrete cost.
- **Not in this roll, and worse:** `prime-substrate-job` and `realm-reconcile-job` are **hooks**
  (3 hook annotations each), excluded by `--no-hooks`, absent from both live and rendered
  manifests. They carry **inline shell**. A `\r` in a shell script is not cosmetic. So **any
  hooked upgrade from a CRLF tree — `scripts/upgrade-sandbox.sh` — renders carriage returns into
  shell.** That hazard was live and invisible, and this roll is the one path that does not touch it.

### The fix applied, and its proof

Stripped CRs from all five, then verified **on-disk sha256 == blob sha256** for each — not "looks
LF now", the actual equality. 0 of 43 CRLF remaining. Re-rendered:

```
raw dry-run stdout CRs : 0    (was 2342)
checksum/broker-code in the diff : 0 lines   (was 2)
```

The broker annotation now **matches live**, which is the proof that CRLF was its entire cause and
that no real code change was hiding underneath it. **The broker pod will not restart.**

`git status` showed the five as ` M` after the rewrite; `git diff` was empty, `git diff --cached`
empty, and `git hash-object` equalled `HEAD:<file>` for each. That was git's **stat cache**
reacting to a changed mtime, not content.

**Correction to what this section first claimed.** It said the ` M` was "resolved by measuring".
It was not, and the difference is the finding: `git update-index --refresh` and even
`--really-refresh` kept answering `needs update` at rc=1 while `cmp` said identical and all three
hashes matched. **`--refresh` only *flags* a stat mismatch; it does not re-hash.** The state
cleared only after an explicit `git update-index -- <the five named paths>`, which re-records
them. Proven to have changed nothing: `HEAD` tree == `git write-tree` == `35d53326…`, so no
content entered the index. Measuring told me the content was identical; it did **not** clear the
flag, and reporting otherwise would have left the next reader unable to reproduce the fix.

### Cross-worktree census

All six lane worktrees (`ia-01 ia-32 ia-5f ia-74 ia-91 ia-eo`) carry **0 of 5** CRLF. **This tree
was the only affected one.** So the arm is valid for a render from any of them — but see §6, the
remedy, because nothing prevents recurrence.

---

## 3. The full-manifest diff, partitioned

289 changed lines against the live manifest:

| category | lines |
|---|---|
| engine images, `c0005142…` → `cf9ccf4c…` | 38 (19 occurrences × 2) |
| cross-repo images, `:latest` → `@sha256:` pin | 12 |
| `helm.sh/chart: invincible-agent-0.4.6` → `-0.4.10` | 236 (118 × 2, uniform — no third value) |
| `IAGENT_IMAGE_TAG` | 2 |
| **semantic total** | **288** |
| extraction boundary: trailing blank line (`5883d5882`) | 1 |
| **UNACCOUNTED** | **0** |

The trailing line is a real artifact of my extractor, not a chart difference: `helm get manifest`
ends with a blank line my reader drops. Named rather than filtered away.

**`checksum/broker-code` is absent from this table**, which is the whole point of §2.

---

## 4. The four sibling pins, and what they bought

All four pinned digests resolve as arm64-bearing indexes. And **every one of the four `:latest`
tags has moved off its pin**:

| image | pinned digest | `:latest` now | running pod | firing changes it? |
|---|---|---|---|---|
| `dag-tools/central-gateway` | `c05e0131…` | `df9d6c90…` | `c05e0131…` | **no** |
| `dag-tools/user-deployment` | `70092098…` | `ad790c94…` | `70092098…` (2 pods) | **no** |
| `pub-tools` | `ed93f7b1…` | `1555b341…` | `ed93f7b1…` (2 pods) | **no** |
| `cortex-ui/frontend` | `28f752f2…` | `567b96e7…` | live manifest `c8d6553f…` | **yes — intended** |

This is the clearest possible vindication of `ca23e9e`: **without the digest pins, firing this roll
would have silently re-pulled four different sibling images**, because all four tags moved. With
them, three components hold exactly what is running and only the frontend moves — `c8d6553f…` →
`28f752f2…`, one line (4452) in both manifests.

Absence control, per the previous arming's §1: the superseded `c8d6553f…` **still resolves**.
Overtaken, not deleted — so no absence is being asserted here.

The `datahub-frontend-react:v1.6.0` pod matched my substring filter and is **excluded with that
reason**: third-party image, not one of the four.

---

## 5. Why `Release Helm Charts` not running is a pass, not a gap

`release-helm-charts.yml` carries `paths: ['helm/**']`. The merge changed **0** files under
`helm/` (positive control: `ca23e9e` changed 4 and the workflow **did** run and **succeeded**
there, publishing `0.4.10`). So at `cf9ccf4` the workflow correctly did not trigger, and chart
`0.4.10` — the version this roll renders — is already published.

Stated because the previous arming learned the opposite lesson the hard way: an unbumped chart
**publishes nothing while reporting green**. The distinction is whether `helm/**` changed at all.
Here it did not, and the chart it needs was published one commit earlier. The roll renders from the
local chart directory regardless, so publication is not on its critical path.

---

## 6. The remedy, and why it is not `.gitattributes` alone

`.gitattributes` already carries `text eol=lf` for `*.sh`, `.githooks/*` and
`baml_shared/baml_client/**` — the precedent exists — but does not reach `helm/**`
(`git check-attr` returns `unspecified` for both a chart file and a chart input).

Extending it is worth doing and is **not sufficient**, for a reason worth writing down: `eol=lf`
governs what *checkout* writes. It does **not** make an editor's later CRLF rewrite visible,
because the clean filter normalizes CRLF→LF on comparison, so `git status` stays clean either way.
**No git-level setting can surface this.**

The leg that actually catches it is a byte-equality assertion, which is cheap and deterministic:

> Before rendering, for every tracked file under `helm/`, assert `sha256(on-disk) ==
> sha256(git blob)`. Refuse to render on mismatch, naming the files.

That is the seal I would add, and it fails today's tree before normalization and passes after —
both directions available as a fixture, because the five filenames and both hashes are recorded
above.

**Not committed.** Any commit now moves master off `cf9ccf4`, re-triggers the 19-image build
(`build-containers.yml` has no path filter) and invalidates this arm. It should land **after** the
roll fires, with the worker's host fix.

---

## 7. What is true of this arm

- Nothing was fired.
- The five chart files are normalized **in this worktree only**, as a working-tree restoration to
  their own blobs. No repo content changed; `git diff` is empty.
- The arm is against `cf9ccf4` with chart `0.4.10`, and the render was produced **after**
  normalization. A render from a tree where those five are CRLF would deploy a different
  ConfigMap and restart the broker.
- The roll moves 17 deployed services to `cf9ccf4` images — including, for the first time in this
  roll series, **real code**: `agent_fleet/cost_agent/*`, `agent_fleet/ontology_service/main.py`
  and `policy/graphs/cost_lot_costing_review.yaml` from the lane/74 merge.
