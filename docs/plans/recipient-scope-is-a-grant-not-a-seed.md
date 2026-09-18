---
id:         recipient-scope-is-a-grant-not-a-seed
status:     open
owner:
blocked-on:
repo:       invincible-agent
code-site:  policy/ (new grants file + sync + validate_policy), docs/adr/ADR-0047 (amendment), agent_fleet/cost_agent/seed.py (RECIPIENT_READERS, removed when this lands)
summary:    Who may FETCH a produced customer-validation package is currently a dict in engine-cost's seed. It is a grant-rail relation and wants task_grants.yaml's shape — deny-by-default, Topaz-decided, git-asserted with git-blame, overlay-configurable, sync-flowed so removal REVOKES, and granted_by + reason required on every entry. A mapping changeable by anyone who can change the engine is not policy. Ruled 2026-09-14 alongside the fix that put the check on the route; Lane 1's, with an ADR-0047 amendment, not an engine change.
---

# Recipient scope is a grant, not a seed

## What exists today, and why it is not enough

`GET /artifact/{filename}` on engine-cost authorizes the caller before serving a produced
package (`bcbc249`): `authz_id` against the reader list for the recipient that artifact belongs
to, 403 naming the package, decided before existence is revealed, no service identity entitled.

**The check is right. Its input is in the wrong place.**

    agent_fleet/cost_agent/seed.py
      RECIPIENT_READERS = {"notional-customer-alpha": ("alice@example.com",), ...}

**A mapping changeable by anyone who can change the engine is not policy.** It cannot be
granted, reviewed or revoked independently of a deploy; there is no git-blame trail *as a
grant*; and nothing refuses an entry naming somebody who does not exist.

## The shape it wants, and it already exists

`policy/task_grants.yaml` solves the same problem for *who may act on a human task*. Its model
transfers field for field:

| property | how it applies here |
|---|---|
| **deny-by-default** | already true of the route; the rail makes it true of the DATA |
| **Topaz-decided** | the engine asks, rather than reading a dict it ships with |
| **git-asserted, git-blame** | who granted a customer access to a package, and when |
| **sync-flowed; removing an entry REVOKES** | the property a seed cannot have at all |
| **`granted_by` + `reason` REQUIRED** | prove-the-negative on the grant path; the sync refuses an unexplained entry |
| **`validate_policy` refuses an unknown `grant_to`** | a reader who is not a seeded user is a typo, not a grant |
| **overlay-configurable per deployment** | a customer's real recipients compose at the repo |

**Key convention**, following `"<task_kind>:<compartment>"`:

    package:<recipient_scope>        e.g. package:notional-customer-alpha

**Permission name is an open choice with a stated lean.** `can_view` already exists and reads
correctly. A distinct `can_fetch` would separate *may see that this disclosure exists* from *may
download the whole of it* — worth having if the UI ever lists packages a caller cannot pull. The
owner should decide; this packet does not.

## THE ONE THING THE RAIL DOES NOT DECIDE, AND IT MUST NOT BE LOST

**`svc:` subjects ARE seeded users** — `svc:review-starter`, `svc:supervisor`, `svc:engine-d` all
appear in `users.yaml`. So the rail would happily accept `grant_to: svc:cortex-bff`, and
`validate_policy` would pass it.

**The engine refuses service identities, and that rule is the engine's, not the rail's.** The
card action arrives through cortex-bff; granting the service would open the route to anyone who
can open the UI — **a confused deputy one hop out, wearing an authorization check's clothes.** A
service acting for a person must carry THAT PERSON's identity (ADR-0044's per-request minted
ticket).

> **Move the data to the rail and that rule is silently droppable**, because the rail's own
> validation would not object. It belongs in the ADR-0047 amendment as a constraint on the
> grant, not in a comment in an engine that no longer holds the mapping.

**This is the same shape as `task_grants.yaml`'s own group prohibition**, arriving from the other
direction: there, a group name seeds a phantom `user:<group>` that passes readback while routing
an approval to nobody. Here, a service name seeds a real subject that passes everything while
routing a disclosure to everybody. **Both are grants that validate and mean the wrong thing.**

## What lands, in order

1. **The grants file**, mirroring `task_grants.yaml` including its refusals.
2. **The sync**, so an entry becomes a Topaz relation and removal revokes it.
3. **ADR-0047 amendment** — §5 currently says entitlement is filtered at production. It is now
   filtered at production AND at fetch, and the amendment should carry both the two-point check
   and the no-service-identity constraint above.
4. **The engine asks Topaz**, and `RECIPIENT_READERS` is deleted rather than left as a fallback.
   A fallback here is two authz truths that drift — the parallel-decider defect
   `task_grants.yaml`'s own header names.

## What the seals already hold, so this can be checked when it moves

`tests/cost/test_the_export_round_trips.py` — a second recipient's reader refused, each reader
served their OWN package, unidentified refused, every service identity refused, authorization
before existence. **The positive control is the load-bearing one**: without "beta's reader
fetches beta's package", a rule that refused everyone would pass every other assertion, and it is
also the only seal that catches a wrong scope lookup. Those seals should go on passing across the
move; if any of them has to be relaxed to accommodate the rail, that is a finding about the rail
rather than about the seal.
