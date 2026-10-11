---
id:         user-token-reaches-specialists
status:     open
owner:      lane/01
blocked-on: phase 2 needs the engine lanes' consent (it changes who cost, finance, safety and docs see); phase 3 needs an SDK change (lane ca)
closed-by:  
code-site:  src/iagent/identity_vault.py:197-285; src/iagent/defs/dynamic_supervisor.py:1431,1592,1681,1878,3299; src/iagent/gateway.py:3137,6875
repo:       invincible-agent
summary:    Gov Q3 asked whether specialists may keep identifying the caller by a body-asserted user_email. Short answer: no, but the obvious fix (widen _CALLER_IDENTITY_VERBS) breaks every multi-subtask run. The vault reference is single-use, and every subtask is its own process. Phase 1 makes one reference per fan-out slot. Phase 2 widens the verbs with the engine lanes. Phase 3 has engines verify what they receive.
---

# The user's token reaches the specialists: one vault reference per fan-out slot

Asked by gov (Q3, `ia-gov/sessions/2026-10-10-report-gov-origin-at-read-and-on-promotion.md`):
> Engine-o identifies the caller by the body-asserted `user_email` … specialists get no user token.
> Acceptable, or does this wait for the user token to reach specialists?

**Answer.** It is acceptable as a stopgap and wrong as an end state.
- **Why it is safe today:** the body field is written by the supervisor from run config that the
  BFF fills from the verified JWT. Seal 5aeeec21 shows that a body-asserted `user_email` does not
  change what the gateway hands the supervisor.
- **Why it is wrong as an end state:** a specialist trusts that field because it trusts the
  network, not because an IdP signed it. R-089 already names the destination: forward the
  person's own token, with the IdP as the root of trust.

This note says how to get there. It also says why the one-line version of the fix would break
production.

## The chain today (measured on `c56a0ca2`)

1. **The BFF launches the run** through Dagster `launchRun`.
   - Run config carries `user_id`, `user_email` (which is `current_user.authz_id`), persona,
     `entitled_domains`, `trace_id` and `session_id`. It carries **no token**; that is ruled
     (`identity-propagation-must-not-cross-run-storage`).
   - The caller's bearer goes into the in-process vault: `VAULT.stash(run_id, caller_token,
     subject=user_email)` at `gateway.py:6875`. The TTL defaults to 600 s
     (`identity_vault.py:99`, overridable by `IDENTITY_VAULT_TTL_SECONDS`).
2. **The supervisor plans and fans out.** It yields one `DynamicOutput(mapping_key=f"task_{idx}")`
   per subtask (`dynamic_supervisor.py:~229`). There is **no cap** on the number of subtasks.
3. **Each `execute_subtask[task_i]` runs in its own process.** It uses `multiprocess_executor`
   (forkserver, at most 5 concurrent); `in_process_executor` is used only under `IS_DEV`
   (`dynamic_supervisor.py:~3684`).
4. **Per subtask, the dispatch identity is chosen.**
   - If the verb is in `_CALLER_IDENTITY_VERBS = {seedPortfolioCanvas, seedCanvas, explain}`
     (`:1592`), `_redeem_caller_token` (`:1681`) calls `POST /internal/identity/redeem`
     (`gateway.py:3137`) as `svc:supervisor`. It gets the caller's token, or raises
     `CallerIdentityUnavailable`.
   - Otherwise `_telemetry_headers` (`:1431`) mints `svc:supervisor`.
   - The dispatch is `requests.post` at `:3299`. Its body also carries `user_email`,
     `entitled_domains` and `user_id` (`:3058-3070`).
   - The Engine A fallback (`:1878`) always goes as the service.
5. **Redemption is atomic and happens once, ever** (`identity_vault.py:220-285`).
   - A second redeem of the same `run_id` returns `ALREADY_REDEEMED` and logs `REPLAY`. That is
     invariant 2's compromise tell, and it is deliberate.
6. **Engines** authenticate transport through the SDK's `make_transport_auth_dependency`.
   - The key is static (`MESH_JWT_PUBLIC_KEY` / `KEYCLOAK_PUBLIC_KEY`). **The chart sets
     neither**, so engines decode without checking the signature.
   - `verify_aud=False`. The posture is OBSERVE; only `REQUIRE_TRANSPORT_AUTH` rejects.
   - cost (`agent_fleet/cost_agent/main.py:719`) and finance (`finance_agent/main.py:937`)
     authorise on `current_caller().authz_id`. Under the service token that is
     `svc:supervisor`, not the person.
   - safety refuses a request that has no person (`safety_agent/measures.py:477`, `NoPerson` → 422
     `no_person`).

## Why "just widen the verb set" breaks production

**One reference, one redemption, N processes.** Say a question fans out to two subtasks whose
verbs are both in the set.
- `task_0` redeems and gets the token.
- `task_1` runs in another process. It cannot see `task_0`'s memory, and its redeem returns
  `ALREADY_REDEEMED`. The BFF logs it as a replay, and the subtask fails with
  `CallerIdentityUnavailable`.
- So widening the set turns every multi-specialist question into a partial failure, and the
  audit log reports each one as a compromise.

**This is already latent today:** a plan with two `explain` steps, or `explain` plus a `seedCanvas`
step, hits it now. I have not seen it live, because I have not walked a plan with two caller-identity
verbs. Phase 1 seals it either way.

**Two tempting workarounds are both refused:**
- *Pass the token from the first subtask to the others* through op outputs or the IO manager.
  That writes it to run storage, which is ruled out permanently.
- *Have the supervisor sign an attestation* of who the person is. The supervisor would then be
  minting an identity assertion. That is the forgeable-actor shape the vault plan's
  hand-roll prohibition refuses, and it is not rooted in the IdP.

## Options

| | design | replay tell | cost |
| --- | --- | --- | --- |
| **A** | The BFF stashes **one single-use reference per fan-out slot**, `(run_id, k)` for `k < SLOTS`. `execute_subtask[task_k]` redeems slot `k`. Unused slots expire at TTL. | Kept exactly, per slot: a second redeem of `(run_id, k)` is still the compromise tell. | N copies of one token in BFF memory for ≤600 s. A subtask with `k ≥ SLOTS` gets `CallerIdentityUnavailable("slot_out_of_range")`, which is loud. |
| B | One reference, redeemable up to N times while the run is STARTED. | **Lost.** A second redeem is now normal, so a stolen `svc:supervisor` credential can drain it silently up to N. | The BFF needs to query run status on every redeem. |
| C | The supervisor attests the person, and engines trust the supervisor. | n/a | **Refused** (see above). |

**Recommendation: A.**
- It is a strict generalisation of the ruled vault. With `SLOTS=1` it is byte-identical to today.
- Every invariant in `identity-propagation-must-not-cross-run-storage` still holds per key:
  single-use, TTL, launcher cross-check, consume-on-mismatch, audit line.
- It stores the same token for the same hop, so the vault plan's scope boundary ("never a second
  *kind* of token") is not crossed.

**The slot is the mapping key.** `context.get_mapping_key()` is `task_<idx>` and is Dagster's own
record, the same reasoning `_redeem_caller_token` already applies to `context.run_id`.
- A subtask re-executed under the same run (an op retry) replays its slot and fails loudly. That
  is correct: a retry should not be a silent second use of a person's credential.
- No `RetryPolicy` is set on `execute_subtask` today, so nothing changes.
- A run re-execution gets a new `run_id`, finds no reference, and gets `NOT_FOUND`, as today.

## Token lifetime

- **Keycloak:** `accessTokenLifespan` is 3600 s (`keycloak-configmap.yaml:14`).
- **Vault:** the TTL is 600 s from launch.
- **Two late cases, one rule:**
  - A subtask that starts more than 600 s after launch (a long plan, a queue behind
    `max_concurrent=5`) finds its slot evicted → `EXPIRED`/`NOT_FOUND` → loud failure.
  - A slot redeemed in time can still carry a token whose own `exp` falls before the specialist
    answers. Once engines verify `exp` (phase 3), that request is a 401.
- **Phase 1 rule:** a slot's `expires_at` is `min(stash + TTL, token.exp − skew)`.
  - The vault never hands out a token that is already dead, and it never extends one.
  - `_expiry_of` in `agent_fleet/utils/service_identity.py:83` already reads `exp` without
    verifying it; the vault does the same.
  - **No refresh, ever.** Refreshing would need the refresh token, and that is a second kind of
    credential in the vault. It is refused.
- A question that outlives its asker's access token fails loudly, and the person asks again. That
  is the honest behaviour.

## Phases

### Phase 1 — slots (Lane 1, this PR series; no engine sees anything new)

- **`IdentityVault.stash(run_id, token, subject, slots=1)`** stores keys `run_id#0 … run_id#(slots-1)`.
  - Each key has its own entry, tombstone and expiry. Expiry is bounded by `exp` as above.
  - `redeem(run_id, claimed_launcher, slot=0)` redeems one key.
  - With the default `slots=1, slot=0`, behaviour and audit lines are identical to today.
- **BFF:** stash with `slots = IDENTITY_VAULT_SLOTS` (default 8). The redeem route accepts an
  optional integer `slot` in `[0, SLOTS)`; anything else is a 422.
  - The route is declared in the gating manifest (`endpoint_gating_manifest.yaml:1828`). Phase 1
    changes its body, not its gate. The plan `gateway-identity-redeem-route-undeclared` still reads
    `status: open`. I did not check whether it is stale or names a gap the manifest entry does not
    close.
- **Supervisor:** `_redeem_caller_token` sends `slot` parsed from `context.get_mapping_key()`.
  - A missing or unparseable key is `CallerIdentityUnavailable("no_slot")`, never a default to 0,
    because defaulting would make two subtasks contend for slot 0, which is today's defect.
  - The verb set is **unchanged**. Phase 1 makes the existing verbs safe in multi-subtask plans,
    and nothing more.
- **The Engine A fallback (`:1878`)** carries the caller token when the subtask redeemed one. It
  still never redeems on its own.
- **Seals:**
  - two subtasks with caller-identity verbs both receive the token, and neither logs `REPLAY`;
  - a second redeem of one slot is still `ALREADY_REDEEMED`;
  - an out-of-range slot is refused;
  - expiry is bounded by `exp`;
  - `slots=1` is byte-identical to the old audit line.
  - **Mutants:** slot ignored (every key is `#0`), the `exp` bound dropped, `no_slot` defaulted
    to 0. Each must go red on its named arm.

### Phase 2 — widen the verbs (needs the engine lanes)

- **The decision is per verb, not "all verbs".** For each verb, putting it in the set makes its
  engine see the person instead of `svc:supervisor`. That changes the engine's answers, and
  usually that is the point:
  - **cost** and **finance:** `current_caller().authz_id` becomes the person. Every grant they
    check today is checked against the service's grants.
  - **safety:** `NoPerson` → 422 stops. Program filtering starts filtering *for* someone. That is
    the precondition saf's program filter has been waiting on.
  - **ontology (engine-o):** the body `user_email` and the token agree. Gov Q3 then closes with
    the token as the authority.
- Each engine lane owns its seals. Lane 1 sends a packet per engine with the verb list, and widens
  only on that lane's reply. **Another lane's red seal is a stop, not a widen.**
- Engines then authorise on `require_authz_id()` (the SDK's verified caller), **never** on the body
  `user_email`. The body field stays for logging only, and goes in a later cleanup.

### Phase 3 — engines verify what they receive (SDK, lane ca)

- Today, an engine that receives the person's token still cannot tell it from a forged one: it has
  no key, and no audience check.
- **The SDK needs:**
  - JWKS fetch with key rotation, not only a static key;
  - an `aud` check against the engine's own client id;
  - an `exp` check.
- **Keycloak needs** an audience mapper on `cortex-ui` that adds the specialist clients, or a
  per-engine audience scope. **Token exchange stays ruled out**; this is the token Keycloak
  already issued, with an audience it already lists.
- After that, `REQUIRE_TRANSPORT_AUTH` flips per engine. That is a values change, the same shape
  as the #14 broker flip.

## What this does NOT change

- No token in run config, op outputs, the IO manager or logs.
- No `act` claim, and no delegation. The provenance obligation (trigger read from the run, not
  from the token) stands unchanged.
- No refresh tokens in the vault.

## Stale homes found while writing this (not corrected here; their owners' files)

Both say `explain` is *not* in `_CALLER_IDENTITY_VERBS`. It has been since `f843d2d8`
(2026-10-01).
- `agent_fleet/docs_agent/entitlement.py:28`: docstring precondition 1 of the docs flip.
- `docs/plans/enable-agentic-auth-flip-packet.md:113`: consequence 1.

`docs/adr/ADR-0050…md:145` quotes the set as `{"seedPortfolioCanvas"}`. That is a dated quote in an
ADR, and it is left as history.

## Not checked

- I did not walk a live plan with two caller-identity verbs. "Already latent" is read from the code,
  not observed.
- I did not measure how long a fan-out queues behind `max_concurrent=5` on the sandbox, so I do not
  know how often the 600 s TTL is reached in practice.
- I did not read the SDK's `make_transport_auth_dependency` body for this note. The claims about
  the static key, `verify_aud` and the posture come from the 10-11 identity-chain survey.
