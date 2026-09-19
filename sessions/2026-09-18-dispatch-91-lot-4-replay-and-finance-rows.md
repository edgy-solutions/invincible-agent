# Dispatch to 91 — replay lot 4 against the provider if it is still empty, then the finance rows

**Ruled by the architect 2026-09-18, overnight window.** Relayed by Lane 1.

## 1. If lot 4 is still empty after the roll

Three defects fired at once behind the lot 4 regression, and **all three are now on master**:
a bare digit manufactured as a lookup term, the suffix rule scoring any short suffix at 0.9
(eo's, fixed), and acting domains never forwarded so demotion never ran. Fix (3) is proven —
`program_id` went from `ambiguous_in_domain, []` to `exact 1.0`.

So after the roll, lot 4 should draw four supplier rows. **If the payload is still empty**,
replay the **recorded request body** against the provider directly — not a fresh hand-typed
request. The distinction matters: a hand-typed probe tests the phrasing you chose, and the
whole lot 4 story is that the failure lived in a term the UI manufactured and nobody typed.

Two instrument notes, both paid for this week:

- **`mesh_client` defaults to `agent-user`/`DATA_ENGINEER` and never sends `active_persona`.**
  An unentitled probe reads as a dead fleet. Send the cell the sheet names.
- **Port-forwards die across a roll.** A dead forward and an empty payload are indistinguishable
  at the call site.

If it draws, say so with the payload shape; if it does not, the recorded body plus the
provider's answer is the artifact, not a description of it.

## 2. The finance sheet rows for the walk census

Lane 1 is building the walk census tonight — one YAML of rows **derived** from the sheets, and a
runner that asserts `route_status`, verb, archetype and a payload floor per row.

Derive the finance rows **from your walk sheet**, in the shape of
`docs/measurements/cost-card-walk-sheet.md`: each prompt on its own quoted-bold line so a parser
can find them, plus persona, domains, expected verb, expected archetype, minimum rows, and the
disposition allowed. The NP-MERIDIAN brief with **three ledger rows** is in the census's first
five.

One thing already known about that row, so you do not re-find it: the brief's 422 was
`fin_program_brief declares checkpointer: true, so it needs a thread_id` — self-inflicted, and
the `run_id` threading is on master. If NP-MERIDIAN 422s again it is a **new** cause.

Until the sheet is a file, the NP-MERIDIAN row sits in the census as **red with the reason
`awaiting finance sheet`** — state, not an exclusion.

Lane: ia-01/lane/01
