# ADR-0034 phase 1.3 — the routing witness. BEHAVIOURALLY CLOSED.

The trust table now has a production reader, and a change to it has been observed to move the
system. That is the ratification test from *"a policy artifact without a production reader is
unshipped policy"*, and 1.3 is the commit that lets the ceremony pass it.

## The four legs — route read from the Restate JOURNAL, never a log

| leg | table on the pod | rung | workflow that STARTED |
|---|---|---|---|
| 1 unpromoted | `trust@1c45c6dc296e` (committed) | `supervised` | `GroupedReview/…W13LEG1B/run` — suspended |
| 2 promoted `monitored` | `trust@d5efb97a1e48` (fixture) | `monitored` | `AutonomousReview/…W13LEG2/run` — completed, failure |
| 3 same format, mismatched `pipeline_version` | `trust@7e3720b4e13a` (fixture) | `supervised` | `GroupedReview/…W13LEG3/run` |
| 4 the deny's shape | fixture | `monitored` | 403 at `exec_dispatch_dispositions` |

**Leg 0 held before every drive:** the pod's table hash was read back and matched the fixture
intended, computed independently. A routing result is only attributable to a table the pod was
provably running.

**Leg 3 is the property the whole table exists to enforce** — a rung earned under one pipeline
version does not survive an upgrade — witnessed live for the first time, not just in unit tests.

## Leg 4 — the ceremony's before-picture, and it took two attempts to become one

```
Command: Run  exec_dispatch_dispositions
Failure 403: "caller 'svc:review-starter' is not authorized (can_invoke) for capability
              'mesh:dispatchDispositions' — failing and releasing."
```

Terminal at the gate · capability named · state released · **and the caller is the identity the
grant will target.**

The first attempt read `caller ''`. See "the empty caller" below — a before-picture naming the wrong
subject is not a before-picture.

### The identity is TOKEN-PROVEN, not asserted — witnessed, not inferred

The distinction matters because `can_invoke` against a self-reported caller is theatre: it would
name the right subject for the wrong reason, which is the fingerprint-laundering shape relocated
into the caller field. So the chain was read end to end:

| step | evidence |
|---|---|
| Keycloak signs the claim | `email: svc:review-starter` in the decoded JWT (mapper output) |
| BFF verifies and reads it | `get_current_user` → `current_user.authz_id` |
| the client CANNOT supply it | `approver` is **not a field** on `ReviewStartRequest` |
| BFF stamps it | `"approver": current_user.authz_id` |
| starter threads it | `"authz_id": approver` |
| the gate checks it | deny names `svc:review-starter` |

The subject at the gate **equals the subject in the token**. (Note the entitlement claim is `email`,
which is the already-filed `email-as-identity` assumption — a work-deploy concern, not a 1.3 one.)

## Two findings the witness caught that a green suite could not

### 1. The passthrough pin fired for real, within minutes of existing

Leg 1's first run routed to `GroupedReview` — **correctly, and for the wrong reason.** The readback
showed `format=(none) pipeline=(none)`: engine-a had been rolled, cortex-bff had not, so the
admission facts died at the BFF hop and the starter fell to the born-supervised floor.

Right answer, wrong reason, **failing safe and therefore invisibly** — the exact class pinned in
`test_review_payload_passthrough` hours earlier. The leg was VOIDED and re-run; a witness that
passes for an unwitnessed reason is void.

It also re-demonstrates the one-artifact-coherence ruling on a new surface: a two-service
fact-threading change where one service rolls and the other does not yields a silently degraded
composite. Here "degraded" happened to mean "safe", which is what made it invisible.

**Inventory item promoted from nice-to-have to proven-necessary:** the starter cannot distinguish
*facts absent* from *facts present, rung supervised*. An `admitted_by: policy-default-missing-facts`
variant would make the degradation legible in the audit trail — the same move as
`join:pending-proxy`. A human catching this in a log line is not a detection mechanism; it is luck
with good habits.

### 2. The empty caller — the ceremony would have been a no-op

Leg 4's first run denied `caller ''`. `_run_definition` derives identity from
`request.get("authz_id") or caller_email or ""`, and ReviewStarter's `workflow_send` carried
neither.

Workflow 1 never exposed it: its gate is the audience `can_act` on the human step, so `direct_call`
is unique to workflow 2 and this identity had never been needed. **No offline test could have found
it** — every unit test supplies its own identity, which is the supply-your-own-provenance trap one
service out. It took the first live run of a path that had never had one.

**Why it blocked the ceremony rather than merely being a bug:** acceptance is *"watch deny flip to
allow for THIS initiator."* A deny against `''` is not the before-side of an allow granted to
`svc:review-starter` — different subjects. The grant would have landed, the deny would have
persisted, and the system would have looked exactly as designed. Fixed in `b99424c`, which grants
nothing; sealed by `test_initiator_identity_reaches_the_workflow_send`.

## Settlement — no residue

The fixture promotion came OFF the running system by rolling engine-a back onto the baked table,
with a readback confirming `trust@1c45c6dc296e` and `witness/pcn/v1` resolving `supervised` again.

*A fixture promotion that outlives its witness is a live trust elevation wearing test clothes.*

## Operational note earned here

**A new Restate service is not discovered by a pod roll.** `AutonomousReview` was absent from
`restate deployments list` after the image shipped it; every `workflow_send` to workflow 2 would
have failed as service-not-found, and the witness would have measured a registration gap while
looking like a routing failure. `restate deployments register <endpoint> --force` re-discovers.
This is the registry-startup-invariant item, met in the wild.

## The ceremony's checklist now stands at three legs

1. **Grant landed** — `mesh:dispatchDispositions` to `svc:review-starter`, with the trust-table
   promotion, as one governed act.
2. **Fingerprint trust closed** — `format_fingerprint` is caller-asserted and unverifiable; the
   backstop is the deny, and the deny expires at ratification (see `autonomous_review.yaml`).
3. **deny→allow witnessed** for the token-proven identity, while every other caller stays denied.

Every one of the three exists because a witness caught what a green suite could not.
