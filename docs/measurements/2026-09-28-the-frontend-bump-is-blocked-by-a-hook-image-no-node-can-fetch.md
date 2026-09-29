# The frontend bump is blocked by a hook image no node can fetch — and the diff had listed it in plain sight

**Lane:** `invincible-agent/master` · **Ordered:** bump the frontend to `sha256:6f277665…` (tag
`5b559765`), fire, verify `imageID`
**Status:** digest derived, pullability proved, chart change committed `3809d5ab`, **fire BLOCKED at
revision 156 `pending-upgrade`** on a pre-upgrade hook
**Fleet:** unchanged on `ec055c49`; **nothing is down** — the frontend still serves on `c8d6553f`

---

## 1. What was asked, and what of it is done

| step | state |
| --- | --- |
| derive the full digest and tag | ✅ five readings, two controls |
| prove the cluster can pull it | ✅ from a node, 1.814s |
| render check | ✅ full manifest, exactly one image line replaced |
| commit the chart change | ✅ `3809d5ab` |
| fire | ⛔ **blocked** — revision 156 stuck in `pending-upgrade` |
| verify `imageID` | ⛔ **not reached** |

## 2. The order named a file that the roll script does not read

The bump was ordered against `values-roll-frontend-digest.yaml`. That file's `VALUES` membership is
the whole story, and it is recorded in full in commit `3809d5ab` and as **R-085**. In short:
`scripts/upgrade-sandbox.sh`'s `VALUES` array holds `values-sandbox.yaml` and
`values-sandbox.secret.yaml` and nothing else, so the overlay is never passed. **Measured on the
consequence, not inferred from the script**: none of the overlay's four digests is running. So the
bump landed in `values-sandbox.yaml`, whose pin *was* the running digest and is therefore provably
in a live path.

## 3. The digest, derived and never typed

Both the digest and the tag arrived abbreviated, and this registry's tags are the full 40-character
sha — where an abbreviation answers `not found` indistinguishably from not-built and no-access.

| reading | result |
| --- | --- |
| `git rev-parse 5b559765` in cortex-ui | `5b559765d1cc539f47beabba1d54257811616ca0` |
| full tag → digest | `sha256:6f27766587108f5dc7fc9af623b7eae4ecac4a67fd218e7efbd3524918b1d1b4` |
| digest media type | `application/vnd.oci.image.index.v1+json`, `linux/arm64` present |
| **positive control** — abbreviated tag `:5b559765` | `not found` — so a `found` here discriminates |
| `60e245a` at its **full** sha | `not found` — a real negative, not an abbreviation artifact |
| **control** — superseded `6e2fc31d` | still resolves; nothing was deleted, it was overtaken |

`:latest` currently resolves to this same digest — the inverse of what the overlay last measured,
and **a fact with a shelf life, not a reassurance**. With `pullPolicy: Always`, latest agreeing
today is what makes the pin cheap to check, never what makes it unnecessary.

## 4. Pullability proved from the consumer's position

R-082, applied rather than quoted: this is a **different repository** from roll #6's payload, so the
credential was re-proved for it. A pod on the new digest with `ghcr-pull-secret` attached reached
`Succeeded` on `k3s-worker6`, exit 0, **pulled in 1.814s** — and its `imageID` equals the pinned
index digest exactly, which settles the repo-digest-versus-manifest-digest question the overlay had
only argued.

## 5. The render check, twice, and the total that was confounded

At a fixed `imageTag`, committed-versus-working-tree is **4 diff lines**: one image line, nothing
else. Against the **live** manifest at the running fleet sha, **exactly one image line is replaced
and it is the frontend**; no engine image appears on the replaced side, so the fleet stays on
`ec055c49`.

The raw total was 2081 lines and was **partitioned rather than believed**: `helm get manifest` omits
hooks (0 hook annotations live, 21 in the render), so all 11 render-only image lines are hook
resources and the asymmetry is a property of the instrument.

⛔ **And that partition is where this roll was lost.** It was correct about the diff and wrong about
the risk. The eleven render-only image lines were dismissed as "hooks, therefore not drift" — and
one of them is the image that blocked the fire. **The population a fire must prove is every image
the render introduces that is not already running**, not the image the change was about. The list
was in my hand and I filed it as an artifact.

## 6. ⛔ The blocker: `quay.io/minio/mc`, and the cache that was load-bearing

`iagent-minio-bucket-init` is a `pre-install,pre-upgrade` hook at weight `-5`. Its image is
`quay.io/minio/mc:RELEASE.2025-08-13T08-35-41Z`, `imagePullPolicy: IfNotPresent`, and it presents
`ghcr-pull-secret` — a **ghcr** credential — to **quay**. It is in `ImagePullBackOff`, so helm is
waiting on a hook that cannot complete, and revision 156 sits `pending-upgrade`.

### The registry refuses anonymously, and the controls are what prove it

| read | result |
| --- | --- |
| failing tag | `401` |
| **positive control** — `latest` | `401` |
| **negative control** — a tag that cannot exist | `401` |

**Uniform `401` across an existing tag, the failing tag, and an impossible tag is the signature of
repository-level refusal, not tag absence** — a readable repository answers `404` for the third.
Measured on two instruments: a hand-rolled token exchange and `docker buildx imagetools`.

⚠ The first attempt at this reading was **vacuous and nearly written down**: a bare `curl` to
`/v2/…/manifests/…` returns `401` without the bearer-token dance, so the failing tag and the
positive control both answered `401` for a reason that had nothing to do with either. The control is
the only thing that caught it.

### No node holds the image, and that reading needed replacing too

First instrument: `node.status.images` — 0 of 7 nodes list it. **That reading is vacuous**: the list
is capped, at **49 entries** on both nodes checked, so a small image's absence from it means
nothing.

Second instrument, which can answer: a pod pinned to each node, `IfNotPresent`, command `true`.
**`ErrImagePull` 7 of 7.** Positive-controlled in the same breath — the same spec shape with an
image known present on `k3s-worker6` reported *"already present on machine"* and `Succeeded`, so the
probe discriminates on exactly the thing it claims.

### How roll #6 passed ten hours ago is UNDETERMINED, and the conclusion does not need it

Roll #6 reached `deployed` at revision 155, so this same `pre-upgrade` hook succeeded. Either quay's
anonymous access changed since, or the layers were cached then and have since been evicted. **I
cannot distinguish them**: there is no DiskPressure now and no image-GC event, but event retention
is about an hour against a ten-hour interval, so **that absence is vacuous and is not offered as
evidence.** The GC story fits the symptom perfectly and I have nothing that measures it.

What holds under both hypotheses is the finding, and it is **R-087**: under `IfNotPresent`, this
hook's success was evidence about a node's cache and never about the registry. The dependency is
real and unfetchable; the cache was load-bearing and nobody guaranteed it. **A green roll history is
not evidence that the images it used can still be fetched.**

## 7. Why the helm client is being LEFT ALONE, again

`upgrade-sandbox.sh:113-143` documents it and roll #6 measured it: an outside kill leaves the release
`pending-upgrade`, which **refuses the next upgrade**, while helm's own timeout finalizes `failed`,
which an upgrade can proceed from. So the client runs to its own timeout even though the hook can
never succeed. The cost is dead wall-clock; the alternative is a release state whose documented fix
is **editing the release Secret's status field** — `upgrade-sandbox.sh:135-136` is explicit that it is
"NOT a rollback" and points at `docs/plans/helm-release-stuck-pending-upgrade-97.md`. Waiting is
strictly cheaper than that, so waiting is what is happening.

### ⚠ And the wait is 100 minutes, because a guard designed for a long prime has no fast-fail face

`HELM_TIMEOUT` defaults to **`100m`** (`upgrade-sandbox.sh:61`), and the script actively **refuses a
shorter one** unless `ALLOW_SHORT_HELM_TIMEOUT=1` is set, printing "proceeding under protest". That
guard is right about what it was built for: a 51-minute prime was once killed by a ten-minute outer
budget, and the default exists so the client outlives the work.

But it has one face, and this fire is its other case. A hook that **cannot** succeed — no node holds
the image, the registry refuses uniformly — burns the full 100 minutes before the release becomes
proceedable, and **roll #7 is blocked behind that timer**, because a `pending-upgrade` release
refuses the next upgrade. 16 minutes in when this was measured; 84 to go for an outcome already
known.

The asymmetry is the finding: **a long timeout is protection when the work can finish and a penalty
when it cannot**, and the script cannot distinguish those because a stuck pull and a slow prime look
identical from the client. What is cheap and missing is not a shorter default — it is a **pre-flight
pull check on every image the render introduces**, which converts this 100-minute wait into a refusal
before the release is ever touched. Same check as §5's corollary, and it is worth filing for exactly
this reason: it pays twice, once by catching the bad image and once by never entering the wait.

## 7b. The re-fire path, derived — and the hook that `--no-hooks` also skips

`--no-hooks` is not a flag the script knows: there is **no** `no-hooks` match anywhere in
`upgrade-sandbox.sh`. It reaches helm only because line 177 is
`exec helm upgrade … "${ARGS[@]}" "$@"`, so trailing arguments pass through. So the re-fire is the
ordinary script invocation with `--no-hooks` appended — no script change, and nothing bypassed that
the script meant to enforce.

⚠ One derived caveat, and it is not the hook that blocked the fire. `--no-hooks` skips **every**
hook, including the `post-upgrade` reregister job — and `upgrade-sandbox.sh:124-127` records what
that costs: engines keep whatever registration they had, with "a pod age that never changed" as the
only evidence. That is **safe here for a reason that must be stated rather than assumed**: this
payload changes one frontend image and no engine image, so no engine restarts and no registration
goes stale. The same flag on a fire that moved `global.imageTag` would be a silent defect of exactly
the kind the trap was written to catch.

## 8. What I did not do, and what it needs

- **I did not mirror the image.** That is the durable fix — vendor `mc` into a registry the fleet
  authenticates to and pin it by digest — and it needs push rights this seat does not have (the
  token measured during roll #6 lacked `read:packages`, let alone write).
- **I did not add the overlay to `VALUES`.** Three of its pins date from 09-23 and the running
  images have moved past them, so wiring it in now would silently downgrade two dag-tools
  workloads nobody re-verified. Filed as a chart item.
- **I did not change the hook's pull policy or drop the hook.** A digest-only bump does not need
  `minio-bucket-init`, and the overlay's own documented command for exactly this operation carries
  `--no-hooks`. That is the re-fire path once the release finalizes `failed` — named here, not
  taken, because the release is not yet in a state that accepts an upgrade.
- **`imageID` is therefore unverified.** The dispatch asked for it; the fire did not reach the
  frontend workload, so there is nothing to read and no figure is offered.
