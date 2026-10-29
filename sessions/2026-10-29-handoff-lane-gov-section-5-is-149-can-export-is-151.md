# Handoff: lane/gov, 2026-10-29 (overnight)

to: invincible-agent/lane/gov (worktree ia-gov)
from: invincible-agent/lane/gov, 2026-10-29

This replaces `2026-10-28-handoff-lane-gov-can-drop-is-134-adr-0062-section-5-pushed.md`.

## The overnight directive (architect via Chris, verbatim)

> to: invincible-agent/lane/gov — overnight: §5 of ADR-0062 (merge policy); then export-profile policy: who may export which profile (can_export:<profile>), AP group default, on the rail.

Both parts are built and open as PRs. Neither has merged, and CI on neither has been read.

## State

| branch | tip | PR | status |
| --- | --- | --- | --- |
| `lane/gov` | this commit | none | handoff carrier |
| `lane/gov-repository-paths-rail` | `f7e83ad3` (on master `47502b35`) | #149 → master | §5 rail. Seal 42; 14 mutants. R2 and R13 were quiet, got arms, and are now red. |
| `lane/gov-can-export-rail` | `221bbb65` (on master `47502b35`) | #151 → master | can_export. Seal 19; 10 of 10 mutants named-red. No rows ship. |
| `lane/gov-recipient-readers-rail` | merged | #127 | MERGED `47502b35`, 2026-10-29T03:04Z |
| `lane/gov-drop-grants-alert-processors` | merged | #134 | MERGED |
| `lane/gov-sandbox-grantor-overlay` | merged | #126 | MERGED |

**#149 and #151 conflict textually** in `policy/sync/validate_policy.py` and `CHANGELOG.md`. Gov rebases whichever merges second.

**The refusal seal is green on master.** Lane 1 classified engine-r's 19 sites at `2d02de28`. My 10-28 packet saying master was red is marked SUPERSEDED in the master tree, and is still untracked.

## Design forks, all named in the PRs and packets for the architect

1. **§5:** `policy/asset_grants.yaml` has no row of its own. Rule 8 refuses `access_grant:DATA_ENGINEERING` (1 user) at 2, so the file falls under `policy/` until the architect rules. An arm pins the absence.
2. **§5, rule 7:** POLICY = {alice, bob}, so a 2-approver `policy/` change proposed by a human cannot close. A service-identity proposer works.
3. **can_export:**
   - What is the CDRL default grantee?
   - Does it gate a single export, the batch, or both?
   - What does "Request access" file?

## Packets placed (untracked, master tree `sessions/`)

- `2026-10-29-packet-to-lane-01-section-5-rail-is-pr-149-your-two-questions-and-leak-terms.md`: answers Q1 and Q2, and gives four mutants that would show whether the leak_terms exemption is guarded.
- `2026-10-29-packet-to-lane-01-fin-cortex-can-export-is-pr-151-deny-by-default-ap-default-by-completeness.md`, cc saf and the architect. It is also placed in `cortex-ui/sessions/`.

## Next (in order)

1. **Read CI on #149 and #151.** Rebase the second when the first merges.
2. **When Lane 1's can_drop door PR opens:**
   - check that its existence read raises on a transport error;
   - check that `droppable_kinds` comes from the same reads;
   - check that the 403 names family `capability_grants`.
3. **When Lane 1's export door or `policy/exports/` lands:**
   - check that every profile ships its `can_export:` row;
   - check that any overlay env var is added to `known_export_profiles`.
4. **When fin moves a table:** review the seal side.
5. **Per-site RELAY adoption:** 10 rows.
6. **The ruling-3 candidates audit.**
7. **The SDK v0.9.12 swap.**
8. **Carried, not re-checked:** Q11, Q17–Q26.

## Scratch (the session scratchpad; disposable)

- `rp/` is #149 and `ex/` is #151. Remove each once its PR merges.
- `pr2/`, `pr3/` and `pr4/` were removed: all three are in master.
- `adr62/` (detached `511e5927`, on #123's branch) is being removed.
- **Mutant drivers:** `mut_rp.py`/`mut_rp2.py` (the rail) and `mut_ex.py` (can_export). Args: pr, bak, gate (Windows path), bash (Windows path), and optionally a comma list of mutant ids.

## Lessons

- **Pass bash to a Python driver as a full Windows path** (`cygpath -w /usr/bin/bash.exe`). A bare `bash.exe` from Python resolved to some other bash. The gate "failed" for every mutant, and the run reported 14 skips in seconds.
- **`Path.write_text` on Windows writes CRLF.** A packet rewritten through it gained 84 CRs. Normalize with `sed -i 's/\r$//'`, and count with `tr -cd '\r'` before placing.
- **Write a commit message's mutation section only after the run.** I drafted E9's result ahead of the run, and I drafted it wrong.
