# Lane 1, 2026-09-26 — the next roll ARMED at `55dc8614`, carrying the docs pool fix and the menu producer half

**Status: ARMED, NOT FIRED.** The order says "do not fire" and nothing here was fired. One
precondition is **open at the time of arming** and is stated as checkable rather than assumed.

    payload sha   d4a00598   (items 2 and 3 -- the code)
    roll sha      55dc8614   (head; what `global.imageTag` would become)
    fleet sha     b5eeb408e5658530193b05e1b503d9ec03dbe95a   (what is deployed NOW)
    helm          revision 152, deployed

---

## 0. ⚠ THE ORDER SAYS "ROLL #4", AND ROLL #4 HAS ALREADY FIRED

The order reads *"Arm roll #4 at head with 2–3."* **Roll #4 fired at helm revision 151**
(`1c1005c2`, the dagster-server pin retirement) and is written up in
`2026-09-26-roll-4-retires-the-dagster-server-pin-and-the-control-plane-is-now-at-b5eeb408.md`.
Measured lineage:

    150   roll #3            Sat Sep 26 20:10
    151   roll #4            Sat Sep 26 21:55
    152   frontend bump      Sat Sep 26 23:34   <- item 1, this session, not a numbered fleet roll

Items 2 and 3 **cannot ride roll #4**: they did not exist when it fired. So the number in the order
is a label that slipped by one, and this is armed as **roll #5** — the next numbered fleet roll.

**The substance of the order is unambiguous either way** (arm the next roll, at head, carrying items
2–3, with the fleet sha beside the payload, and do not fire), so this was not treated as a blocker.
⚠ **If "#4" meant something other than the next fleet roll, this arm is mislabelled and only the
label is wrong** — the sha, the payload and the gate are unaffected. Confirm the label when
convenient.

---

## 1. The payload — what this roll would put on the cluster

Everything in `d4a00598`, reached via `global.imageTag=55dc8614…`.

| item | engine | change |
| --- | --- | --- |
| **2** | **engine-o** (`ontology_service`) | the cold-start fallback spans MESH; response shapes are never offered as subjects (two roots); the productive-option gate records when it stands down |
| **3** | **engine-f** (`presentation_agent`) | `sub_query` + `accepted_slots` on every option-bearing card, from **both** producers |

**Two engines move behaviourally; the rest move only by tag.** That matters for what the roll must
verify — §5.

## 2. ⛔ PRECONDITION, OPEN AT ARMING: the image for `55dc8614` did not exist yet

`--set global.imageTag=<sha>` is a **claim that images at that tag exist**, and it fails as
`ImagePullBackOff` rather than as a helm error. Measured at arming:

    55dc8614   Build & Push Container Images   queued -> in_progress
    55dc8614   Release Helm Charts             completed/FAILURE

**Do not fire until `Build & Push Container Images` is `completed/success` at `55dc8614`.** It was
still `in_progress` when this was written.

**The `Release Helm Charts` failure does NOT block this roll**, and the reason is checkable rather
than reassuring: the roll deploys the **local chart directory** `helm/invincible-agent`, never a
released chart. The same job also failed at `1c1005c2`, which rolled fine as roll #4 — so it is
pre-existing and orthogonal. It is someone's defect; it is not this roll's gate.

⚠ **Carried unchanged from rolls #3 and #4:** this account's token has no `read:packages`, so "the
image exists" still rests on the build job succeeding plus `--push .` in the workflow text. **It is
not a registry read.** The one exception is the frontend, which is cross-repo and *was* read
first-hand from GHCR (item 1).

## 3. The command, and the two `-f` files it must and must not carry

```bash
helm upgrade iagent helm/invincible-agent -n sandbox --kube-context <ctx> \
  --reuse-values \
  -f helm/invincible-agent/values-roll-frontend-digest.yaml \
  --set global.imageTag=55dc8614… \
  --no-hooks --timeout 20m
```

**`values-roll-frontend-digest.yaml` STAYS**, and not on habit — it pins the frontend and the three
cross-repo siblings, none of which `global.imageTag` reaches (`$ours` is false for them, so they fall
through to `latest`). `latest` is a floor that moves.

**`values-retire-dagster-server-pin.yaml` IS DELETED IN THIS COMMIT, and its condition was verified
first-hand, not inherited.** The file says it becomes redundant once the release holds `tag: ""` for
both keys. Read off the **live release at revision 152**:

    dagster.webserver.image.tag = ''
    dagster.daemon.image.tag    = ''

So it asserts nothing the release does not already hold, and roll #4's report says the next hand
should delete it rather than pass it on habit. Deleted. **Passing it would be harmless; keeping it
would be the thing that rots**, because a file that asserts a state already reached is indistinguishable
from one still holding that state open.

**Also verified at 152, because `--reuse-values` is what carries them forward:**

    cortexUi.image.digest = sha256:6e2fc31d…   <- item 1's bump is IN the release values
    global.imageTag       = b5eeb408…          <- the fleet sha, unmoved by the frontend bump

That last line is the "fleet sha beside the payload" the order asked for: **`b5eeb408` -> `55dc8614`**
is the whole of what this roll changes for the ~20 in-repo services.

## 4. The gate before firing — the manifest, not the image lines

Same gate as rolls #3 and #4, for the same measured reason: `-f values-sandbox.yaml` would re-assert
`DATAHUB_TOKEN: ""` over the live token, and **an image-line diff cannot see that.** So:

1. `helm get manifest iagent` -> before
2. the same command with `--dry-run` -> after
3. diff the **whole** manifest, and assert mechanically rather than by eye

**Expected, and it should be asserted as an equality, not scanned:** every `$ours` image tag moves
`b5eeb408…` -> `55dc8614…`, the frontend stays at `6e2fc31d`, the three siblings stay at their pinned
digests, and **`DATAHUB_TOKEN` does not appear in the diff at all.** Anything else is a stop.

## 5. ⛔ The legs — and why leg 11 is NOT the check that matters for this payload

**Leg 11 strict** stands as specified: every deployment Ready, **and** no `Traceback` in each pod's
first 60 seconds, CLEAN / TRACEBACK / **EMPTY-UNDECIDED**, undecided never folded into the pass, and
the matcher positive- and negative-controlled **in the same run** — because a matcher returning zero
because it is broken reads exactly like a clean fleet.

⚠ **Leg 11b is still open fleet-wide** from roll #3's classifier denial on an eighteen-pod log
census. Item 1 ran it on one pod and that is not the census. It needs a permission rule for pod-log
reads or a human run.

**And leg 11 cannot see this payload.** Both changes are *content-level authorization and routing*
behaviour: a pod that starts cleanly proves nothing about whether the docs walk now draws, or whether
a menu can be answered. The behavioural checks are:

| what | how |
| --- | --- |
| item 2 landed | the **docs census** rows, which are `0 pass, 4 fail` at `b5eeb408` |
| item 2's mechanism | `/resolve` on a DOCS caller returns a pool containing `mesh:DocPage` and **no** `mesh:Response` subclass |
| item 3 landed | a refusal menu card carries `sub_query`; an option pick re-routes with the slot bound |
| the gate stood down honestly | `_gate_excluded` shows `disposal: retained` only where the pool would have emptied |

## 6. ⛔ THE SOURCE-VS-DEPLOYED TRAP, WRITTEN DOWN BEFORE ANYONE FALLS IN IT

**Nothing is rolled. The fleet is `b5eeb408`.** A docs census fired right now still exercises the
**old** engine-o, and its baseline is `0 pass, 4 fail`, rc=1, byte-identical across three fires.

**A still-red docs census before this roll fires is NOT evidence the fix failed.** It is evidence the
fix is not deployed, which is already known. The census only becomes a measurement of item 2 **after**
`global.imageTag` reaches `55dc8614` and engine-o restarts.

The same trap in the other direction: **engines re-register only at startup**, and `--no-hooks` skips
prime and re-register. If the docs walk still misses after the roll, the first thing to check is
whether engine-o actually restarted and re-registered — not the new SPARQL.

## 7. What I did not verify

* **That `55dc8614`'s images exist.** §2 — the build was `in_progress`. This is the arm's one open
  precondition and the reason it is armed rather than fired.
* **That the docs fix works on the cluster.** It is sealed in-repo and mutation-proven. §6: it cannot
  be measured against a fleet that does not have it.
* **The `Release Helm Charts` failure's cause.** Established only that it is pre-existing (`1c1005c2`
  failed the same job and rolled fine) and that this roll does not consume its output.
* **Whether the label should read #4 or #5.** §0. The lineage is measured; the intent behind the
  number is not mine to assert.
* **That the roll's blast radius is only the two engines.** Every `$ours` image moves tag, so every
  in-repo service restarts. Only two change *behaviourally* in this payload, but "restarts" is a
  bigger set than "changes", and rolls #2 and #3 both found that the difference has teeth.
