---
id:         doctools-ci-silent-on-push
status:     open
owner:      unassigned
blocked-on: 
closed-by:  
code-site:  
repo:       doc-tools
summary:    Pushes to doc-tools main produce ZERO CI runs — commits land unbuilt while reading as shipped. Use `gh workflow run`; verify the IMAGE, never the commit.
---

# doc-tools CI does not fire on push — commits land unbuilt, silently

**Cross-repo item.** The defect is in `edgy-solutions/doc-tools`; it is filed on the platform board
per ADR-0040's canonical-board rule (`repo:` names where it lives).

## The finding

Observed 2026-08-08. Three commits sat on `origin/main` of `doc-tools` with **zero run records** —
no failures, no `[skip ci]` marker, GitHub Actions `enabled`, the workflow `active`. Among them
`3db8dbb`, the `doc_type_source` attestation: the producer half of fingerprint normalisation.

**It read as merged and shipped while existing in no image.** The last built commit was `c7ffe87`,
two commits behind.

**The symptom is silence**, which is why it is dangerous: nothing is red, the commit is on main, and
every reasonable inference says the feature is live. This is the believed-built class arriving
through a *missing CI run* rather than a missing wire — and the usual tell (a failed build) is
exactly what is absent.

## Why it wasn't caught by the obvious check

`git log` shows the commit on `main`. The GitHub UI shows it merged. Only a query for **runs
matching that sha** shows nothing, and nobody queries that when the commit is visibly landed.

Compounding it: `doc-tools` deploys from a **mutable `:latest` tag**, so a pod started before the
last successful build serves stale code indefinitely with no signal. Observed the same week: a pod
created `2026-08-05T03:45` was still serving an image predating every stamped build, which presented
as an unstamped corpus and looked like a wiring bug in `pipeline_version`.

## Workaround, verified working

`workflow_dispatch` was added in `d5b4482` and fires reliably:

```
gh workflow run "Build Container Image" --ref main
```

Before that the only trigger was `push`, so the recovery path for a missed build was an empty
commit — and the path of least resistance was to assume it had built.

## The rule this hands us

**Verify the IMAGE, never the commit.** Throwaway-pod probe on a freshly pulled tag:

```
kubectl -n sandbox run probe --rm -i --restart=Never \
  --image=ghcr.io/edgy-solutions/doc-tools:latest --image-pull-policy=Always \
  --overrides='{"spec":{"imagePullSecrets":[{"name":"ghcr-pull-secret"}]}}' \
  --command -- sh -c 'echo STAMP=[$DOC_TOOLS_VERSION]'
```

`DOC_TOOLS_VERSION` is baked as a build-arg (`doc-tools@<sha>`); ARG and `build-args:` are in the
same job, verified. A pod predating a stamped build reports the variable **unset**, which is the
discriminator between "the stamp is broken" and "this pod is old".

## What is not known

**Root cause is unidentified.** Actions is enabled and the workflow is active, so the trigger itself
is the anomaly and no explanation has been established — not a `[skip ci]` marker, not a disabled
workflow, not a permissions change. Whether pushes have started firing again since `d5b4482` is
**unverified**; the last confirmed silent push was 2026-08-08.

Until the root cause is known, the operational posture is: **dispatch explicitly, and probe the image
before believing a doc-tools change is live.**

## Why this is filed rather than fixed

The fix is in another repo's CI configuration and the cause is unknown, so the honest deliverable is
the trap plus the workaround. It is filed today rather than waiting for the ADR-0040 migration
because it will bite whoever next pushes to `doc-tools`, and it currently lives only in one agent's
memory — which is precisely the condition ADR-0040 exists to end.
