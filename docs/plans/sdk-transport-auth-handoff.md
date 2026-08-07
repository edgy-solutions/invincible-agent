# SDK transport auth — handoff (prototype built, tested, ready to roll)

**Status: complete and green, not a description.** `iagent-mesh-sdk@68e28c0` (pushed) carries the
working shape; 81 SDK tests pass, 12 of them new and double-sided. This document is the rollout,
the finding, and the sequencing — the code is the read, already transferred.

---

## 1. THE TWO-SEAM FIX, AS BUILT

One library, two seams, so every engine inherits both obligations with **zero lines of engine
code** — the same way telemetry landed in the shim.

### Inbound — `iagent_mesh/transport_auth.py`, applied at the FastAPI factory
`MeshTool.__init__` now passes `dependencies=[Depends(make_transport_auth_dependency(...))]`.

| posture | behaviour |
|---|---|
| **OBSERVE** (default) | validate whatever arrives, log the caller posture per request, **refuse nothing** |
| **REQUIRE** | 401 absent / 403 present-but-invalid / 200 verified |

* **401 vs 403 is deliberate.** "You sent nothing" and "you sent something I could not trust" are
  different operator problems; collapsing them costs an incident's first hour.
* **Signature verification is mandatory for `verified`.** With no key configured the token is
  reported UNVERIFIED **with the reason named** — readable for logs, illegal to authorize on. A
  decode without signature checking is the presence-check defect wearing a JWT's clothes.
* **Subject from `USER_ENTITLEMENT_CLAIM`**, never hardcoded `email` — work names an employee-id
  claim, and hardcoding is the email-as-identity defect.
* **Its own flag (`REQUIRE_TRANSPORT_AUTH`), not `ENABLE_AGENTIC_AUTH`** — see §2; that flag gates
  two Topaz *asks* and was found to gate no JWT verification at all. Overloading it would recreate
  the three-jobs hazard on a flag whose blast radius was just corrected downward.

### Outbound — `MeshClient` mints at use
Defers to the platform's `agent_fleet.utils.service_identity.mint_service_token` when importable:
**one mint implementation, not two**, because two is two places for the claim contract to drift.
Both paths announce: `outbound identity: svc:<name> (minted)` vs
`MESH_DEV_TOKEN (static, dev fallback)`, so a static token in a real deployment reads as the
anomaly it is.

### Scaffold — identity is a paste
`iagent_mesh/identity_stanzas.py` + scaffold emission of `IDENTITY.yaml`: the two blocks a new tool
pastes into the platform repo (`keycloak.serviceClients`, `policy/users.yaml`). The realm-reconcile
job then creates the client on **any** cluster at deploy. Marginal cost of engine N+1's identity:
two reviewed YAML blocks. **No grants are emitted** — a scaffold that pre-granted its own identity
would ship the confused deputy by default.

**Cross-repo pin**: `invincible-agent/tests/test_cross_repo_contracts.py` asserts the SDK's emitted
keys are exactly what the reconcile job and realm import read, **both directions**, with a
positive control that fails if the SDK isn't checked out (a vacuously-passing cross-repo pin is
how one quietly stops pinning). Verified red on a producer-side `clientId → client_id` rename.

---

## 2. THE FINDING — three kinds of nothing that all counted as "present"

The manifest counted dark-launched gates as *"gate present, not none"*. That definition admitted
**three members**, all **worse than absent**: they survive an audit-by-name and train everyone to
believe a property that does not hold.

| # | species | instance |
|---|---|---|
| 1 | **importable-but-unapplied** | `core/authz.py`'s `auth_dependency` — imported by nobody, applied nowhere; `data_analyst/main.py:195` records the decorator "was removed from this handler". **Flipping `ENABLE_AGENTIC_AUTH` turns on no JWT verification anywhere.** |
| 2 | **presence-only** | the SDK's `/execute` refused an *absent* header and accepted **any** value present — `Bearer anything` passed; `LOCAL_DEV` bypassed even that |
| 3 | **assumed-elsewhere** | the DA read path's engine-side authz removed in favour of a gateway gate keyed on a **payload field the caller writes** |

**Amended definition** (now in the manifest, above the original): present = **applied** at an
endpoint **AND validating the credential's content** **AND flag-gated**.

**How presence is verified from now on: import-graph + application-site read, never a name-grep.**
My own fleet enumeration grepped `Depends|verify_jwt|auth_dependency` and missed member 2 entirely
— *the weakest gates are the ones grep cannot find, because they were never built as gates* and
carry none of auth's vocabulary.

---

## 3. ROLLOUT SEQUENCING — expand, migrate, contract

Transport auth is a live-identity-surface migration. Requiring auth before callers present it is
the empty-caller incident executed fleet-wide on purpose.

1. **SDK bump.** Engines pick up OBSERVE on their normal deploy cadence — no coordinated rollout,
   no flag day. Nothing refuses; every request starts logging its caller posture.
2. **The gauge accumulates.** `caller: <id> (<reason>) posture=OBSERVE` per request turns *"all
   callers migrated"* from an enumeration someone vouches for into **a number you read**.
3. **Outbound migration, per caller.** Each gets an identity (stanzas → reconcile job) and a mint.
   Known population from the 2026-08-07 sweep — eight modules with zero auth references; four
   target Engine O (`decision_record_writer`, `review_starter`, `policy_rules_client`,
   `review_composer`), one the mesh-registrar, one the supervisor, two are engines' own
   Restate-ingress proxies (not FastAPI-gated). **Open naming question for the mint contract:**
   the Engine-O callers live *inside engine-a's process* — one identity per **process** or per
   **module**? Recommended: per-process credential, per-module attribution in the payload — the
   credential-authorizes / provenance-attributes split.
4. **Contract phase.** `REQUIRE_TRANSPORT_AUTH=true` **only when the unverified-caller count reads
   zero.** The flip is a read, not a vote.

---

## 4. THE PERIMETER FINDING — second instance of a named class

`MeshClient` used to **raise** without `MESH_DEV_TOKEN`:

> *"Ensure you are running within the secured JupyterHub environment."*

That is the architecture's old trust model **preserved in prose**: a long-lived credential whose
safety rests on **where the process happens to run** — security assumed at a boundary the component
does not control. Same shape as the DA seam deferring to a gateway it could not verify, and this
one sits in the SDK **every future engine inherits**.

**Minting does not modernise the token — it removes the perimeter dependency.** Afterwards the
SDK's outbound trust rests on an identity the platform declares and reconciles, and the caller is
authenticated wherever it runs.

---

## Evidence worth carrying (not anecdote)

**The double-sided proof paid on day one.** `from __future__ import annotations` makes annotations
strings that FastAPI resolves against **module** globals; `Request` imported inside the factory left
`"Request"` unresolvable, so FastAPI treated it as a **query parameter** and **every request
422'd**. A dependency that 422s on every call is a fleet-wide outage shipped as a library bump —
exactly what OBSERVE's default exists to prevent — and the *permissive-side* tests failed
instantly, pre-ship. **That is why the permissive side gets tests: its regression is an outage.**

*SDK convention line, for the next factory-dependency author:* **FastAPI resolves string
annotations against module globals — dependency signatures must import at module level or fail as
phantom query params.**

**Three existing tests were rewritten, not deleted.** They asserted the *old* contract
(presence-only 403; `MeshClient` raising without a static token) and failing was correct. Each
rewrite records the old intent and points at where refusal now lives — amend-above applied to test
code, so a future reader can tell *"removed deliberately"* from *"weakened to pass"*.
