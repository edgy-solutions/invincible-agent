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

## CHECK THE SILENT PRECONDITION FIRST, OR THE LOUD ONE LOOKS LIKE THE CAUSE

**RULED 2026-09-12**, from verifying the overlay gate's first live firing.

Two preconditions had to hold for it to work: the overlay directory in the **image**, and the env
var in the **pod**. They fail differently, and that decides the order you check them in:

| precondition | how it fails |
|---|---|
| overlay dir missing from the image | **SILENTLY** — `compose()` composes a missing directory to nothing, and the gate reads the seed as if it were the whole set |
| env var missing from the pod | **LOUDLY** — the code logs that it was not told where to look and falls back on purpose |

**CHECK THE SILENT ONE FIRST.** Start with the loud one and you find a real, visible problem —
and then stop, having found *the symptom wearing the cause's clothes*. Fix the env var, redeploy,
and the gate still reads the seed alone, because the directory was never there.

The general form: **when two conditions can each produce the same failure, check the one that
fails silently first** — the loud one will announce itself whenever you get to it, and the quiet
one will not.

*Worked example: `/app/policy/overlays/sample/task_kinds/pcn_disposition.yaml` in the image, then
`TASK_KIND_OVERLAY_DIRS` in the pod, then the gate's own answer read from INSIDE the serving pod
rather than from the local tree — which had been wrong about the cluster twice that day.*

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
uv run --frozen python scripts/version_census.py -n <ns>
```

### DO NOT PASS `--expect` AFTER A ROLL — the default already knows

**The census defaults to the tag in the release record** (`helm get values`), which is **written by
the act of rolling**. So the post-roll check takes no argument, and there is nothing to get wrong:

    uv run --frozen python scripts/version_census.py -n <ns>

**`--expect` is for asking "is the fleet at THIS sha" deliberately** — auditing a suspected drift,
or checking a sha you did not roll. **It is never the post-roll check.**

**MEASURED 2026-09-14, on the instrument's own author.** I passed `--expect $(git rev-parse
origin/master)` out of habit after a roll. A docs-only commit had landed between the build and the
check, so master was one commit past the rolled image — and the census correctly reported **all 18
services stale** against an image that does not exist. Re-run with no argument: **17 current, 1
real failure.**

**The earlier rule here said "pass the sha you rolled, not HEAD." That was the right diagnosis and
the wrong remedy** — it left a habit with somewhere to land, and the habit is what fired. `d8e9a40`
had already removed the need for the argument; the runbook had not caught up. **A rule that tells
you which value to type is weaker than one that tells you not to type a value.**

### (historical) `--expect HEAD` is wrong the moment a docs commit lands after a build

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

## Take the roll lock first, and release it only when the gates pass

Ruled 2026-10-24 (the architect). One lane rolls the sandbox at a time, and a ConfigMap enforces it,
not a packet:

```bash
scripts/roll-lock.sh show              # who holds sandbox/roll-lock, since when, until when
scripts/roll-lock.sh acquire           # upgrade-sandbox.sh and roll-litany.sh do this themselves
scripts/roll-lock.sh release           # after the gates pass, by the lane that holds it
```

- The lock is `sandbox/roll-lock` with keys `lane` (`<repo>/<branch>`, derived from git), `started` and
  `expected_end`.
- Every roll script refuses (exit 3) while another lane holds a lock that is not yet stale. **Stale is
  the later of 90 minutes after creation and the holder's `expected_end`** (architect, 2026-10-24):
  90 minutes is the floor, and a roll that declares more keeps its lock that long, so a prime in
  minute 91 to 100 of a 100-minute helm timeout is still protected. A stale lock is taken over,
  loudly. A missing or unparseable `expected_end` leaves the 90-minute floor alone, and the script
  says so.
- **What the holder declares at acquire is all that protects it.** `expected_end` is `started` +
  `--minutes`, and the holder cannot extend it: acquiring again is a no-op. `upgrade-sandbox.sh`
  declares its helm timeout only, so gates run after a full-length helm wait are past the declared end.
- `upgrade-sandbox.sh` takes it after its own guards and right before helm, for the length of its helm
  timeout. A `--dry-run` only reports it. `roll-litany.sh` takes it for 30 minutes; if the same lane
  holds it already, that is a no-op.
- `kubectl create` is the atomic step: two lanes acquiring at once get one winner. An unreadable lock
  is refused (exit 4), never read as free.
- **Release after the gates, not after helm.** The values diff, imageIDs, worker6, the walks: those are
  part of the roll.

**Why.** Prime launches every ontology ingest in the **doc-tools** code location
(`prime_databases.py`, `repositoryLocationName: "doc-tools"`). So a doc-tools roll during an iagent
prime replaces the pod the ingest is running in, and kills it. iagent rev 216 failed exactly so:
doc-tools rev 54 rolled inside it, the `mesh_system` run lost its worker, the run monitor failed it at
60 minutes, prime exited non-zero, and helm skipped every later hook (ontology-seed, reregister,
demo-seed). A packet asking the other lane to wait had been sent, and did not hold. doc-tools and the
workbench copy `scripts/roll-lock.sh` into their own roll scripts.

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

## The sandbox TLS leaf is pinned, never trusted blindly

The sandbox has no lab CA. Every ingress (the UI, the BFF, Keycloak, electric) serves one
self-signed wildcard leaf from the `edgy-wildcard-tls` secret. A post-roll walk **pins that leaf**.
It never disables verification (ruled 2026-10-12).

| field | value (measured 2026-10-12) |
| --- | --- |
| subject = issuer | `CN=*.<sandbox domain>` (one wildcard leaf for every ingress; the domain is in the out-of-repo log) |
| SHA-256 fingerprint | `99:F1:45:2F:08:86:1D:31:35:E3:7C:A1:2B:27:C4:C8:68:B7:E3:00:FB:A7:D4:A8:4C:4F:17:02:66:AB:CB:A6` |
| SPKI sha256 (base64) | `4PSaAg7X2o8kQl7b/kRMD+Dp7piSCZwog2fajFf7v1s=` |
| notAfter | 2027-06-05 |

**Capture the leaf before every walk and compare.**

```bash
openssl s_client -connect <host>:443 -servername <host> </dev/null 2>/dev/null \
  | openssl x509 -outform PEM > sandbox-leaf.pem
openssl x509 -in sandbox-leaf.pem -noout -fingerprint -sha256
```

A fingerprint that differs from the table is a **rotation**. Update this table in the same commit
that walks against the new leaf, so a rotation is seen and never silently trusted.

**Python clients** (`requests`, httpx) take the PEM: `REQUESTS_CA_BUNDLE=sandbox-leaf.pem`.

**Chromium (Playwright)** reads only the OS store, so a PEM cannot reach it. Pin the key with
`--ignore-certificate-errors-spki-list=<SPKI sha256>` in `launchOptions.args`. Chromium then
accepts only a chain whose key hashes to that value.
- Control, 2026-10-12: a wrong pin still fails `ERR_CERT_AUTHORITY_INVALID`.
- With the right pin, 0 cert errors.
