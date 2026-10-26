# A policy refusal names its policy, the missing binding, and who can grant it

**Proposed by lane/gov, 2026-10-25, in answer to the architect's overnight directive of 10-24.
DRAFT RULE: it binds no call site yet.**

The code is in `src/iagent/authz/refusal.py`. The seal is
`tests/security/test_every_policy_refusal_names_policy_binding_grantor.py`. The seed grantor
map is `policy/grantors/`.

> "a missing binding today surfaces as red text nobody can act on. Draft the rule that every
> policy refusal names (a) the policy id, (b) the binding or role missing, (c) who can grant it
> -- and the test that enforces it across the refusal paths. Coordinate with fin on the finance
> case as the first instance; own the general rule."

## The rule

1. **What counts.** A *policy refusal* is a denial that some binding would have turned into an
   allow. The binding can be:
   - a row on the policy rail (`policy/*.yaml`);
   - a deployment config entry;
   - a table still held in code.

   A denial that no binding can lift is not a policy refusal, and it keeps its current body.
   That covers four cases: no identity at all; a route pinned to one service; separation of
   duties; workflow protocol state.
2. **What it carries.** Every policy refusal carries a `refusal` object. Its shape is the SDK's
   `iagent_mesh.refusal.Refusal`: `policy_id`, `missing_binding`, `grantable_by`, `candidates`.
   - `policy_id` is `<family>` or `<family>:<key>`, e.g. `capability_grants:mesh:startReview`
     or `config:DELEGATE_ON_BEHALF_OF`.
   - `missing_binding` is the relation the caller lacks, e.g. `can_invoke(mesh:startReview)`.
3. **Who can grant.** `grantable_by` is read from the deployment's grantor map and never typed
   at a call site. Who approves a grant is a fact about the deployment, not the platform.
   - The map is ADR-0036 composition through the SDK's `compose_rows`. ADR-0039 refuses a new
     composer.
   - The seed is `policy/grantors/`, worded neutrally. Overlays come from
     `GRANTOR_OVERLAY_DIRS`.
4. **The existence rule.** The fields depend only on the caller, the route and what the caller
   sent. They never depend on whether the target exists or what it holds.
   - An object-scoped family is named by its family alone: `asset_grants`, `program_members`,
     `ontology_compartments`.
   - The key goes to the log.
   - So a withheld target and an absent one still answer byte-equal (ADR-0047 §5.1, ADR-0049
     Ruling 4).
5. **Engines name, the BFF completes.** An engine holds no grantor map: engines import only the
   SDK, and `Dockerfile.agent` does not ship `policy/grantors/`.
   - An engine sends `refusal: {policy_id, missing_binding}`.
   - The BFF's `relay_refusal` fills `grantable_by` from the map. It overwrites anything the
     engine wrote there, because an engine may not speak for the deployment.
   - If an engine names a key on an object-scoped family, the BFF narrows it to the family.
6. **A refusal never becomes a 500.** A family the map does not carry still refuses with 403,
   and `grantable_by` says the row is missing.

**Compatibility with the 10-17 cost ruling.** `canvas.ENTITLEMENT_REFUSAL` stays as `reason`.
A `refusal` object naming only the family can sit beside it, and no lot reaches the wire.
`test_an_entitlement_refusal_names_no_lot.py` still holds, so no amendment is needed.

**The SDK's envelope.** It was built for this same directive on `lane/ca-0.9.11` (`26b1238`).
That branch is local only, and this repo pins 0.9.10. So the body is a dict with exactly the
model's fields, and on the bump it validates against `Refusal` unchanged.

## The population, and where it stands

The detector finds sites by form, not by name. It derives them from every tracked `.py` under
`src/` and `agent_fleet/`:
- any call carrying `status_code` 401 or 403;
- ADR-0049's in-band `_refusal("unentitled", ...)`;
- any dict whose `status`, `outcome`, `error` or `reason` is a refusal word.

An independent hand census of the same tree reconciles with it exactly:
- the hand census has 65 sites at 401, 403 or in-band;
- the detector counts 4 `auth.py` sites the hand census didn't;
- the hand census found 1 site, `notice_parts`, that the detector then gained.

On master `7a45a3cb` that gives **69 sites, 0 compliant**:

| bucket | n | detail |
| --- | --- | --- |
| not policy: no identity | 13 | token failures; a request with no caller id |
| not policy: pinned route | 9 | `not_doc_tools` ×4, `not_case_runner` ×4, `not_the_redeemer` |
| not policy: other structural | 12 | §5.1 delegate reads ×3; separation of duties ×2; no journalled audience ×2; protocol state ×2; retry is pin-driven; finance `package_export` ×2 (recipient scope and program mismatch) |
| **pending: own check** | **25** | capability_grants 6, groups 6, task_grants 4, config 2, code 7 |
| **pending: relay** | **10** | the BFF or an engine re-raising an upstream 403. Each must carry the upstream's `refusal` through. |

- **The ratchet is exact.** An unclassified site fails, and so does a listed site that is now
  gone or compliant. So the pending list shrinks as sites are fixed, and it never carries a
  dead row.
- **The detector has a positive control** on synthetic source holding every form.
- **Seven mutants**, each killed by a named arm:
  - a dropped detector form;
  - an object key allowed;
  - the overlay ignored;
  - the relay trusting the engine;
  - an unknown family raising;
  - a pending site converted;
  - a new unclassified site.

## The finance first instance

The finance failure the directive refers to ("the finance failure above") **was not in the
paste**. It is also not in any `sessions/` file from 10-22 to 10-24, and not on `lane/fin`. A
packet asks fin for it.

Until fin answers, the likely candidate is `finance_agent get_artifact`, a 403 reading
"not entitled to {scope}'s package".
- Its binding is `RECIPIENT_READERS`, a table hardcoded in `finance_agent/export.py` with no
  `granted_by`.
- So today its honest family is `code`. Its `grantable_by` can only say "the platform
  maintainers", which is why the table should move onto the rail.
- `package_export`'s two 403s are structural, not policy refusals.

## Open questions for the architect

1. **Restate `TerminalError` carries only a string.** For the 10 relay sites, does the
   `refusal` ride as JSON in the message, or does the SDK grow a field?
2. **May a refusal echo a key the caller itself sent?** For example a capability id from the
   request. The rule as drafted allows it for families that are not object-scoped. It forbids
   it for object-scoped ones even when the caller sent the key, because the key's presence in
   the refusal must not vary by existence.
3. **`candidates` stays empty.** An alternative is itself existence-bearing. Which candidates
   may a caller be told?
4. **Code-held bindings.** `RECIPIENT_READERS` exists in both finance and cost. Should moving it
   onto the rail be the finance instance's real fix, rather than naming `code`?
5. **The sandbox overlay.** Should it name the sandbox's actual approver, or stay on the seed
   wording?
6. **Joining.** The ratchet reds on any new 401/403 site. If Lane 1's open heads (`01-207`,
   `01-208`) add one, the join needs that site classified in the same merge.

## What this does not do

- It changes no refusal site. Every site stays as it is until its instance lands.
- It does not check that a compliant site names the *right* binding. That is each instance's
  own seal, starting with finance's.
- It does not check that a relayed refusal reaches the caller filled. That is each relay's seal.
- It does not cover other repos.
