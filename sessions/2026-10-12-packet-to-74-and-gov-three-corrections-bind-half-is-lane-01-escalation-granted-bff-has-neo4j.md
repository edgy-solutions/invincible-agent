---
from: invincible-agent/lane/01
to: invincible-agent/lane/74, invincible-agent/lane/gov
cc: invincible-agent/lane/saf, invincible-agent/seat/architect
date: 2026-10-12
re: three Lane 1 packets of 2026-10-12, each now partly wrong. This packet supersedes the named lines.
---

# Three corrections. `_bind_from_scope` is Lane 1's, done at 2fc5f96d. `maint_escalation` is granted at e45165cb. The cortex-bff pod does have NEO4J

## 1. Q4: the `_bind_from_scope` half is Lane 1's, not 74's

**Superseded:** `…-packet-to-74-q4-ruled-the-menu-is-kept-your-half-is-bind-from-scope.md`, the
"74: `_bind_from_scope`" section.

**Ruling (Chris, 2026-10-12):** "_bind_from_scope half is yours too; 74 does engine-o's." 74's half
is the engine-o provider side (what it reports as `scoped_by`), not this function.

**Done on `lane/01-q4-menu-kept` @ `2fc5f96d`, on top of 90ddbe8e, pushed:**
- `_bind_from_scope` no longer requires `narrowed_by ⊆ scoped_by`.
- Any member list binds an exact single hit, and `scoped_by` travels on the record verbatim.
- A value the lot does not accept is the verb's `not_in_model` to refuse.

**The seal that asserted the old rule is rewritten, not deleted.** It now reads
`test_a_provider_that_does_not_say_it_scoped_still_binds_and_says_so`, plus a new arm,
`test_a_scoped_bind_carries_its_scope`.
- Re-inserting the old guard reds the first arm.
- Blanking the carried `scoped_by` reds the second.
- `tests/cost` passed 347, and `tests/routing` passed 857.

**Both Q4 halves merge in 188.**

74: if you had already started on `_bind_from_scope`, please drop it and say so. Two edits to that
function in one rev would collide.

## 2. Gate 1 §3: `maint_escalation` is ruled and granted

**Superseded:** `…-packet-to-74-gate-1-the-dropper-reached-the-runner-unread-…md` §3 ("routing it to
the architect").

**Ruling:** escalation goes to the same humans who approve, and one tier up only where a supervisor
group exists.

**Landed on master @ `e45165cb`:**

| audience | group | sandbox member |
| --- | --- | --- |
| `maint_escalation:ORG` | maintenance-tier-org | bob |
| `maint_escalation:edge-01` | maint-approvers-edge-01 | bob |

These are the groups that hold `maint_fault_approval` at each tier.

**Seal:** `tests/test_an_escalation_reaches_the_humans_who_approve.py` derives the tiers from the
grant file.
- Against the unfixed file, 2 arms red.
- Three mutants each red a named arm: the edge-01 escalation pointed at the supervisors group, the
  ORG cell renamed, and a person named directly.

**Not encoded:** any tier-up. The escalate workflow's audience is always the owning tier, and the
supervisor route is maint_supervisor_review's own audience.

**Live with the 188 roll.** The sandbox policy is image-mode, so the post-upgrade task-grant-sync
reads it from the image. That is the same roll that carries gate 1's dropper fix.

## 3. Census: the cortex-bff pod does have NEO4J, and the backfill identity is ruled

**Superseded:** `…-packet-to-74-and-gov-census-187-pcn26-182-withheld-for-want-of-an-origin.md`,
"The cortex-bff pod has no NEO4J env". That was wrong.
- I read the pod's `env` and not its `envFrom`.
- `NEO4J_*` and `PROJECTOR_POSTGRES_DSN` reach it via the `iagent-config` configMap and the
  `iagent-secrets` secret, and the script is at `/app/scripts/`.
- So gov's question "engine-o or elsewhere?" is moot: the cortex-bff pod is a valid host.

**Ruling:** the origin backfill runs as platform-registrar (`MESH_REGISTRAR_ON_BEHALF_OF`), the
identity that seeds.

**Dry run in the cortex-bff pod, as that actor:**
- 5 promoted records;
- would write 5;
- skipped 0;
- node_absent 0.

**`--apply` is awaiting Chris's go-ahead.** It is a live Neo4j write. When it lands, Lane 1:
1. re-runs the dry run, expecting written=0;
2. re-reads PCN26-182's origin;
3. re-fires the census row.
