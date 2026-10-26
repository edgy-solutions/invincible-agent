# Handoff: lane/gov, 2026-10-25 (later)

to: invincible-agent/lane/gov (worktree ia-gov; branches lane/gov, lane/gov-a-409-that-asks-is-a-refusal)
from: invincible-agent/lane/gov, 2026-10-25

This replaces `2026-10-25-handoff-lane-gov-policy-refusal-rule-pr-96-finance-text-missing.md`.

## State

| branch | tip | PR | status |
| --- | --- | --- | --- |
| `lane/gov` | this commit (master `78315212` merged in first) | none | handoff carrier |
| `lane/gov-a-409-that-asks-is-a-refusal` | `e3cd997e` | #107 → master | open; based on master, so CI runs |
| `lane/gov-policy-refusals-say-what-and-who` | `9b26613b` | #96 | merged (`78315212`) |

The full record is `sessions/2026-10-10-report-gov-origin-at-read-and-on-promotion.md`, in the section "2026-10-25 (later)". The open questions are at its foot: Q11, Q17–Q23, Q25 and Q26. Q24 is answered.

## The directive (2026-10-25, from the architect via Chris)

> The finance failure is fin's canvas 409 (program binding unbound), not get_artifact. Rule change from it: a refusal is any 401, 403, or 409 that asks the caller to choose or request something — a 409 with an empty candidate list and no grantor is a non-compliant refusal. Finance's hard-coded readers: "platform maintainers" is an acceptable grantor text now; moving them to the policy rail is yes, as a queue item after #96. Use ca's Refusal field names as you did; switch to the import when v0.9.11 tags. Q21–Q26: Chris will paste them; proceed on the defaults above meanwhile.

- **Done as #107.** The 409 widening, finance's three sites made compliant, the ratchet re-measured on master, and 13 mutants, all named reds.
- **Waiting on:**
  - fin's review of the ask → envelope mapping;
  - fin's answer on the finding that `grant_member` names a grant nothing checks;
  - the architect's review of the judgment calls in the packet (`NAMED` ×4, the `config`/`code` families, `NOT_BUILT`, `extra=`).

## Next

1. **Watch #107.**
   - If CI or a join reds the ratchet on a new 401/403/409 site, classify it in the same merge.
   - If master moves before the merge, re-derive the census and fix the seal's header counts.
2. **When Chris pastes Q21–Q26, apply them.** Q22 and Q23 touch `slot_refusal`'s candidates.
3. **Queue item, after #96: move `RECIPIENT_READERS` onto the policy rail** (finance and cost). It needs:
   - a rail file;
   - a grantor row (the arm "every grant-bearing policy file has a row" will demand it);
   - the two sites moved off `code`.
4. **When SDK v0.9.11 tags,** import `iagent_mesh.refusal.Refusal` and validate the dict against it in the seal.
5. **The pre-existing red** `test_fin_package_export::test_gate_5` is lane/01's `d0f80092` against fin's test. It was reported to the architect; it is not gov's to fix.
6. **Carried, not re-checked:**
   - Q11;
   - Q17 (#77 merged; a merge is not a ruling);
   - Q18–Q20;
   - §5.1 instance 2;
   - the AnswerArtifact origin field.

## Placed (untracked in master's `sessions/`)

- `2026-10-25-packet-to-fin-your-canvas-409-carries-the-refusal-beside-its-ask-pr-107.md` (to lane/fin, cc the architect)
- `2026-10-25-packet-to-architect-gov-the-409-rule-is-built-finance-canvas-409-first-pr-107.md`

## Scratch (the session scratchpad; disposable)

Remove worktrees with `git worktree remove`, never `rm`.

- **`pr2/`** is #107. It has its own `.venv`.
  - The runner is `run_pr2.sh <log> <file>...`, gated.
  - The mutant driver is `mut2.py <pr> <bakdir> <gate.sh> <git-bash.exe>`. Pass Git's bash explicitly: a bare `bash` from Python is a different shell, and every gate check fails as "not clear".
- **`pr/`** is #96, merged. Its uncommitted edits are a stale-base draft, saved as `gov1025_on_9b26613b.patch`. Removable.
- **`rg/`, `wh/`, `seal/`, `q14/`, `adr/`** are all merged or closed. Removable.

## Lessons

- **Rebase the design, not just the diff, when a peer's PR lands under you.** #97 gave finance an `ask` that already said which repair applied. The stale conversion would have contradicted it with a blanket `program_members`. Read what the merged peer built before porting onto it.
- **Measure the grant a refusal names.** "Ask an administrator to grant you a program" names `program_members`, which no layer filters by. A refusal that names a grant nothing checks is still non-actionable.
- **A gate that cannot run reads as a gate that said no.** The skipped mutant pass returned 0 with every row "GATE not clear". Treat a run where every row was skipped as a failed instrument.
