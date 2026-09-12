---
iri: docs:runbook-rolling-a-service
# EXPLAINS IS DELIBERATELY EMPTY, AND THE EMPTINESS IS THE MEASUREMENT, NOT AN OMISSION.
# The invented-IRI rule (ADR-0037 section 1) refuses a target minted to make an edge look tidy,
# and adding-an-engine.md already keeps its list short for that reason. This page goes one step
# further because the graph has nothing it can honestly point at.
#
# Derived from setup/ontologies/mesh_system.ttl rather than recalled: the mesh declares FOUR
# lowercase verbs -- enumerateInstances, proposeDisposition, rendersAs, resolveInstance -- and
# 72 classes. NOT ONE of either concerns deployment, rolling, images, versions or health. A
# roll is an infrastructure act; the mesh does not model it, so there is no contract-depth
# target and inventing `mesh:rollService` is exactly the move the gate exists to refuse.
#
# RULED 2026-09-11 (register R-015), after this page raised the question: an edgeless runbook IS
# admitted. A page with no honest graph target is still a corpus page -- reachable by audience
# and by text, just not by an `explains` edge. Ingest requiring at least one target would refuse
# every operational runbook, and this page is the proof. So: ZERO OR MORE edges, and a page with
# none says so EXPLICITLY with the `none` sentinel below -- which is distinguishable from a
# missing key (author forgot) and from an empty list (author was unsure). This is a decision.
explains: none
doc_kind: how-to
# From policy/personas.yaml, IN ITS OWN CASING -- the canonical enum (PORTFOLIO_LEAD,
# DATA_STEWARD, DATA_ENGINEER, ARCHITECT, MECHANIC, ANALYST, PROGRAM_FINANCE_ANALYST,
# COST_ANALYST), read out of the file rather than recalled. RULED 2026-09-11 (R-017): the
# corpus normalises TO the policy file, never the reverse -- a ratified config outranks prose.
# The validator matches case-insensitively and lints to canonical case.
# Rolling a service is a platform act, so: ARCHITECT.
audience_hint: ARCHITECT
---

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

## THE RELEASE RECORD IS THE TRUTH THE CENSUS TRUSTS — so every roll updates it

**RULED 2026-09-11, after a roll that worked and a census that lied about it.**

`kubectl set image` changes the cluster and **not** the Helm release. The version census reads
`helm get values` as its expectation — correctly, because a release record is the only
fleet-wide statement of what *should* be running — so a roll that bypasses Helm makes the record
false and the census reports against the false record.

**What it looked like:** three engines rolled to master, all six litany legs green, code
confirmed inside the serving pods — and the census called those three **STALE**, because they
differed from a record that had not been told. The three newest pods in the fleet, labelled
behind. A reader acting on that label rolls the fix backwards.

**So a code-only roll goes through Helm:**

    helm upgrade <release> <chart> -n <ns>       --reuse-values --set global.imageTag=<sha> --no-hooks

`--no-hooks` is what makes this a *roll* rather than an upgrade: **it touches no hook and no PV**,
so it does not wake the prime, the ontology seed, or the reregister job, and it cannot stall at
hook weight 2 behind a pinned volume. It updates the deployments and the record together.

**`kubectl set image` remains correct for one thing only** — a deliberate, announced, temporary
divergence you intend to revert. Then say so in the handoff log, because the census will report
it and the next reader needs to know the report is expected.

> **The census's own fix, same day:** a sha that differs from the record is now reported as
> **AHEAD** or **STALE**, decided by git ancestry rather than assumed. The exit code is nonzero
> either way — divergence from the record is the thing it exists to report — but the operator is
> told which direction, **because the remedies are opposite.**

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

## The prerequisite has landed (2026-09-09)

**Migrating the chart to commit-tagged images was the outstanding prerequisite named here.**
It is done, in three parts:

* `global.imageTag` pins **every** image this repo builds, in one place:
  `--set global.imageTag=$(git rev-parse HEAD)`. CI already publishes `:<git-sha>` beside
  `:latest`, so no new build is needed. **Unset renders byte-identical to today.**
* Every image bakes `IAGENT_GIT_SHA` at build time, and every service serves `/version`.
  The BFF serves `/fleet/version`, which asks all of them and returns the lot.
* `scripts/version_census.py` reads that and exits 1 on any disagreement, so it is a gate
  rather than something to read and interpret.

It reached SEVEN OF TWELVE when first built, and the reason is worth carrying: a component's
own `tag` beats a global one, and fourteen values entries said `tag: "latest"` outright. They
were cleared. The floor also fell through to `Chart.AppVersion` — a tag CI has never
published — which is what every one of those literals was quietly papering over, and is the
documented cause of Engine P's ImagePullBackOff.

## The roll procedure

```bash
SHA=$(git rev-parse HEAD)          # the sha whose BUILD you are rolling
kubectl -n <ns> set image deploy/<name> <container>=<repo>/<image>:$SHA
```

`kubectl set image` per deployment, to an explicit commit tag. Targeted, reversible, no helm
upgrade — use `scripts/upgrade-sandbox.sh` when the chart itself must move.

**HOLD ONE DEPLOYMENT BACK AS A CONTROL.** Pick one nothing in the path under test touches.
A census that has only ever seen all-green has not been shown able to say otherwise, and this
is the cheapest possible way to show it. If the held-back service does NOT come back named as
behind, the census is the thing under test, not the fleet.

```bash
uv run --frozen python scripts/version_census.py -n <ns> --expect $SHA
```

### `--expect HEAD` is wrong the moment a docs commit lands after a build

Pass **the sha you rolled**, not `HEAD`. A docs-only or test-only commit moves `HEAD` past the
image without changing it, and `--expect HEAD` then reports the entire fleet stale for a
reason that has nothing to do with staleness. `HEAD` is right for the common case and
becomes wrong silently, which is the worst combination — so the roll script should record the
sha it rolled and the census should read that, rather than anyone passing `HEAD` from habit.

## The four fleet states

A null sha arrives for four reasons and **they have different repairs.** Collapsing them is
the `fetch_registered_entries` conflation, and it was in the first version of the aggregator:

| state | what it is | repair |
|---|---|---|
| `reporting` | answered, reports its build | nothing |
| `no_endpoint` | answered **404** — `/version` not in that image | **roll it** |
| `unstamped` | answered, endpoint present, no `GIT_SHA` | rebuild it |
| `unreachable` | nothing came back at all | the service is **DOWN** |

**A healthy pod 404ing an endpoint it was not rolled with is BEHIND, never DOWN.** "Go and
rescue it" and "deploy it" send a person to opposite places. cortex-ui's header called a BFF
that was up and serving picks UNREACHABLE for exactly this reason, and the same collapse was
in this repo's aggregator on the same night.

This is not a nicety: **the held-back control lands in precisely this state.** A census that
called it DOWN would have made the control unreadable.

The discriminator is whether the service SPOKE — a transport failure has no status at all,
and a non-404 status is neither down nor missing (401 and 500 are different problems, and
neither one is "no endpoint").

## What the litany still cannot enforce

`REQUIRE_PINNED_IMAGE=1` turns the unpinned warning into a stop, and `EXPECT_COMMIT=<sha>`
asserts the tag carries a specific commit. Both work now that the chart can be pinned — but
the chart's DEFAULT is still `latest`, deliberately, so that an unset knob changes nothing.
Until a deploy sets `global.imageTag`, `LEG2` still prints the warning and continues.

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
