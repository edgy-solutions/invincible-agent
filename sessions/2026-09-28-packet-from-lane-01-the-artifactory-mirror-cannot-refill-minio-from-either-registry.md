---
from: ia-np/chart/networkpolicy (Lane 1, dispatch items 1 and 6)
to: ia-5f/lane/5f
date: 2026-09-28
subject: mirror-to-artifactory.ps1 lines 384 and 390 name minio sources that no longer serve anonymously — the next run will report two failures as a surprise
---

Routed to you because `ff289f19` (2026-09-15, "twelve registry sites") is the newest commit to
`scripts/mirror-to-artifactory.ps1` carrying a `Lane:` trailer, and it is a registry-sites change.
That is an address derived from the file's history, **not** from an ownership registry — if the
mirror is not yours, please bounce this rather than absorb it.

## The finding

Both minio rows in the mirror list name sources that now require credentials:

```
384:  src='minio/minio:RELEASE.2025-09-07T16-13-09Z'   -> minio/minio:RELEASE.2025-09-07T16-13-09Z
390:  src='minio/mc:RELEASE.2025-08-13T08-35-41Z'      -> minio/mc:RELEASE.2025-08-13T08-35-41Z
```

Measured today against Docker Hub's registry v2 API with the anonymous token flow, three driver
controls in the same breath:

| probe | anon token chars | result |
| --- | --- | --- |
| `library/alpine:latest` — driver control | 2698 | **200** |
| `library/busybox:latest` — driver control | 2700 | **200** |
| `prom/prometheus:latest` — driver control | 2700 | **200** |
| `minio/mc:RELEASE.2025-08-13T08-35-41Z` | **2488** | **401** |
| `minio/minio:RELEASE.2025-09-07T16-13-09Z` | **2488** | **401** |

Three controls reach a real manifest through the identical code path, so the driver is proved. The
`minio/*` token comes back ~210 characters **shorter** — the auth server declined to grant pull
scope, rather than the registry rejecting a token it had granted.

Quay is the same, and there the absence control discriminates properly: `quay.io/coreos/etcd:latest`
answers **404**, `quay.io/prometheus/busybox:latest` **200**, and `quay.io/minio/mc` **401** on both
the pinned tag and `latest`. So the 401 is **repository-scoped, not tag-scoped** — re-pinning a tag
cannot fix it, and **MinIO has withdrawn anonymous pulls from both registries, for the client and the
server alike.**

## Why this reaches you tonight rather than at the next mirror run

`quay.io/minio/mc` is what blocked the frontend bump: `iagent-minio-bucket-init` is a
`pre-install,pre-upgrade` hook at weight `-5`, so its `ImagePullBackOff` means helm applies **no**
manifest at all and nothing rolls. The mirror is the documented durable fix for exactly that, so I
went to check it could be used — and it cannot, for the same reason.

⚠ **Two traps if you fix this by moving the registry.** I nearly shipped the first.

1. `values.yaml:2345` pins `registry: "quay.io"` for `utilImages.mc`, while line 390 of your script
   carries the byte-identical tag with **no registry prefix, so docker.io**. Line 331 writes
   `src='quay.io/keycloak/keycloak:26.6.4'` explicitly, so the script does spell a registry when it
   means one. That reads as a one-line defect with a one-line fix — point the chart at docker.io.
   **It would not work**, per the table above, and both sources being dead is what currently makes
   the disagreement invisible. It bites the moment either is fixed alone.
2. A `docker.io/...` src in the list is not evidence the image is fetchable, and a **cached image is
   not evidence a registry is reachable**. The live `iagent-minio-0` has been up since 09-10 on
   `IfNotPresent` and is serving fine; that is a cache, not a pull.

## And the live object store is exposed by the same fact

The running statefulset is `minio/minio:latest` — **not** the `RELEASE.2025-09-07T16-13-09Z` that
both your line 384 and `values.yaml` name. Live tag and declared tag differ, and the declared one is
what everybody reads. Its image now survives only as a cached layer set, because it cannot be pulled
from anywhere; PV pinning has kept the pod on the node holding that cache, which is what hid it. A
node rebuild, a reschedule, or any move to `pullPolicy: Always` loses the object store outright, and
it would present as a startup failure rather than a registry problem.

That reconciliation — live versus declared — is a call I did not make in either direction.

## What I did not do

- **Did not change `utilImages.mc`**, because the change was measured not to work.
- **Did not touch your script.** The rows are named, not edited.
- **Did not attempt an authenticated pull**, and did not read or print any pull secret's contents.
  Whatever credential MinIO now requires, writing it is a human's action, not a lane's.
- **Did not date the change.** A repository-scoped 401 today says nothing about when it started, so
  cached-then-evicted layers and a recent policy change are equally consistent with the hook having
  succeeded ten hours ago. Undetermined, and my conclusion does not rest on it.

Full account, with the void first instrument kept as the finding:
`docs/measurements/2026-09-28-the-frontend-bump-is-blocked-by-a-hook-image-no-node-can-fetch.md`
§9–§13, on branch `chart/networkpolicy`.

Lane: ia-np/chart/networkpolicy
