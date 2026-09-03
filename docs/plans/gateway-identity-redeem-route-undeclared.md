---
id:         gateway-identity-redeem-route-undeclared
status:     open
owner:      unassigned
blocked-on:
closed-by:
repo:       invincible-agent
code-site:  src/iagent/gateway.py (POST /internal/identity/redeem), docs/architecture/endpoint_gating_manifest.yaml (gateway section)
summary:    FOUND 2026-09-02 by the engine-cost lane, NOT ITS DEFECT and not fixed by it. tests/test_endpoint_gating_manifest.py::test_every_source_route_is_declared[gateway] FAILS ON HEAD — POST /internal/identity/redeem exists in src/iagent/gateway.py and has no row in the endpoint-gating manifest, so it carries no declared identity, gate or exposure class. Confirmed pre-existing by stashing the lane's changes and re-running: still red. A red seal that everyone steps over stops being a seal, and this one guards the one surface where an undeclared route matters most — an IDENTITY REDEMPTION endpoint. Needs its owner to classify the row (gated | releasable_by_design | ungated_by_accident | delegates | internal), which is a posture call the finding lane has no standing to make.
---

# `POST /internal/identity/redeem` has no gating-manifest row

**Found 2026-09-02** while adding `cost_agent` to `SERVICE_FILES` for the engine-cost build.
**Not this lane's defect, not fixed by this lane** — filed per the standing fence on shared
seams.

## The finding

```
FAILED tests/test_endpoint_gating_manifest.py::test_every_source_route_is_declared[gateway-src/iagent/gateway.py]
AssertionError: gateway: 1 route(s) in src/iagent/gateway.py are NOT declared in the
endpoint-gating manifest: [('POST', '/internal/identity/redeem')]
```

**Confirmed pre-existing rather than assumed.** The lane's own changes were stashed and the
test re-run against clean HEAD: **still red**, with the same single route. So this is not a
side effect of adding a service to `SERVICE_FILES`, and the engine-cost rows are not
implicated.

## Why it is worth a packet rather than a fix-in-passing

**The route is an identity redemption endpoint**, which is the surface where "what is the
declared gate on this?" has the highest consequence in the repository. The manifest exists so
that question has a written answer per route; an undeclared row means the answer lives only in
whatever the code happens to do.

**And a red seal that everyone steps over stops being a seal.** This test is one of the layered
guards that caught Engine F shipping absent from `SERVICE_FILES` — it works, and its value
depends on red meaning something. A standing failure trains readers to scroll past it, which
is how the *next* undeclared route arrives unnoticed.

## What it needs, and why this lane cannot do it

A row with `identity`, `gate`, `exposes`, `consumers`, `class` and a `justification` — where
**`class` is a posture ruling**, one of `gated | releasable_by_design | ungated_by_accident |
delegates | internal`. Choosing it requires knowing what the gateway intends this route to be,
which the finding lane does not.

**If the honest answer is `ungated_by_accident`, the row still gets written** — the manifest's
whole point is that an accidental gap is *declared* as one rather than left blank, so it can be
counted and scheduled rather than rediscovered.

## Note for whoever takes it

**Edit the manifest as TEXT.** A `yaml.safe_dump` round-trip on this file previously destroyed
188 comment lines while adding five rows, and in that file the comments are the reasoning. The
diff's own size hid the loss.
