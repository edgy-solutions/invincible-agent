---
id:         unminted-caller-enumeration
status:     open
owner:      agent
blocked-on:
closed-by:
repo:       invincible-agent, iagent-mesh-sdk, dag-tools, doc-tools, cortex-ui
summary:    Static read of every outbound call in the fleet, classified exempt / minted / unminted. The flip's real precondition.
---

# Unminted-caller enumeration — static, cross-repo

**This is `transport-flip`'s real precondition.** The gauge is corroboration, not proof.

## Why a static read and not the gauge

The registration wiring produced a witnessed zero: `/v1/register`, clean window, 0 new
unverified, 6 verified. That result is real and it is **narrow**.

`review_composer.py:94` calls engine-o's `/resolve_instance` with no credential. It is a
non-exempt path, so under REQUIRE it 401s — and line 95's `raise_for_status()` means the 401
**raises** rather than degrading to the abstain path, so every review fails to *compose*. The
gauge never showed it, and could not have:

> **A gauge measures traffic that occurred, not callers that exist.**

A caller that has not fired during the observation window is invisible to it. "Zero unverified
on non-exempt paths" is therefore scoped to *paths someone exercised*, which is materially
weaker than the flip's precondition requires. **Absence of an observation is not observation of
absence** — and this one was found by accident, while chasing an unrelated question, which is
not a discovery method anyone should rely on twice.

## SCOPE — cross-repo, stated because the default reading is wrong

The flip gates **the whole cluster**, not one repo. `review_composer` happens to be platform
code, but outbound calls also live in:

| repo | why it is in scope |
|---|---|
| `invincible-agent` | the engines, composer, supervisor, gateway, projector, broker |
| `iagent-mesh-sdk` | `MeshClient.ask`, registration transport, anything the SDK calls on an engine's behalf |
| `dag-tools` | `central_gateway` and `CortexDataClient` outbound paths |
| `doc-tools` | the extraction/ingest side, which calls into the mesh |
| `cortex-ui` | browser-originated calls that terminate on gated routes |

Per ADR-0040 the `repo:` field carries this explicitly. **Without it the item silently means
"the repo I happened to be in"** — which is exactly how `review_composer` went unnoticed while
the platform's own registration callers were being enumerated carefully.

## Method

Read outbound call sites from **source**, not from logs. For each, classify:

- **exempt** — target path is in the callee's exempt set (kubelet paths only)
- **minted** — attaches a credential from an explicit identity (`mint_token`, `engine_mint`,
  `_telemetry_headers`, the registration transport)
- **unminted** — no `Authorization`, or a static token, or a credential inherited ambiently

For each **unminted** entry record: caller file:line · target service and path · whether the
path is exempt at the callee · **and what happens on 401** — degrades, or raises. That last
column is the severity, and it is the column this defect proved matters: `raise_for_status()`
turned a tolerated outcome into a total failure.

## Known entries (seed, not the answer)

| caller | target | credential | on 401 |
|---|---|---|---|
| `review_composer.py:94` | engine-o `/resolve_instance` | **none** | **raises** (`raise_for_status`) |
| six engines' registration | registrar `/v1/register` | minted, decode-witnessed | transport retries |
| supervisor dispatch | engine `/…` | minted at `_telemetry_headers` | — |

## Acceptance

- Every outbound call site in the five repos classified, none unclassified.
- Every `unminted` entry either minted, or explicitly exempted with a reason.
- A guard that fails when a new outbound call appears without a classification — otherwise this
  is a one-time census and the next `review_composer` arrives unannounced.

## What this does NOT prove

That the classified callers *behave* correctly under REQUIRE. That still wants the throwaway-pod
witness per service. Static enumeration answers "who could be denied"; the witness answers "what
happens when they are".
