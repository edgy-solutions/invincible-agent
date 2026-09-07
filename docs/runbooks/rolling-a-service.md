# Rolling a service

**Ruled 2026-09-06, after a fix silently regressed out of a running deployment.**

## The rule

**A roll references the commit-tagged image. Never `:latest`.**

And after every roll, in this order:

1. **Find the pod that SERVES TRAFFIC** — `kubectl get endpoints <deploy>`, not the newest
   Running pod.
2. **Assert the image tag is the commit you meant.**
3. **Grep a symbol that commit introduced, inside that pod.**

`scripts/roll-litany.sh` does all three. Raw `kubectl rollout restart` does none of them.

## Why, three failures deep

Each of these happened this week, to people being careful.

### A digest change is not a landed commit

Engine-o's digest moved `1bfd9214 → eaa3cc3e` and the code was not in it — the new image
predated the commit. Digest-changed reads as success and means only *"not the old image"*.

**So:** grep the symbol the commit introduced.

### A symbol found is not a symbol served

A partially-rolled deployment answers truthfully from a pod nobody is routed to. Engine-o ran
two pods for several minutes; `kubectl exec deploy/...` picks one arbitrarily, and the litany
used to pick the newest by timestamp. Both can be the wrong one.

**So:** resolve the pod through `endpoints` first. The litany prints `[serving]` or
`[newest-running (NO SERVICE ENDPOINT - may serve nobody)]` so the answer says which it is.

### `:latest` lets one lane roll back another's fix

Engine-o was rolled by another lane onto an image built **before** `2ff0acf`, and that fix
regressed out of the deployment. **Nobody did anything wrong.** Both lanes pulled "the newest
image"; they did it at different moments, and `:latest` is not a commit — it is a moving
pointer that two independent rolls resolve differently.

This is the one a symbol check catches only if you already suspect it. The lane that rolled had
no reason to check a symbol from someone else's commit.

**So:** the tag names the commit, and rolls stop being order-dependent.

## Current state: the litany REPORTS, it does not yet ENFORCE

The chart still publishes `:latest`, so `LEG2` prints the unpinned warning and continues.
`REQUIRE_PINNED_IMAGE=1` turns it into a stop today, and `EXPECT_COMMIT=<sha>` asserts the tag
carries a specific commit.

**Migrating the chart to commit-tagged images is the outstanding prerequisite** — until it
lands, this leg cannot enforce, and saying so plainly is the point. A guard that claims to
check something it cannot is worse than a documented gap.

## The check that is not automated

The `bash` this environment hands a Python subprocess reports an empty `$BASH_VERSION` and
cannot `set -o pipefail`, so the litany itself has no pytest seal — it is exercised by running
it. `tests/test_helm_timeout_guard_reads_the_resolved_value.py` carries the same limitation and
records it in the same words.

## Upgrades, not just rolls

`scripts/upgrade-sandbox.sh` is the only documented path for a helm upgrade. Raw
`helm upgrade` is **not** a documented path: the script carries the killed-client trap and the
resolved-timeout guard, and neither exists on the raw command.

`helm upgrade --timeout 10m` marked release 100 **failed** while the prime hook ran on
healthily underneath — the third instance across two lanes. The guard now resolves what helm
will actually receive (the env value, then the *last* `--timeout` in `"$@"`, both flag forms)
and refuses under 75m. `ALLOW_SHORT_HELM_TIMEOUT=1` is the named escape hatch.

**A ConfigMap change does not restart pods.** The env is injected at pod start, so an upgrade
that changes a key must be followed by a roll of everything that reads it — and the target must
be rolled *before* anything is repointed at it. Repointing `ENUMERATE_INSTANCES_URL` at an
engine-o endpoint that had not been rolled yet broke enumeration for both domains for several
minutes: the config moved before its target existed.
