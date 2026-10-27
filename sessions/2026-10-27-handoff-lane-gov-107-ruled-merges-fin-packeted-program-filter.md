# Handoff: lane/gov, 2026-10-27

to: invincible-agent/lane/gov (worktree ia-gov; branches lane/gov, lane/gov-a-409-that-asks-is-a-refusal)
from: invincible-agent/lane/gov, 2026-10-27

This replaces `2026-10-25-handoff-lane-gov-409-rule-pr-107-finance-canvas-first.md`.

## State

| branch | tip | PR | status |
| --- | --- | --- | --- |
| `lane/gov` | this commit | none | handoff carrier |
| `lane/gov-a-409-that-asks-is-a-refusal` | `ffee7a34` (master `48fab03d` merged in; no force-push) | #107 → master | **ruled "merges" (10-27)**; at `ffee7a34`, every CI check passed, GitHub reads CLEAN, and it merges cleanly with master `4a4cf47c`. Not merged by gov. The merge declared `refusal` in #103's `CanvasSeedConflictDetail` (as `CanvasSeedRefusal`) and regenerated the OpenAPI file. Local runs at that sha: the ratchet 23 passed, fin's canvas tests 32, fin_package_export 38 (test_gate_5 is green on master now), and 5 planning files green. |
| `lane/gov-policy-refusals-say-what-and-who` | `9b26613b` | #96 | merged (`78315212`) |

The full record is `sessions/2026-10-10-report-gov-origin-at-read-and-on-promotion.md`, in the section "2026-10-25 (later)". It is unchanged by this handoff: the ruling below decides no open Q.

## The ruling (2026-10-27, from the architect via Chris)

> #107 merges. Your finding is fin's defect: `program_members` is named but unchecked. Packet fin: the program list returned in the ask is filtered to the caller's grants, with a test that a non-member sees an empty list and the grantor line. RECIPIENT_READERS to the policy rail stays queued.

**Done:** the packet to fin is placed (see below). It carries what I measured by reading code (no live call):

- engine-fin's `EnumerateRequest` and `ResolveRequest` drop the caller that engine-o forwards.
- engine-o's post-fan-out gate decides sustainment IRIs only.
- `agent_fleet/utils/program_membership.can_view_program` already exists.
- **fin's seed program `NP-MERIDIAN` has no row in `policy/program_members.yaml`** (it holds only `SANDBOX_PROGRAM_ALPHA` and `SANDBOX_PROGRAM_BRAVO`). A correct filter therefore empties the list for every sandbox caller until a reviewed row lands, applied by a human through topaz_sync.
- Filter before `too_many` and before `count`, and answer 503, not an empty list, on a lookup failure.

## Next

1. **Confirm #107 merged** (`gh pr view 107`). A conflicting master move is merged in, never rebased (the branch is pushed).
   - If master moved first and the ratchet reds on a new 401/403/409 site, classify it in the same merge.
   - Then remove the `pr2/` worktree (`git worktree remove`).
2. **When fin lands the filter:**
   - The 409 needs no gateway change. #107's `slot_refusal` `grant_member` arm already emits `program_members` / `can_view_program(program)` with the seed grantor.
   - Check that fin's non-member arm reds by name when the filter is mutated away, and that its member control sees exactly the granted program.
3. **When Chris pastes Q21–Q26, apply them.** Q22 and Q23 touch `slot_refusal`'s candidates.
4. **Queued, after #107: move `RECIPIENT_READERS` onto the policy rail** (finance and cost). It needs:
   - a rail file;
   - a grantor row;
   - the two sites moved off `code`.
5. **When SDK v0.9.11 tags,** import `iagent_mesh.refusal.Refusal` and validate the dict against it in the seal.
6. **The pre-existing red** `test_fin_package_export::test_gate_5` is lane/01's `d0f80092`. It was reported, and it is not gov's to fix.
7. **Carried, not re-checked:**
   - Q11;
   - Q17 (#77 merged; a merge is not a ruling);
   - Q18–Q20;
   - §5.1 instance 2;
   - the AnswerArtifact origin field.

## Placed (untracked in master's `sessions/`)

- `2026-10-27-packet-to-fin-filter-the-asks-program-list-to-the-callers-grants.md` (to lane/fin, cc the architect)
- From 10-25, still for their owners to commit:
  - `2026-10-25-packet-to-fin-your-canvas-409-carries-the-refusal-beside-its-ask-pr-107.md`
  - `2026-10-25-packet-to-architect-gov-the-409-rule-is-built-finance-canvas-409-first-pr-107.md`

## Scratch (the session scratchpad; disposable)

- **`pr2/`** is #107, with its own `.venv`. Remove it once #107 has merged.
  - The runner is `run_pr2.sh`.
  - The mutant driver is `mut2.py`; pass Git's bash explicitly.
- **`pr/` and `rg/`** were removed 10-27.
  - Both branches were in master first (`is-ancestor`).
  - `pr/`'s uncommitted edits match `gov1025_on_9b26613b.patch` by patch-id.
- **`wh/`, `seal/`, `q14/`, `adr/`** were already gone.

## Lessons

- **A filter is only as good as its rail's rows.** The `program_members` check exists and the rail has a grantor, but the program the canvas actually asks about has no row. Ship the filter alone and it makes the refusal fire for everyone, members included. Before calling a filter correct, read the rail for the very key the subject uses.
