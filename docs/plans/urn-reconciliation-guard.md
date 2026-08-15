---
id:         urn-reconciliation-guard
status:     blocked-on-human
blocked-on: a POSTURE ruling — fail broker startup on a URN that does not resolve in DataHub, or warn and serve. Fail-closed is the honest reading and also means a DataHub outage stops every broker. That trade is the human's to make.
owner:      human
closed-by:
code-site:  dag_tools/domain_broker/main.py
repo:       dag-tools
summary:    Nothing checks that a URN a broker registers corresponds to a real DataHub entity. Every identity defect this week — platform, endpoint, bucket — produced the same silent 404, and this one check would have caught all three at startup instead of at a demo.
---

# Two derivations of one identity drift; only a check that they agree holds

A broker advertises routes under URNs it derives locally. The catalog holds URNs derived
elsewhere. Nothing compares them. When they disagree the gateway returns 404 with a routing
table that looks fully populated, and both halves are internally consistent, so neither side
can detect the fault alone.

Three distinct causes produced that identical symptom in one week — a forced
`platform="dagster"` ([[broker-catalog-urn-derivation]]), a wrong `AWS_ENDPOINT_URL`, and a
doubled bucket URL ([[broker-endpoint-env-divergence]]). Each took its own debugging cycle.
**One reconciliation check would have caught all three, at startup, without anyone knowing in
advance which inputs mattered.** That is the argument for it: it is invariant to the cause.

## The check

At broker startup, after `LOCAL_ASSETS` is built and before advertising: for each URN, ask
DataHub whether that entity exists. Report the misses with both strings, since the diff is
always the diagnostic — every instance this week was solvable in seconds by putting the
registered key next to the requested one.

## THE RULING NEEDED — and why it is genuinely a decision

**Fail startup** — a broker whose identities do not exist in the catalog is advertising routes
nobody can use; refusing to start is the honest posture and matches this codebase's
`realm-reconcile` readback gate ("a release whose identity plane is unverified is a failed
release"). **But** it makes DataHub a hard startup dependency: a catalog outage, or a broker
racing an ingest, takes down data serving that would otherwise work — the same ordering trap
as [[registration-boot-order-race]], one layer over.

**Warn and serve** — no new failure mode, and the misses are visible to anyone reading logs.
But this week is the evidence for how well that works: every one of these WAS visible in
principle and none was noticed until a person went looking.

This is [[gate-class-follows-the-effect]] wearing a different hat, and it is five minutes of
thought rather than a build.

## Middle options, if neither pole is right

- **Fail on ALL missing, warn on SOME** — a broker with zero resolvable URNs is
  misconfigured; a broker with one is likely a genuine catalog gap.
- **Warn at startup, fail in CI** — the reconciliation runs against a real catalog in a
  pipeline, and production only warns.
- **Announce the posture at startup** either way, so a reader can tell a checked deployment
  from an unchecked one — the same discipline as the transport gauge's OBSERVE announcement.

## Note on scope

The check belongs in the broker, not the registrar: the registrar's Contract D already
verifies the URIs exist as `:OntologyClass` nodes, which is a different graph and a different
question. This one asks whether the ASSET identity is real.
