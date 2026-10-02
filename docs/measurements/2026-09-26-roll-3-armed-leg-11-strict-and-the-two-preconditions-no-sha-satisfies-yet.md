# Lane 1, 2026-09-26 — roll #3 armed, leg 11 strict, and the two preconditions no sha satisfies yet

**Status: ARMED, NOT FIRED.** The dispatch said re-arm and do not fire. Nothing was fired, no
`helm upgrade` ran, and the arm below has an **unfilled sha slot** — not because the sha is
unknown, but because **no sha exists yet that satisfies the arm**. That is the finding this record
carries; the rest is the arm that becomes runnable the moment it does.

## 1. The arm

```bash
helm --kube-context <ctx> upgrade iagent helm/invincible-agent -n sandbox \
  --reuse-values \
  -f helm/invincible-agent/values-roll-frontend-digest.yaml \
  --set global.imageTag=<SHA — SEE §2, NO SUCH SHA EXISTS TODAY> \
  --no-hooks
```

Same shape as roll #2's arm, which fired green on nine legs. Context lives in the out-of-repo log.

## 2. The two preconditions, and why one sha cannot satisfy them today

The dispatch asks for roll #3 to carry **engine-f's fix** and **the SQLAlchemy pin**. Measured on
this tree at `bfb33b89`:

| commit | what | in `master`? |
|---|---|---|
| `2c7b85cf` | engine-f's presentations retry; registrar `/health` 503s when bolt is unreachable | **YES** |
| `b95ce005` | `build(dagster-server): pin SQLAlchemy and its DBAPI, and delete a false justification` | **NO** |

`global.imageTag` is **one value by construction** — it pins the whole fleet to a single sha, so
"roll both fixes" means "one sha that contains both". `b95ce005` is the single commit `lane/01`
has that `master` lacks. **So no such sha exists**, and roll #3 cannot be armed as specified until
`b95ce005` is merged to `master`.

**This is not a merge I hold authorization for.** Chris approved *pushing* `b95ce005` to its lane
branch, which was done. Approval to push a branch is not approval to merge it to `master`, and
merging is the gated action. Routed rather than assumed.

### The second precondition, which the merge does NOT satisfy

`b95ce005` changes exactly one file: `.github/docker/Dockerfile.dagster-server`. It is a **build
input, not a chart value**. Merging it puts it in the tree; it reaches the cluster only in a
**rebuilt `dagster-server` image**. So arming roll #3 needs *both*:

1. a `master` sha containing `2c7b85cf` **and** `b95ce005`, and
2. a `dagster-server` image **actually built at that sha** and present in the registry.

Checking (2) before firing is roll #2's own lesson, paid for: §7 of the roll-#2 record is titled
for the unpinned image that took the control plane down, and the failure there was precisely an
image whose contents did not follow from the sha the roll named. `--set global.imageTag=<sha>`
asserts an image exists at that tag; it does not verify one. **Verify the tag resolves before
firing, not after.**

## 3. Leg 11, strict — the architect's call, recorded as an answer to an open question

Roll #2's §8.4 left one decision, in its own words "the architect's call, not mine, and it is the
one decision roll #3 cannot start without": leg 11 reds on an otherwise-healthy fleet, and the
options were (1) block on a registrar fix, (2) a narrow exemption keyed to the exception, or
(3) exempt the pod — already struck as a guard that cannot fire.

**The dispatch says "leg 11 strict". Read as: option 2 is refused, no exemption is added, the leg
stands exactly as specified.** Recorded here as the resolution of that question so the next reader
does not re-open it.

> **Leg 11.** Every deployment reaches Ready, **and** the first 60 seconds of each pod's log carry
> no `Traceback`.

Unchanged from roll #2: the CLEAN / TRACEBACK / **EMPTY-UNDECIDED** partition stands, the undecided
bucket is reported and never folded into the pass, and the matcher gets its positive and negative
control in the same run. A matcher that returns zero because it is broken reads exactly like a
clean fleet.

### Why strict is now plausible where it was not — a prediction, with its mechanism, unverified

Roll #2's leg 11 red was `ConnectionRefusedError [Errno 111]` in the neo4j bolt connect, chained
into `ServiceUnavailable`, **with a uvicorn ASGI frame above it** — four events, 12 lines, all
inside +17s to +21s, none afterwards. The ASGI frame is the tell: it was raised inside a *request
handler*, i.e. something reached the registrar over HTTP while Neo4j was not yet accepting bolt.

`2c7b85cf`'s second half makes the registrar's `/health` return **503 / `"status": "degraded"`**
when bolt is unreachable, where it previously reported `neo4j_reachable: false` in the body and
returned 200 regardless — a guard that ran, was right, and could not be heard, because a kubelet
reads the status code and never the body.

**I checked the consumer rather than assuming it.** `helm/invincible-agent/templates/mesh-registrar.yaml:110-113`
wires `readinessProbe.httpGet.path: /health`. So the 503 does reach a reader: the registrar stays
**out of Service endpoints** until bolt works, nothing reaches it to raise, and the four ASGI
tracebacks should not recur.

**That is a prediction, not a measurement.** It has never been fired, and the mechanism is
indirect — it removes the tracebacks by removing the *traffic*, not by handling the exception at
the raise site. Two ways it can still red, both worth watching for rather than being surprised by:

- **The risk moves from 11b to 11a.** The registrar now *correctly* reports itself not-Ready during
  the bolt window, where it previously reported Ready falsely. Leg 11a requires every deployment at
  full `readyReplicas`. With `initialDelaySeconds: 5` / `periodSeconds: 10` it should recover once
  bolt is up, but **the gate must allow the registrar time to go Ready, or strict leg 11 reds on
  11a for the same startup race that used to red 11b.** A red here is the fix working, not failing.
- **Any other caller on that path.** The fix gates HTTP traffic via readiness; anything that reaches
  Neo4j from the registrar *without* an inbound request would still raise into the log.

## 4. What is not done

- **Not fired.** No `helm upgrade`, no `--dry-run`, no cluster contact of any kind.
- **The sha is unfilled**, per §2. The arm is not runnable and was not made to look runnable.
- **The image at that sha is unverified**, because there is no sha to verify against yet.
- **The merge of `b95ce005` is not mine to make** and was not made.

The one decision roll #3 cannot start without is no longer leg 11's exemption — the dispatch
answered that. It is now the merge in §2, and the rebuild that merge does not by itself produce.
