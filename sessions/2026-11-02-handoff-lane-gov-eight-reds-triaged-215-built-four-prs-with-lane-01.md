# Handoff: lane/gov, 2026-11-02 (eight reds triaged to five items; can_configure is #215; four PRs with lane/01)

to: invincible-agent/lane/gov (worktree ia-gov)
from: invincible-agent/lane/gov, 2026-11-02

This replaces `2026-11-02-handoff-lane-gov-204-merged-210-fork-22-in-review-one-outage-question-asked.md`.
- Forks 22 and 23 and the `can_configure` ruling are built. Fork 12 and the lessons in older handoffs still stand.

## The rulings since (via Chris, 2026-11-02, verbatim)

> to: invincible-agent/lane/gov (cc wb) — new capability `can_configure:deck_template` on the rail, group `training-admins` (sandbox: alice), seed row with granted_by: seed; sync before the workbench roll that carries it.

> gov found eight master reds with no owner; triage each to a lane as board items by morning; none of them silently

## State

| what | state | item |
| --- | --- | --- |
| #211, board | open, head `8ebcded9`, CI running at last read | the eight reds and corrections |
| #215, can_configure | open, CLEAN, head `4536e0f0`, CI 20 passed and 3 skipped | `01M6FMQYFY8K233JWP2HXN91ED` |
| #210, fork 22 | open, CLEAN, head `d8c3d4c4`, CI 20 passed and 3 skipped | `01M6FJFNZER425XQ4V9XCRTTCW` |
| #149, repository paths | open, CLEAN, head `033fa87b`, CI 20 passed and 3 skipped | `01M6A9QDN1M7B3400G8Y0MWH0Y` |

**Chart:** tag `invincible-agent-0.4.75` = `aac9900b`, cut before #204 and #210. Its policy gives `alignment-reviewers` to bob. helm read 0.4.75 at revision 225. Everything of gov's since then goes under `## 0.4.76 — not yet cut`. #149, #210 and #215 each add that heading, so the second and third to merge conflict on the changelog. Gov merges master (no rebase) when lane/01 says so. A rebase of #210 needs its seal rerun.

**Order for #215 after merge:** chart cut; Chris runs `topaz_sync` at that release's sha, streamed form; the ia chart roll, whose hook writes the row; then the workbench roll. `topaz_sync` alone leaves `can_invoke` false for everyone. That same sync is what brings alice to `alignment-reviewers`.

## The eight reds

All are red on master `e0a2ab9b`. All are lane/01's, by proof of cause: green at the parent, red at the commit, in today's venv. Whether each fix belongs in the test or the code is unexamined and is lane/01's call.

| item | commit | tests |
| --- | --- | --- |
| `01M6FMQXQ9V1JX4GJJD8F0TDPZ` | `334653ad` (#187) | 4, delegate refusal behind the MCP door; the guard may no longer fire (read, not measured) |
| `01M6FMQXW02A6VP3Q0QD8XZ73W` | `6a10a62a` | 1, three principals where the values list four |
| `01M6FMQY0YAW59ENJEDZTZA2WQ` | `152d453f` | 1, `DispatchFanoutStep` gained `stage` |
| `01M6FMQY6AJHJJC5BMA3FH8Q8F` | `c095be48` | 1, q2-e fixture does not stub `get_open_task_payload` |
| `01M6FMQYB0P53YW79QGMZ3X175` | `a14e21b5` | 1, a fifth promotion statement |

Catch-all `01M6FJH2HQCN09G0CF14451A48` is done and holds pointers only. saf's ninth red stays on `01M6EYWM7JPW40G3PQATTYXAQR`.

## Open forks

12. The relay-form detector for the ratchet (carried over). Item `01M6A9QDN19S78PQVCA67NZ9RC`.
24. A transport outage at the fail-closed sites is still a no. Asked of the architect. Item `01M6FJFNZER425XQ4V9XCRTTCW`.
25. Does `can_configure:` take subjects from a registry list, as `can_review:` does? #215 has none; a misspelt key fails closed. Asked of the architect. If yes, one small PR. Item `01M6FMQYFY8K233JWP2HXN91ED`.

## Waiting on

| for | who | item |
| --- | --- | --- |
| the outage and registry questions | architect | `01M6FJFNZER425XQ4V9XCRTTCW`, `01M6FMQYFY8K233JWP2HXN91ED` |
| #211, #149, #210, #215 merges | lane/01 | `01M6FJH2HQCN09G0CF14451A48`, `01M6A9QDN1M7B3400G8Y0MWH0Y`, `01M6FJFNZER425XQ4V9XCRTTCW`, `01M6FMQYFY8K233JWP2HXN91ED` |
| the five reds | lane/01 | the five above |
| `topaz_sync` at a release carrying #204 and #215, then the chart roll | Chris | `01M6AJR52DDXSJPFKQ12WG08J3`, `01M6FMQYFY8K233JWP2HXN91ED` |
| the catalogue seal | saf | `01M6EYWM7JPW40G3PQATTYXAQR` |
| the strict reader in a release | ca | `01M6AJR570CZG8R9WA0JCYX1ZX` |
| `GRANTED_BY_SEED`: v0.9.13 is tagged, master pins v0.9.12 | the pin bump | `01M6A9QDN199K1WE2H3QN3ZVQ9` |
| production reviewers | the training-domain ruling | `01M6A9QDN16Q03BPSJAPWDSAEP` |
| the configure surface | wb | `01M6FMQYFY8K233JWP2HXN91ED` (gov's item; wb has the packet) |

## Next (in order)

1. Read the state of all four PRs before writing anything about them. #211's CI was still running when this was written; read it. On a conflict in `board/BOARD.md`, re-render, don't hand-merge.
2. Read inbox packets from lane/01 and the architect's answers.
3. When a PR merges, move its item and regenerate the render: #210 to done, #149 to done, #215 to blocked on Chris's sync.
4. **Later, as ruled:**
   - the walker `chris@example.com` → `dave`, with lane/01 (`01M6EX5BSQNCWZXBBCFAM8PNCV`);
   - `GRANTED_BY_SEED` once master pins v0.9.13 (`01M6A9QDN199K1WE2H3QN3ZVQ9`).

## Scratch (session scratchpad, not durable)

- `gs` holds #215, with its own venv, which is also the Python for `bd`. `ct` holds #210, with its own venv. `rp` holds #149, with its own venv. `bd` holds #211, with no venv. `f181` and `cc` can go.
- `mut3.py` sets: `fk` (#210), `cc` (#215). It needs its backup directory to exist; ids are comma-separated.

## Lessons

- **A cut is a fact to read, not a word in a plan.** I wrote "0.4.75, not yet cut" in three packets and two items after the tag existed, and rewrote a cut release's changelog entry twice. Read the tag and its ancestry (`merge-base --is-ancestor`) before saying what a chart carries.
- **A red that names an environment variable need not be environmental.** q2-e says `PROJECTOR_POSTGRES_DSN is unset`, and I suggested my environment. It is green at its parent with the same unset DSN, so the commit is the cause. Run the parent before suggesting an environment.
- **A multi-heredoc shell command with quotes can fail whole.** Nothing was written, and the error named a line far from the cause. Write packets with the Write tool.
