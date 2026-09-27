# Lane 1, 2026-09-26 — roll #3's two preconditions are both satisfied at `b5eeb408`

**Status: roll #3 ARMED and now FIREABLE. Not fired — Chris fires.** This closes the ordering
recorded in
`docs/measurements/2026-09-26-the-dagster-server-image-exists-but-not-at-a-sha-that-satisfies-the-arm.md`,
which found the two preconditions **serial rather than parallel**: the merge is the event that
*produces* the image precondition 2 asks for. The merge has happened, the build ran at the merge sha,
and the job that matters is green.

## 1. Precondition 1 — the pin is on master

| | measured |
|---|---|
| merge commit | `b5eeb408` (`a29d014a..b5eeb408`, pushed) |
| `2c7b85cf` (engine-f) an ancestor of `b5eeb408` | **yes** (`git merge-base --is-ancestor`) |
| `b95ce005` (the SQLAlchemy pin) an ancestor of `b5eeb408` | **yes** |

Both by ancestry, which is the form the precondition was stated in — not by `git log` reading, and not
by the branch the pin was authored on.

## 2. Precondition 2 — an image exists at that sha

| | measured |
|---|---|
| build run at `b5eeb408` | `36282344946`, event `push`, workflow `success` |
| **the job that matters** | `Docker · dagster-server` — **success** |
| read at | job level, via `gh run view --json jobs`, not the run's aggregate conclusion |
| so the tag is | `ghcr.io/edgy-solutions/invincible-agent/dagster-server:b5eeb408…` |

**Read at the job, again, and for the stated reason.** `build-containers.yml`'s matrix is
`fail-fast: false`, so a green run and a red job can coexist; the run's aggregate `success` is the
*neighbour* of "the dagster-server image exists", not the claim. Here they agree, but that had to be
measured rather than inferred, and roll #2's red was precisely an image that did not follow from the
sha the roll named.

## 3. The arm, with the sha slot filled

```bash
helm --kube-context <ctx> upgrade iagent helm/invincible-agent -n sandbox \
  --reuse-values \
  -f helm/invincible-agent/values-roll-frontend-digest.yaml \
  --set global.imageTag=b5eeb408e5658530193b05e1b503d9ec03dbe95a \
  --no-hooks
```

Unchanged in shape from roll #2's arm, which fired green on nine legs. Context lives in the
out-of-repo log.

`global.imageTag` is one value for the whole fleet by construction, so this sha moves **every**
engine — which is now harmless and was the whole argument against the `workflow_dispatch` escape
hatch: at a lane sha it would have moved twenty-odd images onto `lane/01`'s tree to deliver a one-file
Dockerfile change. The dispatch was available, was named so it would not be reached for, and was not
used.

**Leg 11 strict stands** — the narrow exception-keyed exemption is refused, no exemption is added, the
leg is as written. The two ways it can still red are unchanged and still unfired, including that the
risk moves from 11b to **11a**, because the registrar now honestly reports itself not-Ready during a
window in which it used to report Ready falsely.

## 4. Owed on the fire, so it is not forgotten at the moment it becomes payable

**The fleet sha beside the payload, with its derivation named** — owed to the cortex peer for four
rounds, open on their ledger as well as this one. It becomes payable the moment this arm fires and it
is not payable before. The derivation to state then: `global.imageTag` as set above, which is the
merge sha `b5eeb408`, which is the sha the image was built at — one value, three descriptions of the
same thing.

Also queued behind the fire: the three-fire census on the four docs rows, with the pool leg live for
the first time.

## 5. What I did not verify

- **I still did not read GHCR's package registry.** This account's token carries
  `gist, read:org, repo, workflow` and **not `read:packages`**, so the registry's own listing was
  never queried, at either sha. The claim in §2 is one inference step from a first-hand read: job
  success **plus** `--push .` in the workflow text. That is the same inference
  `--set global.imageTag=<sha>` itself makes, so it is not a new risk — but it is not a registry read
  and is not recorded as one.
- **I did not verify the image's contents follow from the sha.** That is roll #2's failure mode, it is
  not settleable from CI metadata, and it is what the roll's own legs settle.
