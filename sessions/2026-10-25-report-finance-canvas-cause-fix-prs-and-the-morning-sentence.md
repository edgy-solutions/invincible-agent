# Report: "make me a finance canvas". Cause, fix PRs, and the sentence for the morning

to: invincible-agent/seat/architect, via Chris
from: invincible-agent/lane/fin, 2026-10-25

## Cause

I measured each part from the Dagster logs of three probe runs, and from `/templates`.

1. **Chat: no verb, so the generalist answered.**
   - The only `mesh:seedCanvas` registration is typed `idp#Portfolio`, in
     PORTFOLIO_LEAD·PORTFOLIO_PLANNING.
   - Outside the finance cell the subject grounds to `mesh#DocPage`, which gives
     `no_verb_classified` and then the generalist.
   - Inside the finance cell, `fin#Program` picks `mesh:finProgramBrief`, a brief rather than a
     board.
2. **The picker's amber "needs a binding: program".** cortex's `needsBinding` is structural (any
   shared slot means "not offered"). The server had nothing to offer it either: `/canvas/seed`
   answered an unbound program with a bare 409.
3. **Latent bug.** `CanvasSeedRequest` dropped the supervisor's `params`, `user_persona` and
   `domain`. So any chat-routed seed built the **portfolio** board, whatever template it named.
4. **Sandbox data was not the cause.**
   - NP-MERIDIAN ("Notional Program Meridian", synthetic) is already in engine-fin's seed.
   - alice holds PROGRAM_FINANCE_ANALYST·PROGRAM_FINANCE through `finance-analysts`.
   - A direct seed with `bindings {program: NP-MERIDIAN}` built 6 of 6 panels on 10-08.
   - So I added no fixture program and no policy, and no Topaz write is needed.

## Fix

- **PR #97** (base master, head `473f9c40`): https://github.com/edgy-solutions/invincible-agent/pull/97
  - A second `mesh:seedCanvas` registration typed `fin#Program` in the finance cell. It asks
    "Which program did you mean? Options: Notional Program Meridian."
  - `/canvas/seed` reads the dispatch fields. Any disagreement is a 422, never portfolio.
  - The 409 carries `ask`, plus `policy` when the caller can see no program. `policy` names one
    repair: switch cell, ask for a program grant, or join the group read from
    `policy/groups.yaml`.
  - `/templates` adds `shared_slot_detail`.
- **PR #98**, stacked on #97 (head `df5802bb`, **no CI gate runs on a stacked PR**):
  https://github.com/edgy-solutions/invincible-agent/pull/98
  - The seed answer carries `template_id`, so cortex places the board as a finance board.
  - It widens a pinned response seal by one field, so it **needs a ruling**.
- **Tests.**
  - The new arms are in `tests/planning/test_finance_canvas_asks_which_program.py`: 23 in #97,
    25 in #98. Eight mutants each redden a named arm.
  - Targeted run: #97 1010 passed, #98 1012 passed. In both, the only failures are 4 that also
    fail at base `db7db75c`.
  - Not the full suite.
  - Joined with gov's #96 in a throwaway worktree: 39 passed.
- **cortex-ui.** The picker change (offer askable rows, render the 409 `ask`, re-send `bindings`)
  is theirs to make. The request is placed, untracked, in their `sessions/`.

## The sentence for Chris in the morning

This needs #97 merged and cortex-bff rolled. With #98, presentation-agent rolls too.

1. Sign in as **alice**.
2. Choose the cell **Program Finance Analyst · Program Finance**.
3. Type: **`make me a finance canvas`**
4. When asked "Which program did you mean?", pick **Notional Program Meridian**.

Caveats:

- **Not verified live.** The classifier may still prefer `mesh:finProgramBrief`. If it answers
  with a brief, try `build the program finance board`. That phrasing is also unverified.
- Seeding the six panels is sequential and takes minutes.
- **The picker button** stays amber until cortex-ui ships its side.
- **Before the merge**, no chat sentence works. Only a direct `POST /canvas/seed` from the finance
  cell with `bindings {program: NP-MERIDIAN}` does.

## Packets placed (untracked)

- `invincible-agent/sessions/2026-10-25-packet-to-lane-01-finance-canvas-is-97-then-98-roll-cortex-bff-and-presentation.md`
- `invincible-agent/sessions/2026-10-25-packet-to-gov-the-finance-failure-is-the-canvas-picker-and-it-is-a-409-your-census-cannot-see.md`
  - This answers gov's "which finance failure?".
  - It names a gap: gov's refusal census counts only 401/403, so an empty-menu 409 ask reads as a
    clean zero.
- `cortex-ui/sessions/2026-10-25-packet-to-cortex-the-unbound-finance-row-can-be-seeded-by-asking-which-program.md`

## Not done

- No roll; the task was PRs only.
- No live verification of the classifier choice.
- Fin's base-red `test_gate_5_a_disagreeing_scope_is_409_naming_the_derived_one` is not diagnosed.
