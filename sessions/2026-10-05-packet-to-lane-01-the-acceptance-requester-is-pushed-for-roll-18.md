# Packet: the acceptance requester is pushed for roll #18

to: ia-01/lane/01
cc: invincible-agent/seat/architect
from: ia-74/lane/74, 2026-10-05
re: the 2026-10-05 dispatch to ia-74/lane/74 (items 1–3)

The full report is
`ia-01/sessions/2026-10-05-report-74-the-acceptance-row-names-its-requester-and-a-blank-one-is-refused.md`.

## 1. Take `lane/74-acceptance-requester` @ `525c8539` for roll #18

It is one commit on origin/master `f2fa87e1`. `git merge-tree` against every unmerged lane/74
branch is clean except two: `outcome-from` (already landed as `0d6f37e3` and `f1d44b28`) and
`mesh-writers` (superseded by `-v095`). Both conflicts exist against master already.

What it does:
- The acceptance row's `requested_by` becomes the authz_id of the person whose turn's answer
  carried the review_request.
- The path: `/orchestrate`, then `produced_for.authz_id`, then both consumers, then the fact
  `authz_id`, then the runner's identity, then the row.
- A blank requester is refused in three places: the builder (no case opens, and the turn shows
  `acceptance_not_opened`), the store (`NoRequester`), and the BFF (a terminal 422
  `no_requester` at all four register sites).

**The refusal is store-wide, not acceptance-only -- RULED 2026-10-05, see section 4.** The 10-05 census found no live kind
writing blanks apart from the defect and two grouped_review rows that predate the `approver`
requirement. Two paths are unmeasured:
- access_request (no rows to census);
- `dispatch_driver`'s `or ""`.

A blank on either is now a terminal 422.

**Sealed:**
- 25 arms;
- 18 of 18 mutants killed;
- 22 red and 3 green on the unfixed base (the greens are two controls and one hand-off that already
  held);
- consequence run: 394 passed, plus the known environmental SDK-path red.

**For your roll's verification:** the existing `~1` acceptance row keeps `requested_by = ""`,
because the refusal applies at register time. A fresh HAZ case opened after roll #18 is the one
that should carry the person.

## 2. The lineage re-check holds otherwise

Everything in the 10-04 `~1` lineage stands as measured except `requested_by`. The subject→bob
mapping and the resume are still unmeasured.

## 3. Engine W stays off

`KNOWLEDGE_SEARCH_VIA_MESH` defaults to `false` on `lane/74-engine-w-mesh` (`ca4fab9e`, unmerged).
Nothing in `helm/`, `setup/` or `scripts/` sets it, so roll #18 runs DIRECT either way. It stays
off until your identity census after roll #18.

## 4. Ruled 2026-10-05: store-wide stands, and the two unmeasured callers are yours before roll #18

Chris: "yes. A task nobody asked for is a lineage hole whatever its kind." **Lane 1** measures the
two unmeasured paths and fixes their callers to pass a requester before roll #18, so the 422
never fires on a legitimate path. Where they are (line numbers from origin/master and
`lane/74-acceptance-requester`):

- **access_request** -- `src/iagent/gateway.py:728` on the branch passes
  `requested_by=current_user.email`. Its siblings pass the authz_id: triage at `:821` passes
  `current_user.authz_id`. A principal with no email is refused here, and an email that differs
  from the authz_id breaks the convention every other row follows. No access_request rows
  existed to census.
- **dispatch_driver** -- `agent_fleet/restate_analyst/dispatch_driver.py:196` registers
  `task.get("requested_by") or ""`. Its own comment says this is "the approver who resolved the
  grouped review". `plan_to_payload` (`:67`) defaults `requested_by` to `""`, and its one
  non-test caller is `:514`. The question to measure is whether every plan reaching `:514`
  carries a requester. The default `""` is where a missing one turns into a 422.

Since `525c8539`, a blank on either path is a terminal 422 `no_requester`, not a row. The seal
`test_every_bff_register_call_maps_the_refusal_to_a_terminal_422` keeps the BFF side honest. It
cannot see a caller that sends a blank, so measuring those callers is the work above.
