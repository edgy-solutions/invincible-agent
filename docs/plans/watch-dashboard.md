---
id:         watch-dashboard
status:     parked
owner:      human
blocked-on: enforcement locks (near complete)
closed-by:
repo:       invincible-agent
summary:    Live canvas cards — refresh-on-demand, then materialization, then streaming. Design note, unbuilt.
---

# Watch / dashboard — live canvas cards

> **Provenance note.** This packet is a **design sketch reconstructed from conversation**. Unlike
> `silence-closure-arc`, almost none of it is checkable against the repo, because none of it is
> built. It is recorded so the reasoning survives the session, not because it has been verified.
> Treat every claim below as a proposal. The one thing that *is* checkable — that no watch
> object, schedule or card-refresh path exists in the repo today — is the reason its status is
> `parked` rather than `open`.

## The thesis

Not "dashboards in the canvas" — **the canvas as the operational surface** where watching,
deciding and acting share one substrate. A BI tool shows a number; when the number is wrong you
leave the tool. Here the chart that alarms sits beside the review it spawns, and the disposition
dispatches through the same governed machinery.

## The new concept

A **watch**: `(query descriptor + cadence + owner + condition + consequence)`. Everything else is
composition of machinery that already exists.

Four questions the object forces, each with an answer the system's existing rules dictate rather
than invent:

- **Whose entitlements?** The owner's — a watch is a standing question *by someone*. A watch
  whose owner loses the entitlement stops firing **legibly** (`paused: entitlement`), never
  silently. That is the silence-closure rule applied before the thing exists.
- **What is a notification?** A human task. Do **not** build a second, lighter alerts pipe beside
  the existing one — that is the two-writers shape this codebase has retired repeatedly.
- **When may a consequence act?** Notify-only is `supervised`. Auto-dispatch is the autonomous
  path: capability-gated, granted per watch-class through the ceremony machinery and the trust
  table's `(format_fingerprint, pipeline_version)` keying.
- **Cadence cost.** Watches should reference **promoted chains** rather than each carrying a
  private query — which puts chain promotion on the critical path of two theses at once, and is
  the main reason this is parked rather than started.

## Tiers

1. **Refresh-on-demand.** The card carries the query descriptor; refresh re-drives it under the
   *viewer's* identity, entitlements re-evaluated at fetch. Smallest tier, and it forces the two
   contract changes tiers 2–3 need anyway.
2. **Scheduled materialization.** A promoted chain on a Dagster schedule. A service identity
   materializes; the viewer is gated at read. **Staleness stated on the card**, never implied.
3. **Streaming.** Deferred. The hard part is entitlement semantics on a subscription:
   authorized-once-and-flowing-forever is the stored-authz defect in motion.

## The constraint binding all tiers

**The UI never computes or extrapolates between updates.** The card renders backend truth at a
stated timestamp, or it is synthesizing — and a synthesized number on an operational surface is
indistinguishable from a measured one to the person acting on it.

## Status

Parked. Nothing starts before the enforcement rolls complete and the ceremony closes.
