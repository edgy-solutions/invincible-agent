# Handoff: lane/gov, 2026-10-28

to: invincible-agent/lane/gov (worktree ia-gov; branches lane/gov, lane/gov-recipient-readers-rail, lane/gov-sandbox-grantor-overlay)
from: invincible-agent/lane/gov, 2026-10-28

This replaces `2026-10-27-handoff-lane-gov-116-open-six-refusal-rulings-to-build.md`.

## State

| branch | tip | PR | status |
| --- | --- | --- | --- |
| `lane/gov` | this commit | none | handoff carrier |
| `lane/gov-recipient-readers-rail` | `94139c4f` (on master `5522d8d2`) | #127 → master | Ruling 4: the rail shape. Seal 26; 11 neighbour files green; 11 of 11 mutants named-red. CI not yet read. |
| `lane/gov-sandbox-grantor-overlay` | `78f135b1` (on master `5522d8d2`) | #126 → master | Ruling 5: the alice overlay for `asset_grants`. Seal 7; 6 of 6 mutants named-red. Rides 0.4.72; the rendered values diff (one env key on cortex-bff) is in the PR body. CI not yet read. |
| `lane/gov-options-name-program-members` | `371cdfbf` | #116 | merged (`a244d5f4`) |
| `lane/gov-relay-refusal-prefix` | `85578a99` | #119 | merged (`5522d8d2`) |

#126 and #127 touch no common file; either may merge first.

## The 10-28 rulings (architect via Chris, verbatim)

> gov ruling 4: gov writes the rail shape (a recipient_readers family with grantors); fin and cost
> each move their own RECIPIENT_READERS onto it. Owners build, gov seals. Ruling 5: chart change
> approved; rides 0.4.72 with the values diff shown first.

These supersede the 10-27 text of ruling 4 ("family `program_members`"). The proposal in #127 is corrected to match.

## Packets placed (master tree, untracked)

- `2026-10-28-packet-to-fin-recipient-readers-rail-is-built-move-both-tables-onto-it.md`: both tables go to fin, because every `cost_agent` commit since 10-15 is fin's or 01's. It lists every call site, the refusal-seal rows whose family changes from `code` to `recipient_readers`, and that a Topaz transport error raises.
- `2026-10-28-packet-to-architect-gov-rulings-4-and-5-are-prs-127-and-126.md`: three questions.
  1. Is `recipient_readers.yaml` required?
  2. Should the other families' sandbox overlay name cnogradi or alice?
  3. Does `domain_consumption`'s in-process read leave a gap at work? (Unverified.)

## Next (in order)

1. **ADR-0062 §5 (merge policy), due 10-29 morning.** The packet is `sessions/2026-10-28-packet-to-gov-adr-0062-section-5-is-yours-merge-policy.md` in the master tree; read it whole.
   - **Where:** draft PR #123, branch `lane/01-adr-0062-mesh-owns-its-repositories`. Pull `bdd399e2` or later; write §5 in place and push to that branch (lane/01 invited it).
   - **What §5 covers:**
     - who may propose, review, merge and tag, per repo and per path, on the policy rail with grantors;
     - the second-approver rule for `policy/` and release tags, citing saf's #114/#115;
     - which paths need a second approver;
     - which lane owns which `sessions/` path;
     - engine-r's merge inputs for application source.
   - **Refusal sites:** §2's refusal sites are classified in the PR that builds them, not in the ADR.
2. **Read CI on #126 and #127.** Neither is based on another lane's branch, so CI runs.
3. **When fin moves a table,** review the seal side: the ratchet's PENDING shrinks, and the refusal-seal rows change family.
4. **Per-site RELAY adoption:** 10 rows, one site per change, each with its own arm.
5. **Ruling 3:** audit every non-empty `candidates` source. Today these are the options (from #113) and `switch_cell`'s `[cell]`.
6. **When SDK v0.9.12 tags,** swap the prefix pair for `Refusal.to_terminal()` / `from_terminal()`.
7. **Carried, not re-checked:** Q11, Q17–Q20, §5.1 instance 2, the AnswerArtifact origin field, and Q21–Q26 when Chris pastes them.

## Scratch (the session scratchpad; disposable)

- **`pr2/`** is #127's branch and **`pr3/`** is #126's, each with its own `.venv`.
- Runners are `run_pr2.sh` and `run_pr3.sh <log> <files>`.
- Mutant drivers are `mut_r4.py` and `mut6.py`. Pass Git's bash explicitly.
- Remove each worktree once its PR merges.

## Lessons

- **A census comment that says "names the file" is a claim.** `ast.parse(src)` and a decode error both name no file. The fix wraps both and adds a mutant, R10, that plants an unparseable file. "Fails loudly" was true; "names the file" was not, until the wrap.
- **Check the owner before addressing.** "fin and cost" read as two lanes. The roster has no cost lane, and the trailers on `cost_agent` commits say fin.
