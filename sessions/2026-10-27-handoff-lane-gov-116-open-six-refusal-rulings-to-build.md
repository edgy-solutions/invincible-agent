# Handoff: lane/gov, 2026-10-27 (later)

to: invincible-agent/lane/gov (worktree ia-gov; branches lane/gov, lane/gov-options-name-program-members)
from: invincible-agent/lane/gov, 2026-10-27

This replaces `2026-10-27-handoff-lane-gov-107-ruled-merges-fin-packeted-program-filter.md`.

## State

| branch | tip | PR | status |
| --- | --- | --- | --- |
| `lane/gov` | this commit | none | handoff carrier |
| `lane/gov-options-name-program-members` | `371cdfbf` (on master `235a125b`, which has #113) | #116 → master | open; not merged by gov. Local: seal 24, fin canvas 32, #113's enumeration 8, OpenAPI-current 2. Three mutants were each killed by a named arm. |
| `lane/gov-a-409-that-asks-is-a-refusal` | `ffee7a34` | #107 | merged (`0d228204`) |

#116 answers the architect's 10-27 directive: "the 'which program?' options case names `program_members` once #113 lands; that is the grant that gates. Update the docstring in the same PR." The fin packet (filter the ask's program list) was answered by #113, which is merged and adds the `NP-MERIDIAN` rail row.

## The six rulings on #96's open questions (architect via Chris, 2026-10-27), verbatim in substance

1. **Restate relays.** The refusal rides as JSON in the `TerminalError` message under a fixed prefix (`refusal:` + the Refusal dict) and is parsed at the BFF. ca adds `Refusal.to_terminal()` / `from_terminal()` in SDK v0.9.12. **Until then: gov's prefix form, with a seal that both sides parse to the same dict.**
2. **Echoing a caller-sent key:** as drafted. Object-scoped families never echo, even when the caller sent the key. The finance recipient scope is object-scoped.
3. **`candidates`:** only objects the caller already holds a view grant on (fin's #113 filter is the source), never "others exist". With no grants, the list is empty and `grantable_by` is the whole answer.
4. **`RECIPIENT_READERS` moves onto the rail:** family `program_members`, `granted_by` per program, finance first, cost second. "Platform maintainers" is the honest grantor until that lands.
5. **The sandbox overlay names the sandbox's actual approver (alice).** The seed stays neutral.
6. **Joining:** any merge that adds a 401/403/409-ask site classifies it in the same merge. The ratchet enforces it, gov doesn't chase, and Lane 1 is told.

## Next (in order)

1. **Ruling 1, a new branch off master.**
   - The engine-side encoder goes in `agent_fleet/utils/` (restate_analyst already imports `agent_fleet.utils`).
   - The decoder goes beside `relay_refusal` in `src/iagent/authz/refusal.py`.
   - The seal: one dict → encode → decode gives the same dict, and a non-prefixed message passes through.
   - The 10 RELAY rows in the seal stay PENDING until each site uses the pair. Moving them is per-site work.
   - Record all six rulings in the proposal's "Open questions" section in the same PR.
2. **Ruling 5.** A sandbox grantor overlay naming alice. It needs `GRANTOR_OVERLAY_DIRS` wired in the chart; nothing in `helm/` sets it today. Keep the IPs and hosts out of it.
3. **Ruling 4, finance first.** Move `agent_fleet/finance_agent/export.py:66` `RECIPIENT_READERS` onto `program_members`; then cost (`agent_fleet/cost_agent/seed.py:198`). The code is fin's and cost's, so gov packets the owners with the rail shape unless told to build it.
4. **Ruling 3: audit every non-empty `candidates` source.** Today: options (from #113, compliant) and `switch_cell`'s `[cell]`. That is a cell the caller holds, not an object; say so in the proposal.
5. **When SDK v0.9.12 tags,** replace the prefix pair with `Refusal.to_terminal()` / `from_terminal()`.
6. **Carried, not re-checked:**
   - Q11;
   - Q17–Q20;
   - §5.1 instance 2;
   - the AnswerArtifact origin field;
   - Q21–Q26 when Chris pastes them.

## Scratch (the session scratchpad; disposable)

- **`pr2/`** is now #116's branch, with its own `.venv`. The runner is `run_pr2.sh`; the mutant driver is `mut3.py` (pass Git's bash explicitly). Remove `pr2/` once #116 merges, or reuse it for ruling 1 by branching off master.

## Lessons

- **Rebase only what is unpushed.** #116 was cut before #113 merged. It was not yet pushed, so it was rebased onto master, and its "merge after #113" text became "rests on #113 (merged)" before anyone read it.
