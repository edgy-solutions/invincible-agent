# A policy refusal names its policy, the missing binding, and who can grant it

**Proposed by lane/gov, 2026-10-25, in answer to the architect's overnight directive of 10-24.
DRAFT RULE: it binds finance's three 409s and no other call site yet.**
Widened 2026-10-25 to the 409 that asks (architect, via Chris): see "The finance first instance".

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
- any call carrying a 401, 403 or 409 status: as `status_code=` or `status=`, or as the first
  positional argument (409 added 2026-10-25, after the ruling above);
- ADR-0049's in-band `_refusal("unentitled", ...)`;
- any dict whose `status`, `outcome`, `error` or `reason` is a refusal word.

An independent hand census of the same tree reconciles with it exactly:
- the hand census has 65 sites at 401, 403 or in-band;
- the detector counts 4 `auth.py` sites the hand census didn't;
- the hand census found 1 site, `notice_parts`, that the detector then gained.

**Correction (2026-10-25).** The hand census and the detector agreed because both missed the
same form. `PromotionRefused(..., status=403)` in `promotion.py` names its status as
`status=`. The "reconciles exactly" claim was wrong. The detector now reads that form.

**Re-measured on master `78315212`, 2026-10-25**, with 409 and the missed forms: 117 keys.
The finance three are now compliant, leaving **114 keys over 116 sites**, partitioned 73
NOT_POLICY and 41 PENDING. The seal's header carries the derivation. The table below is the
10-24 baseline.

On master `7a45a3cb` that gave **69 sites, 0 compliant**:

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
- **Thirteen more mutants (2026-10-25, the 409 widening)**, each killed by a named arm. Each of
  the three sites is reverted; the ask is ignored; the member grants are emptied; every slot
  maps to `code`; each repair branch and the options mapping is broken; `candidates` is
  ignored; `extra` is dropped; the exception's slots are dropped.
- **Seven mutants (#96)**, each killed by a named arm:
  - a dropped detector form;
  - an object key allowed;
  - the overlay ignored;
  - the relay trusting the engine;
  - an unknown family raising;
  - a pending site converted;
  - a new unclassified site.

## The finance first instance

**Ruled 2026-10-25 (architect, via Chris):** the finance failure is fin's canvas 409, the
`program` binding left unbound. It is not `get_artifact`, which this draft had guessed. The
ruling widens the rule:

> a refusal is any 401, 403, or 409 that asks the caller to choose or request something — a 409
> with an empty candidate list and no grantor is a non-compliant refusal.

A 409 about the target's own state asks for nothing, so it is not a refusal. Examples are
already resolved, terminal, immutable and moved on (`CONFLICT` in the seal). Neither is a 409
whose body names its one resolution (`NAMED`), or one for a verb that is not built yet
(`NOT_BUILT`).

**The three sites.** `unbound_required_slot` is raised at `/export/package`, at `/canvas/seed`
and at `seed_panel`. Each now goes through `policy_refusal(..., status_code=409)`.
`canvas_template.slot_refusal` derives the fields. At `/canvas/seed` it derives them from
fin's own `ask` (`_canvas_seed_ask`). The ask stays in the body unchanged, so the refusal
tells the caller nothing the ask does not already say.

| fin's ask | `policy_id` | `missing_binding` | `candidates` |
| --- | --- | --- | --- |
| options (the caller's menu) | `program_members` | `bind(program)` | the option values |
| no options and no policy (too many to offer, or nobody asked) | `groups` | `bind(program)` | `[]` |
| `switch_cell` | `groups` | `active_cell(<persona> · <domain>)` | `[<persona> · <domain>]` |
| `join_group` | `groups` | `member_of(<group> \| ...)` | `[]` |
| `declare_group` | `groups` | `a_group_granting(<persona> · <domain>)` | `[]` |
| `grant_member` | `program_members` | `can_view_program(program)` | `[]` |
| none, or `ask_unavailable` | `groups` | `bind(program)` | `[]` |

Export and `seed_panel` build no ask, so they give the default row.

**The family is the owning cell's.** A slot whose referent a cell owns (`REFERENT_CELLS`) is
chosen from what that cell sees, and a cell is granted by `groups`. A slot that no cell owns is
named under `code`.

**The menu is the member grant's** (architect, 2026-10-27). The options case names
`program_members`, because that is the grant that gates the menu. Measured 2026-10-25: no layer
filtered `fin#Program` members by caller. engine-o's enumerate gate reaches only sustainment
IRIs, and engine-fin's `EnumerateRequest` carried no caller. Ruled fin's defect; #113 fixes it.
engine-fin now lists and resolves only the members whose program the caller can view
(`can_view_program`). It filters before its limit and answers 503 when the check cannot be made.

So the options a caller sees are exactly what `program_members` grants them. A caller in the
owning cell who is granted none gets the `grant_member` repair. An ask with no options shows no menu the grant
bounds, so it keeps the cell's family. A slot no cell owns keeps `code`, menu or not.

**This rests on #113** (merged, `235a125b`, which also adds the `NP-MERIDIAN` row to
`policy/program_members.yaml`). Without that filter the options row would name a grant nothing checks.

**The hard-coded readers.** Ruled: "platform maintainers" is an acceptable grantor text now.
Moving `RECIPIENT_READERS` onto the policy rail is a queue item after #96.

## Open questions for the architect

1. **Restate `TerminalError` carries only a string.** For the 10 relay sites, does the
   `refusal` ride as JSON in the message, or does the SDK grow a field?
2. **May a refusal echo a key the caller itself sent?** For example a capability id from the
   request. The rule as drafted allows it for families that are not object-scoped. It forbids
   it for object-scoped ones even when the caller sent the key, because the key's presence in
   the refusal must not vary by existence.
3. **Which `candidates` may a caller be told?** An alternative is itself existence-bearing.
   Finance offers only what its ask already shows the caller (the enumerated menu, or the cell
   they hold). Every other site keeps `[]`.
4. **Code-held bindings: RULED 2026-10-25.** "Platform maintainers" is acceptable grantor text
   now. Moving `RECIPIENT_READERS` onto the rail is a queue item after #96.
5. **The sandbox overlay.** Should it name the sandbox's actual approver, or stay on the seed
   wording?
6. **Joining.** The ratchet reds on any new 401/403 site. If Lane 1's open heads (`01-207`,
   `01-208`) add one, the join needs that site classified in the same merge.

## What this does not do

- It changes no refusal site beyond finance's three 409s. Every other site stays as it is
  until its instance lands.
- It does not check that a compliant site names the *right* binding. That is each instance's
  own seal, starting with finance's.
- It does not check that a relayed refusal reaches the caller filled. That is each relay's seal.
- It does not cover other repos.
