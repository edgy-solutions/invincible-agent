# Handoff: lane/gov, 2026-10-25

to: invincible-agent/lane/gov (worktree ia-gov; branches lane/gov, lane/gov-policy-refusals-say-what-and-who)
from: invincible-agent/lane/gov, 2026-10-25

This replaces `2026-10-21-handoff-lane-gov-withholding-arms-option-1-pr-82-q17-q20-with-the-architect.md`.

## State

| branch | tip | PR | status |
| --- | --- | --- | --- |
| `lane/gov` | this commit (fast-forwarded to master `db7db75c` first) | none open; #32 merged 10-24 | handoff carrier |
| `lane/gov-policy-refusals-say-what-and-who` | `9b26613b` | #96 → master | open; 14 passed, file alone |
| `lane/gov-withholding-arms-name-their-subject` | `b0d9385b` | #82 | merged (`f5b35500`), in master |
| `lane/gov-action-route-seal`, `lane/gov-q14-unconfigured-topaz` | `01d8605b`, `3e9b25a9` | #77, #78 | merged into master 10-24 |
| `-resolve-instance`, `-enumerate-gate`, `-caller-census`, `-narrow-except` | as on 10-15 | #39, #45, #47, #54 | closed; whether the content landed elsewhere is not re-checked |

The full record is `sessions/2026-10-10-report-gov-origin-at-read-and-on-promotion.md`, section "2026-10-25". The open questions are Q11 and Q17–Q26 at its foot.

## The directive (10-24, overnight, from the architect via Chris)

> Policy readability for the finance failure above: a missing binding today surfaces as red text nobody can act on. Draft the rule that every policy refusal names (a) the policy id, (b) the binding or role missing, (c) who can grant it -- and the test that enforces it across the refusal paths. Coordinate with fin on the finance case as the first instance; own the general rule.

- **The rule and its seal: DONE, as #96.**
  - The helper is `src/iagent/authz/refusal.py`, the grantor map is `policy/grantors/`, the ratchet is `tests/security/test_every_policy_refusal_names_policy_binding_grantor.py`, and the proposal is `docs/proposals/a-policy-refusal-names-its-policy-the-missing-binding-and-who-can-grant-it.md`.
  - No refusal site changed.
- **The finance instance: BLOCKED on the failure text.** "The finance failure above" was not in the paste. Fin and Chris were both asked. Gov's guess is `finance_agent get_artifact` (`RECIPIENT_READERS`, family `code`).

## Next

1. **When fin or Chris names the finance failure:**
   - If it is `get_artifact`, fin lands the body per the packet and deletes the PENDING row in the same commit.
   - If it is another site, find it in the PENDING table by its key. If it is in NOT_POLICY, reclassify it with the reason why a grant would lift it.
2. **Watch #96.**
   - If a join reds the ratchet on a new site, classify that site in the same merge (Q26).
   - Once #96 is in master, every new 401/403 site in any lane has to be classified.
3. **When Q21–Q26 are ruled:**
   - Q21 decides the 10 relay rows' path.
   - Q22 decides whether `missing_binding` may echo the caller's own scope.
   - Q24 may move `RECIPIENT_READERS` onto the rail. That needs a new grantor row, and the arm "every grant-bearing policy file has a row" will demand one.
4. **Carried, not re-checked:**
   - Q11 (`svc:` as a recipient);
   - Q17: #77 is merged, but a merge is not a ruling;
   - Q18–Q20;
   - §5.1 instance 2 (grep lane/01-* for `_delegate_principals` reads added since `b3fdad7f`);
   - the AnswerArtifact origin field.

## Placed (untracked in master's `sessions/`)

- `2026-10-25-packet-to-fin-policy-refusal-first-instance-which-finance-failure.md` (to lane/fin, cc the architect)
- `2026-10-25-packet-to-architect-gov-policy-refusal-rule-drafted-six-questions-finance-text-missing.md`

## Scratch (the session scratchpad; disposable)

- Worktrees, removed only with `git worktree remove`, never `rm`:
  - `pr/` (#96; keep it until #96 merges);
  - `wh/`, `seal/`, `q14/`, `adr/` (all merged or closed; removable);
  - `rg/`, which holds the venv the runners use.
- `run_pr.sh <log> <file>...` is the gated runner for `pr/`. It passes `-p no:langsmith_plugin`, because the venv's langsmith plugin crashes on a missing `xxhash._xxhash`. The venv is not repaired.
  - The runners use another worktree's venv (`rg/.venv`). The newer CLAUDE.md rule says to use this worktree's venv or `uv run`. Move the next run to `uv run` inside `pr/`.
- The mutant driver is `mut_pr.py` (seven mutants; results in `mut_pr.out`).

## Lessons

- **A directive can cite context that never arrived.** "The finance failure above" was in nobody's paste. Do the part you own (the general rule), and ask for the missing instance by packet and in chat at once. Don't guess it into the seal; the guess goes in the packet, labelled as a guess.
- **Look for the shape before inventing one.** ca had already built `Refusal` for this directive on an unpublished SDK branch. Adopting its field names saved a second envelope and a later migration.
- **A merged lane branch must be fast-forwarded before its next commit.** lane/gov was 444 behind after #32. Six untracked packets collided with master's committed copies. They were byte-identical, so removing them and fast-forwarding lost nothing. Compare the bytes before removing anything.
