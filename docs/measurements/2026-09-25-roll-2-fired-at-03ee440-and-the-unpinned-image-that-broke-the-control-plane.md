# Lane 1, 2026-09-25 — roll #2 fired at `03ee440`, nine gate legs green, and the unpinned image that took the control plane down

**FIRED. `helm upgrade` rc=0, revision 148, status `deployed`, at
`03ee440dc4118fd78ec8a789fd6c2d83815bf974`, chart `0.4.10`.** The live manifest came back
**byte-identical to the gated render** except the single line already partitioned as an extraction
artefact (§3) — which retroactively validates that partition entry rather than excusing it.

**And it produced one red the gate could not have caught: the Dagster control plane is down with
`ModuleNotFoundError: No module named 'psycopg'`.** Cause measured, not inferred, in §7. It is not
a code change in this repo and not a bad gate leg — it is an *unpinned image*, which is the finding
worth keeping. Ten legs green and the container still cannot start, because **no leg exercised a
container**; see §7's last paragraph.

Three ways a roll can fail to fire, and only one of them is a problem with the roll. The taxonomy
stays because the *purge* now sits in the third row:

| | meaning | this arm | step 3, the purge |
|---|---|---|---|
| **red** | a gate leg failed; the deploy would be wrong | no | no |
| **void** | gate sound, names the wrong sha (`cf9ccf4`) | no | no |
| **blocked** | gate green, subject current, the *actor* was refused | was, then cleared | **yes** |

The fire was **blocked first** and then cleared: Chris authorized it in writing, the auto-mode
permission classifier refused the `helm upgrade`, and it went only when Chris cleared the
permission. `scripts/upgrade-sandbox.sh` would also have deployed and was deliberately **not** used
as a substitute: it bakes in every values file and runs hooks, so it is a *larger* action than the
one gated here, not a safer route to the same one. That distinction is the whole reason the fire
waited rather than finding another road.

This supersedes
`2026-09-24-roll-2-rearmed-at-cf9ccf4-and-the-crlf-that-forged-a-configmap-change.md`, whose arm is
void because `lane/74` moved to `99b56be` after it was written.

---

## 1. The arm

```bash
helm --kube-context <ctx> upgrade iagent helm/invincible-agent -n sandbox \
  --reuse-values \
  -f helm/invincible-agent/values-roll-frontend-digest.yaml \
  --set global.imageTag=03ee440dc4118fd78ec8a789fd6c2d83815bf974 \
  --no-hooks
```

Byte-for-byte the rendered command minus `--dry-run`. Context lives in the out-of-repo log.

`master` moved `cf9ccf4 → 03ee440` by `git push origin master`, three commits: the merge `03ee440`,
`c19f70e` (docs) and `99b56be` (the host identity scrub). The merge was verified **as a merge** —
`git merge-tree --write-tree` plus by-name checks in both directions — not as a two-dot diff, which
on this pair again rendered master's own work as reversals, `values-roll-frontend-digest.yaml`
among them. Read literally, that diff says the merge reverts the digest pinning this roll depends
on. It does not; master is simply not an ancestor of the lane tip (merge-base `b12f0dd`).

## 2. The gate, nine legs

| leg | result |
|---|---|
| CI `Build & Push Container Images` @ arming sha | **completed / success** (run `36090025176`) |
| CI `Release Helm Charts` @ arming sha | **did not run, correctly** — 0 files under `helm/` in the merge |
| …its positive control | `ca23e9e` changed 4 helm files, **ran and succeeded**, published `0.4.10` |
| chart version at the arming sha | **`0.4.10`** — the published one; `appVersion 2026.07.02` |
| 19 built images resolve with `arm64` | **19/19**, 4 platform entries each |
| bogus-sha negative control | **19/19 correctly MISSING**, 0 control failures |
| **byte-equality over `helm/`** (new leg, §5) | **43 tracked files, 0 mismatched** |
| `--dry-run` renders | **rc=0**, empty stderr, 335877 bytes |
| full-manifest diff | **289 lines partitioned to 0 unaccounted** (§3) |
| four sibling digests re-read | **4/4 resolve with `arm64`**; bogus-digest control → `manifest unknown` |
| cluster, post-reboot | **7/7 nodes Ready** |

The 19-image matrix was **re-derived from `.github/workflows/build-containers.yml` at the arming
sha**, not reused from the previous arm's file — and came back identical to it. The population
split still holds: **19 built, 17 deployed** (19 manifest occurrences; `dagster-server` and
`cortex-bff` carry two each). `langgraph-support` and `swarms-scraper` are built and not rendered.

## 3. The manifest diff, and the partition that was wrong on the first cut

289 changed lines. My first pass counted the categories independently and got **290 out of 289**,
with one line matching nothing — which is impossible for a partition and is the whole reason to
add the residual bucket rather than sum the buckets. The cause: `IAGENT_IMAGE_TAG` lines *contain*
the image sha, so two lines were in two categories at once. Re-cut with explicit precedence so
every line lands in exactly one bucket:

| category | lines |
|---|---|
| `IAGENT_IMAGE_TAG` | 2 |
| engine `image:` lines, `c0005142…` → `03ee440d…` | 38 (19 occurrences × 2) |
| `helm.sh/chart: invincible-agent-0.4.6` → `-0.4.10` | 236 (118 × 2, uniform — no third value) |
| cross-repo images, `:latest` → `@sha256:` pin | 12 |
| extraction boundary: one trailing blank line | 1 |
| **UNACCOUNTED** | **0** |
| **total** | **289** |

Symmetry check, which a bucket count alone does not give: **19 engine occurrences on the live side
and 19 on the new side.** No service image appears or disappears; every one of them moves.

`checksum/broker-code` is **absent** from this table. That is the point of the previous arm's §2:
a CRLF working tree had been forging a ConfigMap change and a broker pod restart.

## 4. The four sibling pins

Re-read immediately before the fire attempt, all four resolve as arm64-bearing indexes:

| image | pinned digest | moves? |
|---|---|---|
| `dag-tools/central-gateway` | `c05e0131…` | no — live is `:latest`, pin equals what runs |
| `dag-tools/user-deployment` | `70092098…` | no (2 occurrences) |
| `pub-tools` | `ed93f7b1…` | no (2 occurrences) |
| `cortex-ui/frontend` | `28f752f2…` | **yes, intended** — live manifest carries `c8d6553f…` |

The negative control shares the subject's repository: a zeroed digest on `pub-tools` answers
`manifest unknown`, so "resolves" is being read from a registry that can also say no.

## 5. The byte-equality leg, promoted from proposal to gate

The previous arm proposed it; this one runs it as a first-class leg:

> For every tracked file under `helm/`, assert `sha256(on-disk) == sha256(git blob)`. Refuse to
> render on mismatch, naming the files.

**43 tracked, 0 mismatched.** Corroborated independently by the render itself: the raw `--dry-run`
stdout carries **0 CR bytes**, against 2342 before the normalization. The reboot did not
reintroduce them. The leg is still **uncommitted**, because any commit moves `master` off the
arming sha and re-triggers the 19-image build — it lands after the roll.

Two instrument rules this leg exists to enforce, both learned the hard way:

- Compare **bytes**, never `git status`. `core.autocrlf=input` normalizes CRLF→LF in the clean
  filter used for comparison, so a CRLF working file reads clean forever. No `.gitattributes`
  setting surfaces it either; `eol=lf` governs checkout, not a later editor rewrite.
- Never extract a render with msys `sed` — it silently strips every CR, which is what made the
  flagship leg blind. The extractor here reads and writes binary (`scratchpad/extract.py`).

## 6. What firing would change, and what is not done

92 commits separate the live tag from the arming sha, but the engine payload is nine source files:

```
agent_fleet/cost_agent/instances.py            agent_fleet/graph_host/identity_scrub.py
agent_fleet/cost_agent/main.py                 agent_fleet/graph_host/main.py
agent_fleet/ontology_service/main.py           agent_fleet/presentation_agent/capabilities.py
agent_fleet/presentation_agent/main.py         src/iagent_pure/slot_disposition.py
                                               src/iagent_pure/walk_census.py
```

`graph_host/identity_scrub.py` + `main.py` are lane/74's host fix: the caller JWT stops reaching
the checkpoint store. **That is why the purge is ordered after the roll** — clearing the three
checkpoint tables while the old image still writes tokens would refill them.

Status after the fire:

- **the fire** — **done.** rc=0, revision 148, `deployed`. Verified twice over: the post-deploy
  manifest is byte-identical to the gated render but for the one extraction line, and the frontend
  digest is read from `imageID` (the bytes actually running) rather than from `.spec`:
  requested `sha256:28f752f2111b760c…` == running `sha256:28f752f2111b760c…`. `/version.json`
  answers `cortex-ui`, `git_sha a6950b25…`, built `2026-09-24T02:25:27Z`. Served by
  `iagent-cortex-ui`; my first probe guessed the service name `iagent-frontend` and got
  `Name or service not known` — **my instrument, not a finding**, recorded so the NXDOMAIN is never
  read as a dead frontend.
- **step 3, the purge** — **BLOCKED, and nothing was deleted.** Option B (`checkpoints`,
  `checkpoint_blobs`, `checkpoint_writes`; leave `checkpoint_migrations`). Authorized by Chris in
  writing, which resolves the conflict 74 was holding on; the `DELETE` was refused by the auto-mode
  classifier as `[Cloud Storage Mass Delete]`. The transaction never ran, so the before-counts
  below are also the current counts. **I did not batch the delete into smaller chunks to slip under
  the classifier** — that is routing around the denial's intent, not a safer method, and the
  distinction is the same one that kept `upgrade-sandbox.sh` out of the fire.

  | table | rows | disposition |
  |---|---|---|
  | `public.checkpoints` | 30 | to clear |
  | `public.checkpoint_blobs` | 41 | to clear |
  | `public.checkpoint_writes` | 66 | to clear |
  | `public.checkpoint_migrations` | 10 | **KEEP** — and it is the positive control |

  Two things were established before the delete was attempted, and they survive the block:
  **the premise** — `iagent-engine-lg` runs `graph-host:03ee440…` and is ready, so the writer
  carrying `identity_scrub.py` is live and a cleared table will not refill with tokens; and
  **the scope** — these four tables exist in exactly one database (`iagent.public`); `postgres` and
  `datahub` hold none. That matters because *a purge verified in the wrong database returns 0 for
  the wrong reason*, and `checkpoint_migrations` staying at 10 is what distinguishes "the three are
  empty" from "I am querying nothing". Counts only were read; **no blob contents were selected**,
  per the standing refusal to reproduce the stored bearer tokens.
- **step 4, the backfill** per `docs/runbooks/backfilling-the-vector-space.md` — **step 0 green,
  the rest gated.** The script is proved *in this tree at `03ee440d`*: `verify_self` 1,
  `retrievable` 0, `--list-walked` 3, `git status --porcelain` empty. The runbook's own positive
  control discriminates — at `7ac0765~1` the same patterns answer 1 / 0, inverted — so the zero is
  a real absence and not a broken matcher. **What gates the rest is the runbook's fleet-silence
  stop condition**, which prints the two crashlooping dagster pods: 41 of 43 pods ready, and the
  two that are not are both `dagster-server:03ee440`. So §7 is not a side quest; it is step 4's
  precondition.
- **step 5, the suite**, once, alone. The reboot precondition is **met** (LastBoot
  2026-09-24T22:31:30, was 08/28 with 27.4 days' uptime). Re-measure memory immediately before
  running, per the order — the reading below is from before the fire and is not a substitute:
  physical free 1530 MB / 4.7%, load 95%, commit in use 42718 MB of a 64982 MB limit, 22263 MB
  available.

Step 2, the S3 refresh, is **already done and sealed green** — it ran before this order arrived, in
the prime-then-roll direction, which is the correct one: engines re-register only at startup, so
the roll's restart is what publishes the primed state. It is written up separately. It will be
**re-verified, not re-put**, after the roll: a re-put fires `ontology_sensor` automatically and the
Jena leg is a Graph Store Protocol POST, which appends.

**One correction to that plan, caused by §7:** with the daemon down, `ontology_sensor` **cannot**
fire at all. The re-put hazard is therefore currently inert — and so is every schedule and sensor in
the fleet. That is a reason to fix §7 before anything expects Dagster to act, not a reason to relax
the no-re-put rule, which holds whenever the daemon returns.

---

## 7. The one red the fire produced: an unpinned image, not a code change

`iagent-dagster-daemon` and the new `iagent-dagster-webserver` pod are both **CrashLoopBackOff, 6
restarts**, on `dagster-server:03ee440…`. The **old** webserver replica, still up on
`dagster-server:c0005142…`, serves fine — so the two images are the experiment, and the old one is
the control.

The traceback's last frames, which are the whole diagnosis:

```
File ".../sqlalchemy/engine/create.py", line 602, in create_engine
File ".../sqlalchemy/dialects/postgresql/psycopg.py", line 497, in import_dbapi
  import psycopg
ModuleNotFoundError: No module named 'psycopg'
```

**I did not accept a cause that merely fit.** The frame is `dialects/postgresql/psycopg.py` — the
*psycopg3* dialect — which says what resolved, not just what was missing. The version delta then
names why:

| package | old `c0005142` (works) | new `03ee440` (crashes) |
|---|---|---|
| `dagster` / `dagster-postgres` | 1.13.23 / 0.29.23 | 1.13.24 / 0.29.24 |
| `psycopg2-binary` | 2.9.13 | **2.9.13 — unchanged, still present** |
| `SQLAlchemy` | **2.0.54** | **2.1.0** |

`psycopg2-binary` is installed in **both**, so **nothing was dropped** — the tempting story
("a dependency went missing") is wrong. SQLAlchemy 2.1 changed which DBAPI a bare `postgresql://`
URL resolves to, from psycopg2 to psycopg3. The image carries the driver it always carried; the
library stopped asking for it.

**Neither `.github/docker/Dockerfile.dagster-server` nor `.github/workflows/build-containers.yml`
changed between the two shas** — verified byte-identical. No commit in this repo caused this.

### The finding worth keeping: the Dockerfile's justification is false, and load-bearing

```
# Install latest dagster ecosystem — the user-code image
# (dagster-control-plane) doesn't pin dagster in iagent's
# pyproject.toml ... so we MUST match by also not pinning,
RUN pip install --no-cache-dir dagster dagster-webserver dagster-postgres dagster-graphql
```

The user-code image **is** pinned. It builds with `uv sync --locked`, and `uv.lock` fixes
`dagster` at **1.12.20**:

| image | resolution | dagster | SQLAlchemy |
|---|---|---|---|
| `dagster-control-plane` (user code) | `uv sync --locked` → **pinned** | **1.12.20** | 2.0.48 |
| `dagster-server`, old, works | `pip install`, **unpinned** | 1.13.23 | 2.0.54 |
| `dagster-server`, new, crashes | `pip install`, **unpinned** | 1.13.24 | **2.1.0** |

So the unpinning never produced the match it was written to produce: the *working* pair was already
a full minor apart (1.13.23 server against 1.12.20 user code). The comment describes a mechanism
that has not been true for as long as `uv.lock` has pinned dagster — **a stale justification, which
reads as a considered decision precisely because it explains itself**. It has been quietly
converting every rebuild into a dice roll, and this time the dice came up SQLAlchemy 2.1.

The general form, which belongs in the fleet's rules: **an image does not belong to a sha when its
dependencies are unpinned.** The tag says `03ee440`; the bytes say *whatever PyPI served at build
time*. Two builds of the identical Dockerfile at the identical commit are not the same artefact, so
`global.imageTag` is telling the truth about provenance and lying about content.

### Why nine green legs missed it

Every leg asked whether the right *bytes* would be deployed — that images resolve, that digests
match, that the render is what the diff says. **Not one leg started a container.** That is a real
gap and not hindsight: the gate's own claim is "the roll would deploy something wrong", and it was
right — it deployed exactly what was asked for. A cheap eleventh leg would close most of it: for
each image the roll moves, `docker run --rm <img> python -c 'import <entrypoint deps>'`, or simply
require the previous roll's pods to have reached Ready before the next arm is called green.

### Remedies, ranked — and none fired

1. **Surgical, no rebuild.** Pin the two components back via the chart's own documented escape
   hatch, which `values.yaml:16` describes for exactly this ("a hotfix under test"). The helper's
   precedence was read, not assumed: `$tag := .tag | default (global.imageTag …)`, so a component
   tag **wins over** `global.imageTag`, leaving the other 17 images at `03ee440`.
   `--set dagster.webserver.image.tag=c0005142… --set dagster.daemon.image.tag=c0005142…`
2. **Durable.** Add `psycopg[binary]` to the `pip install`, or pin `sqlalchemy<2.1`, or — best, and
   what the comment was *trying* to do — pin the ecosystem to what `uv.lock` resolves. Any of these
   needs a CI rebuild and therefore a new sha and a **second fleet roll**.
3. **`helm rollback` — wrong, and named so it is not reached for.** It would undo `graph_host`'s
   JWT fix, which is live and is the thing step 3's purge depends on.

**None of these was fired.** (1) is another `helm upgrade`, which is not covered by the
authorization Chris gave for *this* arm, and (2) moves the fleet off the sha he named. The
control plane being down blocks step 4 but not step 3, and step 3 is blocked on its own permission.
So this stops here and goes in the morning report.
