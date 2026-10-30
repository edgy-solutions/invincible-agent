# Handoff: lane/gov, 2026-10-30 (the standing rule applied; the hold on #151/#159 is lifted)

to: invincible-agent/lane/gov (worktree ia-gov)
from: invincible-agent/lane/gov, 2026-10-30

This replaces `2026-10-30-handoff-lane-gov-answer-export-kind-and-plan-reader-149-151-159-merge-ready.md`.
That file's state is superseded by the table below. Its open forks, Next steps (except where
rewritten below), scratch notes and lessons still hold; read its "Open forks" and "Lessons" sections.

## The directive (architect via Chris, 2026-10-30, verbatim)

> Standing rule (architect, 2026-10-30): nothing in an API, wire type, route, engine or UI hard-codes
> a workflow, document kind, domain, group, program, recipient, or customer's shape. Those are
> configuration: a registry row (kinds, task kinds, rules), a declaration served on the wire
> (options, consequences, labels, review shapes), a policy-rail row (grants, audiences, approvers),
> or an overlay (profiles, templates, mappings). Code implements the mechanism; config names the case.
>
> Tests before you open a PR: (1) a new wire type uses generic nouns (item, kind, rule, recipient),
> with the domain term carried as a value from config; (2) a new behaviour is reachable by adding a
> row, not a branch — if you wrote `if kind == "pcn"` or an enum of workflows, it's wrong; (3) a
> deployment can add its own case without a code change, in an overlay never committed; (4) the
> registry/declaration your code reads is the one the server serves, not a copy.
>
> A ruling that seems to ask for a specific case (e.g. "pcn and pdn droppable by alert-processors")
> is the first row, not a constant.

**Applied to #151 and #159, measured and pushed. None has merged.** The rule is saved in auto-memory as
`code-names-the-mechanism-config-names-the-case`.

## State

| branch | tip | PR | status |
| --- | --- | --- | --- |
| `lane/gov` | this commit | none | handoff carrier |
| `lane/gov-repository-paths-rail` | `f4942845` | #149 → master | Unchanged. Its `GOVERNED_ROOTS` restates engine-r's constant; reported to the architect as a fork, not held. |
| `lane/gov-can-export-rail` | `e15195d9` | #151 → master | `EXPORT_DEFAULT_GROUPS`/`EXPORT_PROFILE_GROUPS` gone. The refusal advises the groups granted by same-kind rows; a lone kind names none. can_export 29 + 1 skip; validate_policy 7; CLI OK; X1–X15 15/15 named-red (re-anchored). **Still no `can_export:plan-answers` row.** |
| `lane/gov-recipient-readers-plan-owner` | `68b6a98a` | #159 → master | `OWNERS` gone: owners are the rail's keys, checked by `OWNER_NAME_RE`. recipient_readers 35 + 2 skip; validate_policy 7; CLI OK; P1–P7 7/7. |

**The join** is master `77fb1d73` + #148 `03f164ac` (fin's new head, with the test-4 fix) + #151 `e15195d9` + #159 `68b6a98a`:
- without the row: red, and the refusal names no group;
- with the row: can_export 30, recipient_readers 37, validate_policy 7; CLI OK;
- fin's dark seal is still red (1 failed, 92 passed). It is fin's.
- **jx/jr (J1–J4) were NOT re-run** on this join: their anchors predate the rule fix.

**Packets placed** (untracked, master tree `sessions/`):
- `…-hold-151-and-159-they-fail-the-config-rule.md` (the hold);
- `…-hold-lifted-151-and-159-pass-the-config-rule.md`, which carries the revised row text and the two forks for the architect.

PR bodies for #151 and #159 now open with a "2026-10-30 standing rule" section. The prior bodies are saved as scratch `pr151_body_pre_cfg.md` and `pr159_body_pre_cfg.md`.

## Open forks (new; the old file's 1–6 still stand)

7. **Test 4 on #151.** `known_export_profiles` composes each kind's directories as its loader does: a copy, held equal by the `test_2` arms. Gov recommends the SDK loader convergence (v0.9.12) as the fix, not a #151 blocker. The architect's call.
8. **Test 4 on #149.** `GOVERNED_ROOTS` restates engine-r's; it is repository scope. The architect's call.

## Next (in order)

1. **Read CI on #149, #151 and #159** at the new heads.
2. **On the first merge among #148, #149 and #151:** as in the old handoff's Next 2. The row to append is scratch `plan_answers_row.yaml`, whose reason was revised under the rule. Re-run X1–X15 after the rebase.
3. **Re-anchor jx/jr in `mut3.py`** if a join measurement is wanted again.
4. **Before every PR, run the rule's four tests.** Grep added code lines for quoted case names.

## Lessons

- **"The ruling, typed into code" is the shape the rule forbids.** All three violations here were rulings made constants:
  - a group default;
  - a ruled profile→group;
  - a closed owner set.

  The fix each time was to read the keys or rows that config already declares and check their shape.
- **A mutant anchored on the code you just removed silently SKIPs** ("anchor count 0"). Read the skip lines, not only the named-red count. X14 skipped once on an indent mismatch.
