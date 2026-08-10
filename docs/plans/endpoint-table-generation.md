---
id:         endpoint-table-generation
status:     open
owner:      agent
blocked-on:
closed-by:
code-site:  tests/test_route_census.py
repo:       invincible-agent
summary:    Generate the README endpoint table from the live route census instead of asserting it.
---

# Endpoint table — generate, don't assert

## Why — and the propagation is the argument

The README adjudication (2026-08-09) walked the ADR count, the identity story and the durability
claim against code, correcting each. It then **passed over a wrong endpoint row**: Engine E
serves `/query_graph`, not `/query_proxy`.

Found the next day by enumerating live routes during a litany repair — and found only because
the litany's probe map had copied the wrong path **from the README**. The doc error became a
tooling error, which produced a leg-5 failure that read as a *fleet* defect until the cause was
traced back.

Two lessons, the second being this packet's reason:

* **Format carries unearned authority.** A table reads as data even when it is assertion. The
  adjudication's own rule was "every claim verified by read", and an endpoint table is precisely
  the claim that looks too obvious to check.
* **Doc errors do not stay in docs.** They are copied into probe maps, runbooks and tests, where
  they present as defects in the system rather than in the record.

## The move

`tests/test_route_census.py` already enumerates `app.routes` across every constructed app. Make
it the source for the README's endpoint table — generated, with a drift test. Same discipline as
the workflow schema (ADR-0039) and the board (ADR-0040): generated-not-asserted, plus a test that
keeps the generated artifact honest.

## Acceptance

- The table regenerates identically from the census (byte-comparable).
- The drift test bites, proven broken-on-purpose.
- A wrong path in the README becomes a **CI failure**, not a reader's afternoon.

## Note on scope

The census sees apps **as constructed in this repo**. Routes added by middleware at runtime are
outside its reach, so the generated table should say what it covers rather than implying
completeness — the same disclosure the board's coverage line makes.
