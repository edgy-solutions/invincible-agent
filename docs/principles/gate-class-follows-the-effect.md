# The gate-class-follows-the-effect law

> **What a route DOES decides whether in-cluster reachability is an acceptable gate. Not who
> wrote it, not which repo it lives in, and not whether anyone is known to call it.**

| the route… | in-cluster reachability alone is… | note |
|---|---|---|
| **reads internal state** | **ACCEPTABLE, while the closure holds** | conditional, and the condition expires — see below |
| **writes authority** (grants, approvals, identity) | **NEVER** | |
| **writes effects or integrity** (state, routing, disposition) | **NEVER** | |
| **is an unused action route** | **verified-then-disabled** | verify across *all* repos first |

## Why this is a law and not a disposition

It was reached on 2026-08-10 as a disposition of **twelve known platform routes**. It was promoted
on 2026-08-11 for one reason, and it is the only reason that should ever promote a ruling:

> **It classified instances it was not written for, without amendment.**

Two findings arrived the next day from a different repo — `dag-tools`, which shares no code with
the platform and does not even depend on the mesh SDK — and both landed cleanly in its columns:

* `[[dag-tools-broker-register-unauthenticated]]` — `/api/v1/internal/register` takes `broker_url`
  from the request body and repoints any URN. **Integrity write → never.**
* `[[dag-tools-gateway-unverified-subject]]` — the DA data route never verifies its bearer and
  takes its authz subject from a header. **Not a gate class at all** — a missing precondition
  *underneath* one, which is how the rule earns its edge case rather than breaking on it.

A ruling that only resolves the cases it was drafted against is a disposition. One that resolves
the next case unprompted is a rule, and pretending otherwise means **every cross-repo instance
reopens a question that was already settled** — at the cost of an evening, each time.

## The closure condition on row 1, which is the part that expires

"Internal reads are acceptable in-cluster" is true **precisely while you author every pod in the
cluster.** That is a real control and it is not permanent. At the work deploy it weakens, and the
items riding on it are not small — an approval plane that checks nobody, a routing table anyone
can rewrite.

So row 1 is the only conditional row, and its condition must be **restated, not assumed**, every
time it is invoked. An `internal` route is honest only if the cluster boundary is still the trust
boundary. When that stops being true the row does not degrade gracefully — it inverts.

## Applying it to a new finding

Ask, in this order:

1. **What does the route change?** Nothing → row 1. Authority → row 2. State, routing, or
   provenance → row 3. Nothing, because nobody calls it → row 4.
2. **Is the closure still intact for this deployment?** If the answer is "at sandbox yes, at work
   no", the finding has two dispositions and must say so.
3. **File it with the class named**, in its own item, citing this law. Do **not** reopen
   `endpoint-gating-undeclared-routes-recommendation.md` — that packet is this law's *first
   application*, not its home. Cross-repo items stay visible as such via the `repo:` field.

## What this does not cover

Whether a caller carries a credential is a **separate axis** — see
`docs/plans/unminted-caller-enumeration.md`. A route can be correctly classified and still be
called by something unminted, and the two are fixed together only when one amplifies the other
(the `/write_item_state` precedent: gating without minting converts a working path into a
permanently broken one, because `_fail_terminal_on_4xx` makes a 401 non-retryable).
