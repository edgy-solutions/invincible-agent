# Lane 1, 2026-09-26 — the dagster-server image exists, but not at a sha the arm can name

**Status: roll #3 still ARMED, NOT FIRED.** This record answers the read-only image question and
replaces §2's "no sha satisfies the arm today" with something sharper: **the two preconditions are
serial, not parallel.** Precondition 2 is not an independent gate that could be cleared alongside the
merge — the merge is the event that *produces* the image precondition 2 asks for.

Supersedes nothing in
`docs/measurements/2026-09-26-roll-3-armed-leg-11-strict-and-the-two-preconditions-no-sha-satisfies-yet.md`;
it adds the ordering that record could not state because it had not looked at the build trigger.

## 1. The check that was asked for, and its answer

**A `dagster-server` image exists at the current head of `origin/master`.**

| | measured |
|---|---|
| `origin/master` head | `a29d014a` |
| build run at that sha | `36275135347`, event `push`, workflow `completed/success` |
| the job that matters | `Docker · dagster-server` — **success** |
| what success means | `.github/workflows/build-containers.yml` builds with `--push .` (two buildx invocations, both `--push`), tagging `${REGISTRY}/${IMAGE_PREFIX}/${service}:${github.sha}` |
| so the tag is | `ghcr.io/edgy-solutions/invincible-agent/dagster-server:a29d014a…` |

**The workflow's aggregate conclusion was not the claim.** Roll #2's red was an image whose contents
did not follow from the sha the roll named, so the per-job conclusion was read rather than the run's,
and the `--push` was read rather than assumed. A matrix with `fail-fast: false` is exactly the shape
where a green run and a red job can coexist; here they do not, but that had to be measured.

## 2. It does not satisfy precondition 2, and the reason is the trigger

Precondition 2 asks for an image at a sha carrying **both** `2c7b85cf` (engine-f) and `b95ce005` (the
SQLAlchemy pin). `a29d014a` carries the first and not the second.

The new fact:

```
.github/workflows/build-containers.yml
on:
  push:
    branches: [master, main]     # <- lane branches are NOT here
```

- `git branch -a --contains b95ce005` → **`lane/01` and `origin/lane/01` only.**
- `gh run list` over the last 60 runs → **no build run at `b95ce005` at all.**

So **no `dagster-server` image has ever been built at the pin's sha, and none can be while the pin
lives only on a lane branch.** `b95ce005` changes exactly one file,
`.github/docker/Dockerfile.dagster-server` — a build input — so it reaches the cluster only through a
rebuilt image, and the only event that builds one is a push to `master`.

**Therefore: precondition 2 is downstream of precondition 1.** The order is forced —

```
merge b95ce005 to master   (YOURS; the gated action)
  -> push to master fires build-containers.yml at the merge sha
    -> Docker · dagster-server publishes an image at that sha
      -> roll #3's --set global.imageTag=<merge sha> names a real image
```

There is nothing for this lane to do between those steps, and nothing that can be done before the
first one.

## 3. The escape hatch, named so it is not reached for

`workflow_dispatch` is a trigger on this workflow, so a dispatch at `lane/01` **would** publish
`dagster-server:b95ce005` without a merge. **It is a trap here, and the reason is not the image.**

`global.imageTag` is **one value for the whole fleet by construction** (§2 of the armed record). A
roll at `b95ce005` therefore moves *every engine* to `lane/01`'s tree, not just dagster-server —
twenty-odd images swapped to a branch that has had no full-suite run as master, to deliver a
one-file Dockerfile change. The dispatch is available and it should not be used for this; unlike
the check in section 1 it is not a read at all -- it writes a new image into the registry.

## 4. The arm, with the sha slot now stated as a rule

```bash
helm --kube-context <ctx> upgrade iagent helm/invincible-agent -n sandbox \
  --reuse-values \
  -f helm/invincible-agent/values-roll-frontend-digest.yaml \
  --set global.imageTag=<the sha of the MERGE COMMIT that lands b95ce005 on master, once
                          its build-containers.yml run shows `Docker · dagster-server` success> \
  --no-hooks
```

Unchanged in shape from roll #2's arm, which fired green on nine legs. Context lives in the
out-of-repo log.

**Leg 11 strict stands** — the narrow exception-keyed exemption is refused, no exemption is added,
the leg is as written. Recorded again here only so the ordering change above does not read as
re-opening it. The prediction that strict is now plausible, and the two ways it can still red
(including that the risk moves from 11b to **11a**, because the registrar now honestly reports
itself not-Ready during a window it used to report Ready falsely), are unchanged and still
unfired.

## 5. What I did not verify

- **I did not read GHCR's package registry.** This account's token carries
  `gist, read:org, repo, workflow` and **not `read:packages`**, so the registry's own listing was
  not queried. The claim in §1 is therefore one inference step from a first-hand read: build job
  success **plus** `--push` in the workflow text. That inference is the same one
  `--set global.imageTag=<sha>` makes when it asserts an image exists, so it is not a new risk —
  but it is not a registry read and is not recorded as one.
- **I did not verify the image's contents follow from the sha.** That is roll #2's failure mode and
  it is not settleable from CI metadata; it is settled by the roll's own legs.
- **The local `master` is 3 commits ahead of `origin/master` and unpushed** (`3a518695`), so no
  build has run at the local head and no image exists at it. All three are documents and change no
  image input, so this does not affect the arm — but a sha that has never been pushed cannot have an
  image, which is worth stating rather than checking.
