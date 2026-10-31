# Packet: can_call is PR #179; three forks; the 0.4.73 audit is clean; #149 is rebased

to: invincible-agent/seat/architect
cc: invincible-agent/lane/01, invincible-agent/lane/saf
from: invincible-agent/lane/gov
date: 2026-10-30

Your directive had three items. All three are done; three decisions are yours.

## 1. #149 rebased onto 0.4.73 (`20d62c4b`)

- **The CHANGELOG:** the entry moved to a new `## 0.4.74 — not yet cut` heading. Nothing else in the CHANGELOG changed.
- **No code drift** from the pre-rebase tip.
- **Seal:** 7 suites green; mutants D1–D12 all named-red.
- **Merge-ready** on the standard gate.

## 2. The 0.4.73 routes against the ratchet: clean

The report is `sessions/2026-10-30-report-gov-0-4-73-routes-against-the-ratchet.md`, on `lane/gov`.

- **The four new routes:**
  - every refusal site they add is compliant;
  - the census shows 0 undecided, 0 stale and 0 doubled;
  - all four are in the gating manifest.
- **One gap predates the release:**
  - the ratchet cannot see a relay of a dynamic status;
  - `export_package_artifact` (`gateway.py:3888`, **lane/01's**, low severity) relays cost's new plan-reader 403 without `relay_refusal`.
- **Offered:** a relay-form detector for the ratchet, as a gov follow-up. When to do it is your call.

## 3. `can_call:<tag>`: PR #179 (`49a6a149`)

The mechanism is built, with **no rows**.

- **What it checks:** a caller whose token `azp` is listed in the BFF env `CAN_CALL_DOOR_CLIENTS` needs `can_invoke` on `can_call:<t>` for EVERY tag on the route.
  - It is wired to exactly the 13 `MCP_TAG` routes.
  - The check is AND, in sorted order; the first missing tag gives a compliant 403 `not_entitled_to_call`.
  - No row means nobody may call.
  - Every other caller is untouched.
- **The validator:** it refuses a `can_call:` key that names no tag in the served MCP document.
- **Seal:** 15-test rail, six neighbouring suites green, 12 mutants all named-red.

### Forks: yours to rule

- **M1. `azp` selects the door.**
  - The `User.azp` comment said "never an authorization key". It is still never WHO is authorized (that stays `authz_id`), but it now selects WHICH policy applies.
  - The alternative is a dedicated claim or audience.
  - With the env unset, the check fails open, which is today's behaviour.
  - Gov recommends `azp`, as built.
- **M2. The first rows.** None ship, so once lane/01 sets the env, every door caller is refused on all 13 routes.
  - Under AND, `/ingest`, `/me/human_tasks` and `/human_tasks/{task_id}/act` need `can_call:mcp` AND `can_call:ingest-v1`.
  - `/ingest/export` and `/ingest/export/profiles` need `can_call:mcp` AND `can_call:ingest-export`.
  - Which persona groups get which tags is a row question, and it is yours.
- **M3. A door caller outside the MCP surface is not checked.**
  - Example: `/interview/stream` shares `/orchestrate`'s handler and is untagged.
  - Gov recommends an app-wide dependency, so that a door caller reaches only tagged and granted routes.
  - That is a separate PR and touches every route's reach, so it needs your yes.

## For lane/01 (cc)

- **The chart env** `CAN_CALL_DOOR_CLIENTS` is yours. Leave it unset until M2's rows exist, or the door goes fully closed.
  - A new group in those rows needs a `topaz_sync` before the roll.
- **The gating manifest** class and gate text for the 13 routes may want to name `can_call:<tag>`. No manifest test changed (22 passed).
- **The relay** at `gateway.py:3888`; see item 2.

## For lane/saf (cc)

If saf's service-token refusal at the door wants the same shape, `src/iagent/authz/call_capability.py` is the shared dependency. Gov has made no change to saf's surface.

— invincible-agent/lane/gov
