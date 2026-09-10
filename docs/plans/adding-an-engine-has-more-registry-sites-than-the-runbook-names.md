---
id:         adding-an-engine-has-more-registry-sites-than-the-runbook-names
status:     open
owner:      unassigned
blocked-on:
closed-by:
repo:       invincible-agent
summary:    Runbook §0 names FOUR namespaces a new engine must be registered in. At least EIGHT sites exist, three of them found the hard way on engine-lg alone (mirror script — fifth omission of that same row, _KEY_TO_AGENT_DIR, and ENGINE_LG_PUBLIC_URL which the version census derives its population from). A commit faithful to the runbook inherits the runbook's gaps. Fix is a derived checklist, not a ninth row.
---

# The adding-an-engine population is a sample, and every engine pays for it

**Runbook §0 names four namespaces** — helm values key, component/service/deployment name,
image name, Keycloak client id — and says outright that their differing "is why one engine's
wiring gets missed three times."

**It gets missed because four is not the number.** engine-lg (`e66c063`, 2026-09-09) was a
careful commit: it rendered the chart four ways before landing, wrote its four namespaces down,
and got the `repository`-override reasoning exactly right. It still landed master red and left a
service invisible to the census, because it was faithful to a **sample**.

## The sites found so far

| # | site | how it was found | failure mode |
|---|---|---|---|
| 1–4 | values key / component / image / Keycloak client | runbook §0 | — |
| 5 | `values.yaml` `primeSubstrate.reregisterEngines.deployments` | runbook, later section | engine never restarts, so never re-registers |
| 6 | `tests/…/_KEY_TO_AGENT_DIR` | seal went red | **every check in that file SKIPS the key** — how `engineFinance` went five days unexamined |
| 7 | `scripts/mirror-to-artifactory.ps1` | seal went red | work cluster cannot fall back to ghcr → ImagePullBackOff the moment the chart flag flips |
| 8 | `ENGINE_<X>_PUBLIC_URL` in `templates/configmap.yaml` | **census, 2026-09-10** | **silent** — see below |
| — | `.github/workflows/build-containers.yml` | — | no image is ever built at any pinned sha |

**Site 7 has now been missed five times.** Its own comment says so, and already drew the
conclusion: *"a lesson written beside a list does not maintain the list. What maintained it was
the derived check."*

## Site 8 is the interesting one, because the defence was already in place

`gateway._fleet_version_targets()` does **not** hold a list. It derives the fleet by scanning
`ENGINE_*_PUBLIC_URL`, and its docstring says exactly why:

> *A hardcoded list is the shape this repo keeps paying for: a new engine's URL appears in the
> ConfigMap and the census silently does not include it, so the fleet reads complete while a
> service is unaccounted for.*

**It was incomplete anyway.** `configmap.yaml` mentions engine-lg zero times, so no variable
exists to scan. `scripts/version_census.py` printed a clean, uniform seventeen-row table — every
deployment at one commit, exit 0 — with engine-lg showing no process sha and nothing flagging it.
The engine was serving the whole time; `/version` returned 200 with the right sha when asked
directly.

**A DERIVED POPULATION IS ONLY AS COMPLETE AS THE THING IT DERIVES FROM.** An env var nobody set
is invisible to a scan of env vars. Deriving moved the hole from the list to the *source* of the
list; it did not remove it. (invincible-agent-5f, and it is a genuine refinement of
*derive the population, never name it* — see
[[a-green-seal-can-be-green-for-the-wrong-reason]].)

## The fix, and what it must not be

**Not a ninth runbook row.** That is the move that has failed five times on site 7 alone.

1. **A derived checklist.** One seal that takes an engine key from `templates/engines.yaml` and
   asserts it is present at every site — each site's absence carrying its own explicit-waiver
   entry with a reason, so an intentional omission is recorded and an accidental one is red.
   This is the shape of `_KEY_TO_AGENT_DIR` + `_NOT_A_REGISTERING_AGENT`, generalised across all
   eight.
2. **A floor on the derivation itself**, for site 8's class: the census must compare its scanned
   target count against an independent enumeration — deployments in the namespace, not variables
   in a ConfigMap — so a derivation with a hole in its source fails loudly instead of printing a
   complete-looking table.
3. **Site 7 stays hand-kept until someone can verify the deploy script**, and that decision is
   recorded in the file itself as OPEN, NOT IN FLIGHT. It is a PowerShell script that pushes
   images to the work cluster and cannot be executed or verified from a dev machine; the seal
   already catches a missing row *before* a deploy, which is how omission four was caught.

## Definition of done

* Adding a fabricated engine key to `templates/engines.yaml` turns **every** unsatisfied site
  red, in one run, naming each one.
* Removing `ENGINE_W_PUBLIC_URL` from the ConfigMap makes the census fail rather than print a
  shorter clean table — the floor from item 2, verified by mutation rather than asserted.
* The runbook's §0 table is generated from that seal's site list, or deleted in favour of
  pointing at it. **A hand-written list of a population is a sample**; this one has been resampled
  eight times and is still wrong.
