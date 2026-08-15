# git-rails Topaz — structural summary of `C:\tmp\iagent-policy` (eyeball-diff this vs the real repo)

Source-authority for STRUCTURE (not content). Read from the local dir 2026-07-24 (dir dated Jul 15–21).
The human confirms work == this except the employee-id in `users.yaml`. **Diff the SHAPE below against the
real repo in five minutes; flag any drift** (the "created long ago" stale-record check).

## Layout
```
README.md · CODEOWNERS (policy/ @<org>/security-approvers)
.github/workflows/validate.yaml          # PR gate: runs the product image's validate_policy.py, no cluster
deploy/values-work.yaml                  # enables topazSeed.policySource: git, points at the repo
policy/  users.yaml groups.yaml domains.yaml asset_grants.yaml
         task_grants.yaml ontology_compartments.yaml capability_grants.yaml   # 7 files, ALL required
```

## Deployment mechanism (this is the "how a manifest change takes effect" answer)
- A **`topaz-seed` CronJob** (chart **≥ 0.3.14**) clones the repo every 10 min → `validate_policy.py`
  (malformed ⇒ whole run refused) → six diff-based syncs apply → **readback: every asserted grant must
  check TRUE or the Job FAILS**. Merge-to-`main` IS the grant; **removal is revocation**.
- `loadManifest: true` → the **chart-shipped ReBAC manifest** is loaded idempotently on every tick. The
  manifest is NOT hand-edited — it ships in the seed image. (Resolves my earlier configmap-vs-PVC unknown.)
- `overlayEnums: [domains.yaml]` → our classification vocabulary replaces the image's demo set.

## The 7 files → sync script → Topaz relation
| file | grants | Topaz |
|---|---|---|
| `users.yaml` | user → groups + default persona/domain cell | `topaz_sync.py` |
| `groups.yaml` | group → (persona, domain) cells | `topaz_sync.py` |
| `domains.yaml` | classification vocab (overlayEnums) | — |
| `asset_grants.yaml` | dataset `can_read` (reader) | `grant_sync.py` |
| **`task_grants.yaml`** | **HITL `can_act` audiences — `task_audience` actor relations, key = `task_kind:compartment`** | `task_grant_sync.py` |
| `ontology_compartments.yaml` | ontology_class viewer | `ontology_compartment_sync.py` |
| `capability_grants.yaml` | `direct_call` `can_invoke` (ADR-0029 sixth ns) | `capability_grant_sync.py` |

## Non-negotiables (from the README — these ARE the contract)
1. **`id:`/`grant_to:`/`subject:` are EMPLOYEE-IDs, not emails** — the IdP puts employee-id in the authz
   claim; an email-keyed grant exists in Topaz but never matches. (The identity divergence I banked:
   work = employee-id; sandbox = whatever sandbox's IdP emits — MUST verify before seeding sandbox grants.)
2. No AD/LDAP automation; every grant names `granted_by` (+ `reason` for asset/task/ontology/capability);
   anonymous ⇒ refused (exit 2, nothing applied). No permissive fallback cells. Removal = revocation.
3. `validate.yaml` `--overlay-enums` MUST mirror `deploy/values-work.yaml` `overlayEnums` (drift = CI
   validates one world, the cluster seeds another). Image tag pinned (NOT :latest) at/after chart 0.3.13.

## THE FINDING — `task_audience` is the existing `can_act` home; `disposition_item` was reinventing it
`task_grants.yaml` already grants **"WHO may approve/reject a class of HITL tasks"** via Topaz
`task_audience` actor relations, keyed `task_kind:compartment`. That is EXACTLY the grouped-review
can_act, and the compartment IS the domain. So the pcn disposition review fits the EXISTING mechanism:
audience `pcn_disposition:SUSTAINMENT`, granted in `task_grants.yaml` — **no new `disposition_item` type,
no new rego, no manifest edit.** The sealed HITL path already resolves a task's `audience` → `task_audience`
actors (cortex-bff). Reconcile the committed `can_act_via_topaz` (which used a bespoke `disposition_item`
rego) to check `task_audience` instead — single-decider, uses work's rails, less surface. **This is the
payoff of reading the rails before building: it deletes a type + a rego + a manifest edit.**

## Sandbox plan (build a SANDBOX repo of this SHAPE with SANDBOX content)
- New repo (same 7-file shape) seeded from this structure; content = sandbox (SUSTAINMENT domain; the pcn
  review audience; test subjects in sandbox's id format; AVIATION fixture for the discrimination 3rd leg).
- Enable `topazSeed.policySource: git` on sandbox (its seed CronJob exists but is default-disabled) →
  discrimination seal runs against config that ARRIVED by the mechanism.
- Two verifies before seeding: (a) sandbox subject-id FORMAT (email? username? sub-UUID?) — the identity
  knob; (b) `task_audience` is in the sandbox chart's shipped manifest (loadManifest path).
- Divergence README (one paragraph): structure syncs, content diverges, subject-claim knob named.
