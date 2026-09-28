# Lane 1, 2026-09-28 — roll #6 FIRED and is BLOCKED: the cluster cannot authenticate to ghcr, whose packages are public

**Lane:** `invincible-agent/master` · **Item:** overnight dispatch 5 · **Status:** FIRED, **BLOCKED, NOT LANDED** · **fleet NOT degraded**

Roll #6 fired at 09:45:06 with the derived payload sha and every gate satisfied. It cannot land. The
cause is not in the payload, the chart, or the roll — **every node in the sandbox is refused by ghcr,
for packages that allow anonymous pulls.**

---

## The one-line state

| what | reading |
| --- | --- |
| helm release | `iagent`, **`pending-upgrade`**, LAST DEPLOYED 09:45:06 |
| blocking hook | `iagent-prime-substrate-xx2th`, `Init:ErrImagePull` |
| new pods | **20 on `ec055c49…`, all ImagePullBackOff, none Ready** |
| **old pods** | **19 on `55dc8614…`, all `Ready=true`** |
| **is anything down?** | **No — measured across EVERY deployment in the namespace**, not inferred from the 19: none has zero ready replicas except `tika`, which is `0/0` by desire. The rolling update is holding the old replicas because the new ones never pass readiness |

**That last row started as an inference and was turned into a measurement.** The first draft said
"no outage" on the strength of 19 `invincible-agent/*` pods being Ready — the same filter that had
already hidden `cortex-ui` and `central-gateway` from the leg 11a baseline. Two rows above in this very
table. A claim of "nothing is down" is an absence assertion over **every** workload, so its population
is the deployment list, not the subset my grep happened to name.

**The fleet is serving normally on roll #5's sha.** That is the fact to lead with: this is a roll that
did not land, not an outage.

---

## The error, as the kubelet states it

```
failed to resolve reference "ghcr.io/edgy-solutions/invincible-agent/dagster-control-plane:ec055c49…":
failed to authorize: failed to fetch oauth token: unexpected status from GET request to
https://ghcr.io/token?scope=repository%3A…%3Apull&service=ghcr.io: 403 Forbidden
```

**403 on the token endpoint** — an authorization failure, not a missing tag.

---

## ⛔ THE DISCRIMINATION THAT CHANGES THE FIX: the packages are PUBLIC

```
curl "https://ghcr.io/token?scope=repository:edgy-solutions/invincible-agent/cortex-bff:pull&service=ghcr.io"   → token, 88 chars
curl -H "Authorization: Bearer <that>" https://ghcr.io/v2/…/cortex-bff/manifests/ec055c49…               → HTTP 200
```

**An unauthenticated client can pull this image right now.** So the cluster is not being denied because
the image is private. It is **presenting a credential that ghcr rejects**, and ghcr answers a bad
credential with 403 rather than falling back to the anonymous access that would have succeeded.

**A stale pull secret is therefore strictly worse here than no pull secret at all.** That inverts the
usual remediation: the first thing to try is removing the credential, not renewing it.

| the secret | reading |
| --- | --- |
| name | `ghcr-pull-secret`, type `kubernetes.io/dockerconfigjson` |
| created | **2026-05-31** — about four months old |
| referenced from | `values-sandbox.yaml:21-22` and `values.yaml:44-45`, fleet wide |
| contents | **not read, not printed, not reproduced** |

It worked for roll #5 yesterday at 11:28, which pulled a brand-new sha and succeeded, and it fails
now. An expiring token fits that shape exactly. **I did not read the credential, so expiry is the
likely cause and not a measured one** — the distinction matters because the remediation differs.

---

## ⛔ MY GATE VERIFIED THE REGISTRY FROM THE WRONG CREDENTIALS

The gate said: *"A green build job is the producer's claim about the registry, not a read of it — so
the image is confirmed by reading the registry."* I did read the registry. **I read it as me.**

`docker manifest inspect` from this workstation answered a question about **my** docker credentials.
The consumer is **the kubelet**, with a different identity, and nothing in the gate ever asked whether
*it* could pull. The reading was true and answered the wrong question — a census through a helper is a
claim about the helper.

The sharper version: **image existence and image pullability are different properties, and I had
carefully verified only the first.** Roll #5 taught the fleet to distinguish a build's claim from a
registry read, and I applied that lesson one step short of the consumer.

**What the gate needed was a cluster-side pull test** — a throwaway pod on the sandbox pulling one
payload tag — which costs seconds and would have failed *before* the release went to
`pending-upgrade`. Someone else reached the same conclusion independently while this roll was
blocked: a `ghcr-pulltest` pod pulled successfully at 09:47 and was deleted before I could read its
spec, so **I cannot say what credential it used** and do not claim it as my control.

### And a second sample that was not a population

I verified three images — the payload services — because the items named three engines. But
`global.imageTag` is **fleet wide**: it retagged all 19 workloads, including `dagster-control-plane`,
which is what the blocking hook runs. The census afterwards found all 19 present, so this did not
cause the failure; it was still an unearned pass. **The scope of the flag, not the scope of the
change, determines the population to verify.**

---

## The failures I first called "NOT this one" — and they ARE this one

`iagent-dag-tools` (`dag-tools/user-deployment:latest`), `iagent-pub-tools-broker` (`pub-tools:latest`),
`doc-tools`, `iagent-cortex-ui` and `iagent-central-gateway` are also in ImagePullBackOff, and none of
them is affected by `global.imageTag` — different repositories, unchanged tags. My first reading was
that these were a separate, already-known problem, and I reached for the recorded explanation:
`values-roll-frontend-digest.yaml:137` predicts in writing *"A roll restarts pods. With `:latest` +
`Always` and `:latest` already moved…"*, which fits the shape exactly.

**It is the wrong explanation, and I checked instead of using it.** Measured:

| reading | result |
| --- | --- |
| the error on `doc-tools`, `cortex-ui`, `dag-tools-broker` | **`403 Forbidden`** — the same one |
| all 19 payload packages, anonymous | **19/19 → HTTP 200** |
| `dag-tools/user-deployment:latest`, `pub-tools:latest`, `doc-tools:latest`, anonymous | **all HTTP 200** |
| nodes involved | worker1, worker2, worker3, worker6 — **not one node** |
| node reboots / `NodeNotReady` | **none**; node objects date from 2024 |

**One root cause for every ImagePullBackOff in the namespace**, and because every package is
anonymously pullable, remediation option 1 should clear all of them, not only the payload.

⛔ **A recorded hazard fitted the symptom and was still the wrong cause.** The `:latest`-has-moved
note is true, load-bearing, and about these very workloads — which is exactly what made it dangerous:
it is pre-authenticated. Had I accepted it, I would have filed a correct-sounding second finding and
left the actual cause undiagnosed. **A justification that fits by construction fits a symptom it did
not cause.**

### And I cannot say who restarted them

Those pods are **14m old**, coincident with the fire at 09:45:06 — so "pre-existing", which this
document said in its first draft, is contradicted by the ages. But `doc-tools` is a **separate helm
release** (`doc-tools`, rev 17) that my upgrade does not touch, so my roll cannot explain it either.
A `ghcr-pulltest` pod ran at 09:47 and was deleted, so **another operator was debugging this at the
same minute**, plausibly deleting pods to force re-pulls. **Attribution is undetermined and left that
way** — the roll and someone else's debugging occupy the same two minutes, and nothing I can read
separates them.

⛔ **My leg 11a baseline could not have seen them.** It filtered on `invincible-agent` in the image
path, so the two workloads served from other repositories were excluded **by construction** — the
filter let in exactly what I expected to find. `doc-tools`, `iagent-central-gateway` and
`iagent-cortex-ui` are in the same position. A baseline whose filter is drawn around the expected
answer cannot report a surprise outside it.

---

## Why the helm client is being LEFT ALONE

`upgrade-sandbox.sh:113-143` documents the killed-client trap: an outside kill leaves the release
`pending-upgrade` so the **next upgrade is refused**, and every hook scheduled after the long one is
never created. Helm's own timeout is `100m` (started 09:45, so ~11:25) and reaching it marks the
release **failed**, which a subsequent upgrade can proceed from.

**So the background client is not being interrupted.** Letting it time out is the recoverable
outcome; killing it is the wedged one. This is the script's own documented hazard being obeyed rather
than rediscovered.

**And the wait is headroom, not loss.** The pulls are in backoff and will retry. **If the credential
is fixed before ~11:25, this roll completes on its own** with no second fire.

---

## What a human has to do — diagnosed here, not executed

The live credential write is not mine to make. In preference order:

1. **Delete the stale secret and let the anonymous path serve**, since the packages are public:
   `kubectl -n sandbox delete secret ghcr-pull-secret`. Cheapest, and **measured from a node** (below),
   not inferred. It leaves the chart referencing a missing secret, which kubelet tolerates.
   **This one is not reversible by me** — I cannot reconstruct a credential I have never read, so if
   the secret is wanted back it has to be re-created from the PAT, not restored by me.
2. **Rotate it** with a PAT carrying `read:packages`, if any payload package is ever private.
3. Confirm with a throwaway pull of `…/cortex-bff:ec055c49…` on the sandbox **before** re-firing.

Worth knowing: my own `gh` token also lacks `read:packages`, which is a separate matter from the
cluster's and is why the first registry query returned a false negative.

---

## ✅ The remediation is now measured FROM A NODE, not from my workstation

The caveat this section used to carry was the load-bearing one: *the anonymous pull was measured from
this workstation, and the node and I do not share an egress path.* That is the same defect as the gate
itself — **a census through a helper is a claim about the helper** — so leaving it written down while
recommending a credential deletion would have repeated the error inside its own correction.

Closed by running the consumer's own query. First the premise, because the test is worthless if the
pod inherits a credential: the namespace's `default` ServiceAccount attaches **no** `imagePullSecrets`
(the field is empty), so a pod that names none presents none.

```
kubectl -n sandbox run ghcr-anon-test-l01 --restart=Never \
  --image=…/invincible-agent/cortex-bff:ec055c49… --command -- /bin/true
```

| reading | result |
| --- | --- |
| pod phase | **`Succeeded`** |
| node | **`k3s-worker5`** — a node, not this workstation |
| pull secrets on the pod | **none** |
| kubelet event | `Successfully pulled image "…/cortex-bff:ec055c49…" in **23.001s**. Image size: 400058008 bytes` |

**A kubelet pulled a payload image with no credential.** So the 403 is caused by the credential being
*presented*, and removing it is not a hope — it is the measured path. The test pod was deleted.

⛔ **This is the check the gate was missing, and it costs 23 seconds.** It belongs in the roll
procedure ahead of the upgrade, not in the post-mortem of one: it exercises the real consumer, the
real image, and the real egress path, and it fails before a release can reach `pending-upgrade`.

Note what it does **not** show: that the secret is expired, or what is wrong with it. It shows only
that the anonymous path works from a node, which is all option 1 needs.

---

## What I did **not** verify
- **Why the credential stopped working.** Not read, by rule. Expiry is inference from its age and
  from roll #5 succeeding yesterday.
- ~~Whether every one of the 19 packages allows anonymous pulls.~~ **Closed rather than left as a
  caveat: 19/19 return HTTP 200 anonymously**, plus `dag-tools/user-deployment`, `pub-tools` and
  `doc-tools`. Writing the caveat made the gap cheap to close, which is the argument for writing it.
- **What `ghcr-pulltest` used.** Deleted before I read it.
- **Items 1–3 on the cluster.** Nothing in this roll landed, so item 3's "after" half is still gated.
