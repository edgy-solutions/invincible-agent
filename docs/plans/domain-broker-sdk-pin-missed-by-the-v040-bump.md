---
id:         domain-broker-sdk-pin-missed-by-the-v040-bump
status:     open
owner:      unassigned
blocked-on:
closed-by:
repo:       invincible-agent
code-site:  helm/invincible-agent/values.yaml:582 (domainBroker.meshSdkVersion), helm/invincible-agent/files/domain-broker.py
summary:    MASTER IS RED. tests/test_lock_coherence.py::test_domain_broker_sdk_version_matches_the_fleet_pin fails — the fleet moved to iagent-mesh v0.4.0 in dc327d1 (28 files: every pyproject.toml and every uv.lock, 15 and 29 respectively, all consistent) but helm/invincible-agent/values.yaml's domainBroker.meshSdkVersion was NOT in that sweep and still reads v0.3.1. The broker would authenticate by a different SDK build than the services it sits beside, which is the exact condition that seal exists to catch. ONE LINE, and the test names the fix verbatim. Filed rather than fixed because domainBroker is not the engine-cost lane's block and the standing fence says to file shared-seam findings. Verified NOT pre-existing: the test PASSES at 803071e and fails from dc327d1 onward.
---

# `domainBroker.meshSdkVersion` was missed by the v0.4.0 fleet bump

**Found 2026-09-03** by the engine-cost lane while running its own seal set. **Not that lane's
block**, so filed rather than fixed.

## The failure

```
AssertionError: domain-broker installs iagent-mesh v0.3.1 but the fleet pins v0.4.0.
The broker would authenticate by a different SDK build than the services it sits beside.
Update helm/invincible-agent/values.yaml -> domainBroker.meshSdkVersion.
assert 'v0.3.1' == 'v0.4.0'
```

## What is and is not consistent

`dc327d1` — *"the fleet consumes v0.4.0 — fourteen consumers, not thirteen"* — moved **28
files** and moved them **completely**:

- **15 `pyproject.toml`** files → all `@v0.4.0`, none left on v0.3.1
- **29 `uv.lock`** entries → all `?rev=v0.4.0`

**It did not touch `helm/invincible-agent/values.yaml`.** The broker's pin is not a
`pyproject.toml`; it is a chart value that the broker file is templated from, so a sweep
scoped to Python packaging files misses it by construction.

**Ownership check, done rather than assumed:** the test **passes at `803071e`** (before the
bump) and fails from `dc327d1` onward. It is not pre-existing, and it is not the engine-cost
addition — that engine's pyproject and lock both moved with the sweep and agree at v0.4.0.

## Why the seal is right to be loud about it

The broker sits in the request path and authenticates alongside the engines. A version skew
there means one component verifying tokens with a different SDK build than the components
around it — and the SDK is the package that governs fleet auth, which is why every engine
pins it to a tag rather than a range. The seal's own comment records that this pairing was
once claimed wrongly and would have been an outage.

## The fix

`helm/invincible-agent/values.yaml:582` → `meshSdkVersion: "v0.4.0"`.

**And the generalisable half:** the bump's scope was *"every file that pins the SDK"*, and it
was executed as *"every packaging file"*. Those two sets differ by exactly one member, and the
seal is what noticed. **If a future bump is scripted, derive its file list from the seal's
notion of a pin rather than from a glob over `pyproject.toml`** — otherwise the same member
goes missing again and the same test catches it again.

## Note for the ADR-0047 lane

**This bump is the wake condition ADR-0047 §8.5 named** — *"the checkable event is the pin
bump, not the tag"*. It has now happened: the fleet consumes v0.4.0. That reopens §8.5's
question about whether route C supersedes route A's shim, and the identity half of
[[sdk-discards-caller-identity]] should be re-read against what v0.4.0 actually delivers
before anything is concluded.
