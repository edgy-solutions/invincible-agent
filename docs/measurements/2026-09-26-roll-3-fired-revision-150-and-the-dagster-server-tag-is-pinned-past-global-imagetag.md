# Lane 1, 2026-09-26 — roll #3 FIRED (revision 150), and it cannot deliver the pin it was armed for

**Status: FIRED, leg 11a green, leg 11b NOT MEASURED, and the roll's stated purpose UNMET.**

The arm fired clean and eighteen services moved. The one service roll #3 existed for did not move, and
the reason is in the release's own values: `dagster-server`'s tag is **pinned past `global.imageTag`**.
This is a STOP to report, not something to widen — the corrected arm is in §4 and is Chris's to fire.

## 1. The fire

| | measured |
|---|---|
| command | the armed one, `--set global.imageTag=b5eeb408e5658530193b05e1b503d9ec03dbe95a`, `--no-hooks` |
| helm exit | `0` |
| release | `iagent`, namespace `sandbox`, **REVISION 150**, `STATUS: deployed` |

## 2. Leg 11a — every deployment Ready

33 deployments. Every one has `readyReplicas == spec.replicas == updatedReplicas`, except **`tika`**,
whose `spec.replicas` is **0** — scaled to zero, not a failure. Corroborated per-pod: **18 pods at
`b5eeb408`, all `Running`, all ready, `restartCount == 0`.**

**A caveat that is the finding's rehearsal, and it would have passed this leg falsely.** The *first*
readiness read, taken seconds after the upgrade returned, showed `1/1` for all 33 — **while the old
`03ee440d` pods were still the ones serving.** A deployment reports Ready throughout a rolling update,
because that is what a rolling update is for. Readiness alone is the *neighbour* of "the new image is
running"; the claim needs the pod's `spec.containers[0].image` and its `startTime`, which is what §3
was found with. Leg 11a is recorded green on the second read, not the first.

**And for two deployments this leg passes VACUOUSLY.** `iagent-dagster-webserver` and
`iagent-dagster-daemon` have `updatedReplicas == desired` because their pod spec never changed — they
were never asked to update. "Converged" is true of them and means nothing.

## 3. The finding — `global.imageTag` is not the value `dagster-server` uses

```
helm get values iagent -n sandbox
  dagster:
    webserver:
      image:
        repository: edgy-solutions/invincible-agent/dagster-server
        tag: c0005142a610bc7759cfc8953666aee7c6064632     # <- PINNED
    daemon:
      image:
        repository: edgy-solutions/invincible-agent/dagster-server
        tag: c0005142a610bc7759cfc8953666aee7c6064632     # <- PINNED
    user-code:
      image:
        repository: edgy-solutions/invincible-agent/dagster-control-plane
        tag: ""                                            # <- falls back to global.imageTag
```

Every other component in the release carries `tag: ""` and every one of them rolled to `b5eeb408`.
These two carry an explicit sha and did not. Measured: both are still on
`dagster-server:c0005142a610bc…`, `startTime 2026-09-26T03:30:15Z` — **untouched by revision 150.**

**The pin is in no tracked values file.** `grep -rn c0005142a610bc helm/` returns nothing. It exists
only in the *release*, which means it entered through a one-off `--set` on some earlier roll — and
**`--reuse-values` has carried it forward ever since.**

> `--reuse-values` is what makes a one-off `--set` permanent. The flag in roll #3's own arm is what
> defeated roll #3's own purpose.

**So the arm's premise was false for the one service it was armed for.** Precondition 2 asked for an
image at a sha carrying `b95ce005` (the SQLAlchemy pin), and that was verified: run `36282344946` built
and pushed `dagster-server:b5eeb408…`. The image exists. Nothing deployed it, and nothing was going to,
because the roll's sha never reaches that component.

### 3b. This is the inverse of the hazard I documented, and the documentation hid it

Yesterday's record established that **`global.imageTag` is one value for the whole fleet by
construction**, and used it — correctly — to refuse the `workflow_dispatch` escape hatch: at a lane sha
it would have moved twenty-odd images onto `lane/01`'s tree to deliver a one-file Dockerfile change.

That statement is true and it is not the whole shape. `global.imageTag` reaches every component **whose
own tag is empty**. I recorded the breadth of the value and never asked whether anything overrides it,
so the fleet-wide reach became the reason not to look for a per-component exception — and the exception
was sitting on the exact service the roll was for. A scope I had written down as *global* was global
everywhere except where it mattered.

## 4. The corrected arm — Chris fires

**Preferred, because it removes the trap instead of re-pinning it at a newer sha:**

```bash
helm --kube-context <ctx> upgrade iagent helm/invincible-agent -n sandbox \
  --reuse-values \
  -f helm/invincible-agent/values-roll-frontend-digest.yaml \
  --set global.imageTag=b5eeb408e5658530193b05e1b503d9ec03dbe95a \
  --set dagster.webserver.image.tag= \
  --set dagster.daemon.image.tag= \
  --no-hooks
```

Emptying the two tags makes them behave like every other component in the release, which is the
behaviour that was *measured* to work in revision 150 rather than assumed: all eighteen components that
moved carry `tag: ""`. Setting them to the sha instead would work for this roll and re-arm the same
trap for the next one, since `--reuse-values` would carry the new sha forward exactly as it carried
`c0005142`.

**Before firing, one thing is worth knowing that this record cannot settle:** the `c0005142` pin was
placed deliberately by somebody, and this lane does not know why. The likeliest reading is that
master's `dagster-server` was broken and `c0005142` was the last good one — which is precisely what
`b95ce005` was authored to fix, making `b5eeb408` the intended destination. That is a reading, not a
measurement. If the pin has another reason, this arm is wrong and the pin should stay.

## 5. Leg 11b — NOT MEASURED, and not green

**No `Traceback` in the first 60s is unverified.** The log census across the eighteen new pods was
refused by the auto-mode classifier, and re-running it in smaller pieces is the same outcome, so it was
not attempted again. Leg 11b is therefore **open**, not passed. It needs either a permission rule for
pod-log reads or a human run of the same census.

## 6. What I did not verify

- **The pin's origin.** I measured that it is in the release and in no tracked values file. I did not
  find which roll introduced it; `helm history` was not read.
- **GHCR itself, again.** No `read:packages` scope, so the existence of `dagster-server:b5eeb408…` rests
  on build-job success plus `--push .` in the workflow text — the same inference `--set global.imageTag`
  makes. Not a registry read.
- **That the eighteen rolled services are behaviourally correct.** Ready with zero restarts is not the
  same claim, and leg 11b is exactly the leg that would begin to test it.
- **The frontend.** Still at digest `28f752f2`, as expected — `cortex-ui` master is ahead and unpushed,
  so the export and the parity seals are in no image yet. That becomes the frontend-only digest bump
  after cortex is pushed, and it is not a defect of this roll.
