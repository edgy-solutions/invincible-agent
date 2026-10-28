# Handoff: lane/gov, 2026-10-28 (evening)

to: invincible-agent/lane/gov (worktree ia-gov)
from: invincible-agent/lane/gov, 2026-10-28

This replaces `2026-10-28-handoff-lane-gov-rulings-4-and-5-open-adr-0062-section-5-next.md`.

## State

| branch | tip | PR | status |
| --- | --- | --- | --- |
| `lane/gov` | this commit | none | handoff carrier |
| `lane/gov-drop-grants-alert-processors` | `d4508b26` (on master `5522d8d2`) | #134 → master | can_drop rail. Seal 15; 13 of 13 mutants named-red. CI not yet read. |
| `lane/gov-recipient-readers-rail` | `94139c4f` | #127 → master | Ruling 4. CI green (20 pass, 3 Release skip); that CI runs lint and builds, not pytest. |
| `lane/gov-sandbox-grantor-overlay` | `78f135b1` | #126 → master | Ruling 5, rides 0.4.72. CI green, as above. |
| `lane/01-adr-0062-mesh-owns-its-repositories` | `511e5927` | #123 (lane/01's draft) | gov wrote §5 and pushed it there (fast-forward from `93ea39af`), with trailer `Lane: ia-gov/lane/gov`. |

**#134 and #127 conflict textually** in `policy/sync/validate_policy.py` and CHANGELOG. Gov rebases whichever merges second. #126 merges clean with both.

## The 10-28 alert-processors directive (architect via Chris, verbatim)

> 1. gov: a group `alert-processors` on the policy rail (groups.yaml, seed + sandbox overlay with
> alice in it), and a policy `can_drop:<content_kind>` granted per group -- configurable per
> deployment in Topaz, nothing hard-coded. Default: pcn and pdn droppable by alert-processors
> only; other kinds unchanged.
> 2. Lane 1: the ingest door checks can_drop for the declared kind at drop time; refusal carries
> the envelope with grantable_by; task-grant-sync carries the new group.
> 3. cortex: the drop control shows only the kinds the caller may drop (from entitlements), and a
> refused drop renders the envelope with "Request access". Test: a non-member sees no PCN/PDN
> option.
> Work gets the grant rows for his overlay in the packet.

**Gov's half is #134.** It takes Lane 1's names: `capability:can_drop:<kind>`, `can_invoke`, and `capability_grants.yaml` with `grant_to_groups`.

**One departure.** The gated set is "the Topaz object `capability:can_drop:K` exists", not a key on the content kind. The SDK's `ContentKindRegistration` forbids extra fields.

## Packets placed (untracked)

- **`sessions/2026-10-28-packet-to-lane-01-and-cortex-can-drop-names-taken-gated-set-lives-in-topaz.md`**, in both the master tree and `cortex-ui/sessions/`. It carries:
  - the contract and the door's two reads (read 1 must raise, not swallow);
  - gov's answers to cortex's gaps: check every kind-setting site, against the dropper;
  - three architect questions;
  - the work overlay rows.
- **`sessions/2026-10-28-packet-to-lane-01-adr-0062-section-5-is-written-511e5927.md`**, in the master tree.

## Next (in order)

1. **Read CI on #134.** If #127 or #134 merges, rebase the other one.
2. **When Lane 1's door PR opens:**
   - check that its existence read raises on a transport error;
   - check that `droppable_kinds` comes from the same two reads;
   - check that the 403 names family `capability_grants`.

   Gov seals; it does not build the door.
3. **When fin moves a table:** review the seal side (#127's ratchet PENDING, and the refusal-seal family rows).
4. **Per-site RELAY adoption:** 10 rows, one site per change.
5. **Ruling 3:** audit every non-empty `candidates` source (the #113 options and `switch_cell`).
6. **When SDK v0.9.12 tags,** swap the prefix pair for `Refusal.to_terminal()` / `from_terminal()`.
7. **Carried, not re-checked:** Q11, Q17–Q26.

## Scratch (the session scratchpad; disposable)

- `pr2/` is #127, `pr3/` is #126, `pr4/` is #134, and `adr62/` is detached at `511e5927`.
- The mutant driver is `mut_cd.py`. Its args are pr, bak, gate.sh and bash, each as a Windows path.
  - Pass the **script path** through `cygpath -w` as well, because `MSYS_NO_PATHCONV=1` stops the conversion of the script path too.
- Remove each worktree once its PR merges.

## Lessons

- **Read the inbox before building.** Lane 1 had proposed names and asked for a reply "before your PR". The first build (a new Topaz type, its marker and its sync) was discarded. It cost an implementer run, not a merge, but it would have been avoided by listing `sessions/*to-gov*` first.
- **Check a proposed field against the schema that will read it.** Lane 1's `drop_capability` key would have raised in an `extra="forbid"` SDK model and failed every `/ingest` closed.
