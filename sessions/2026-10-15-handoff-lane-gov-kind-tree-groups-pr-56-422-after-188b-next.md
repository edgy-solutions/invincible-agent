# Handoff: lane/gov, 2026-10-15

to: invincible-agent/lane/gov (worktree ia-gov; branches lane/gov, lane/gov-resolve-instance, lane/gov-enumerate-gate, lane/gov-caller-census, lane/gov-narrow-except, lane/gov-kind-tree-groups)
from: invincible-agent/lane/gov, 2026-10-15

This replaces `2026-10-14-handoff-lane-gov-except-narrowed-pr-54-422-after-188b-next.md`.

## State

| branch | tip | PR | status |
| --- | --- | --- | --- |
| `lane/gov` | this commit | #32 → master | open |
| `lane/gov-resolve-instance` | `ac6e4ff0` | #39 → lane/gov | ACCEPTED (in rev 187) |
| `lane/gov-enumerate-gate` | `9393ff08` | #45 → lane/gov-resolve-instance | ACCEPTED |
| `lane/gov-caller-census` | `bb0b5190` | #47 → lane/gov-enumerate-gate | ACCEPTED; for the 188 landing |
| `lane/gov-narrow-except` | `16aa5450` | #54 → lane/gov-enumerate-gate | APPROVED (2026-10-15) |
| `lane/gov-kind-tree-groups` | `77f5a795` | #56 → **lane/01-rev189** | open; Lane 1's work-instruction row lands behind it |

All six branches are pushed. The full record is `sessions/2026-10-10-report-gov-origin-at-read-and-on-promotion.md`, section "2026-10-15".

## Rulings (architect)

- **2026-10-14:** "a svc: literal counts as absent in every arm, same as blank; a service identity is never a person." Built at `bb0b5190`.
- **2026-10-14:** "accepted; the engine-side 422 refusing svc: after 188b, as you say."
- **2026-10-15:** "#54 approved. The kind-tree test must count a group grant as a recipient (group → members) — fix the test, Lane 1's work-instruction row lands behind it." Built as #56.
- **2026-10-15, later (gov's list):** "kind-tree test counts group grants; 422 no_person incl. svc: after 188b; resolve_instance gate PR rebased on 74's decide(); packet census → Lane 1 list; AnswerArtifact origin field only when a writer appears."
  - **"resolve_instance gate PR" is #54; RULED: wait for 188b.**
    - 189 branches from 188 (`c9091040`), not from 188b. #45 and #47 sit only on 188b, and #54 is stacked on #45.
    - Measured with `git merge-tree`: #54 picked alone onto `lane/01-rev189` conflicts in `main.py`, and `_gate_enumerated_members` doesn't exist there.
    - So: rebase #54 onto 74's decide() only once 188b is under 189, or decide() is on 188b. Use a new branch, no force-push.
    - 74's decide() change (the same-class tie in `instance_resolution.decide`, per saf's 10-15 packets) was not on any pushed ref on 10-15.
  - **Packet census: RULED done** (the 10-11 list). The misfile it reported is resolved, since the Q10 parser (`e5fb8319`, `9766f984`) is in master. No refresh.
  - **188b status at 10-15:** held, "stopped on lane/74's person-chain seal" (`13be1472`).

## Brief, 2026-10-16

From the architect, via Chris — act on it.

> to: invincible-agent/lane/gov
> Origin on promoted PCN rows: after Lane 1's e2e promotes as bob, read the origin record and confirm resolved_by, steward_confirmed, and that visible_by_origin withholds for a user outside the audience. Day 2: the /ingest/{id}/source grant — review the 403 rule against the seal.

The pasted header read `ia-gov/lane/gov`. Chris says the worktree form was his error, ruled form above, and asks that the pasted form not be carried forward.

Chris's instruction is to do it exactly as laid out, with a matched control: a user inside the audience who sees the row.

**State at 2026-10-16: both items are blocked on a missing precondition.** Checked across `git log --all` on every fetched ref, Lane 1's worktree (tracked, modified and untracked files), and all packets in master's and ia-01's `sessions/`.

- **Item 1. Lane 1's bob promotion has not run.**
  - No file holds both bob and a promotion on any ref or in ia-01, and no packet reports such a run.
  - The nearest file is `tests/sandbox_e2e/_seal_pcn_review_bff.py`, where bob only reads the qualification queue.
- **The brief's names, mapped to the code:**
  - `visible_by_origin` is `agent_fleet/utils/origin_entitlement.py:129` (master).
  - `resolved_by` is the node property `origin_resolved_by`.
  - **`steward_confirmed` exists nowhere** (`git log --all -S` is empty). The nearest shape is the steward rung `promotion_stores.py:301-319`: `origin_resolved_by: "steward"`, with `origin_evidence` carrying `steward_attestation` and the decision record, and no `origin_program`. Gov will read `steward_confirmed` as that shape unless the architect says otherwise.
  - The record is a Neo4j node property, read by artifact id (`gateway.py` `_ARTIFACT_BY_ID_CYPHER`). No route reads it by ingest or notice id.
- **The plan when bob's run appears** (read-only; no live write):
  - Read the promoted row's `origin_*` properties.
  - Decide `visible_by_origin` for two users: one outside the audience (a user whose domains cannot consume the owner domain), and a **matched control** inside it. The two must share the gate and the population, and differ only in audience membership.
  - The probe matches the sheet's caller cell.
- **Item 2 (Day 2). `/ingest/{id}/source` does not exist.**
  - No route, no 403 rule and no seal on any ref (`git log --all -G`), and no packet or doc names it.
  - Ingest routes on master: `POST /ingest`, `/ingest/events`, `GET /ingest/{id}/status`, `POST /ingest/{id}/retry`, `/ingest/{id}/stage`.
  - Gov reviews the 403 rule against its seal once both are pushed.

## What #56 is

- **The predicate:** a recipient is a `grant_to` user, or a `users.yaml` member of a `grant_to_groups` group that `groups.yaml` declares. Memberless and undeclared groups reach nobody, as in `validate_policy.unusable_group_audiences`.
- **The arms:**
  - a two-sided control (7 cases);
  - the join with `validate_policy`, over real policy plus a fixture holding one group of each outcome;
  - every `document_promotion` audience reaches someone.
- **Results:** 64 passed; with a stand-in work-instruction row, 74 passed. K1–K3 and V1–V2 are each red on a named arm.

## Placed (untracked in master's `sessions/`)

- `2026-10-15-packet-to-lane-01-kind-tree-seal-counts-group-members-pr-56-your-row-can-land.md`, cc the architect.

## Worktree note

- **`lane/gov-kind-tree-groups` (and anything based on `lane/01-rev189`)** tracks five packets that `lane/gov` leaves untracked. Backups are in the session scratchpad, `untracked-bak2/`.
  - Checking out `lane/gov` removes them; restore them from the backup, then cmp. This was done on 2026-10-15, and all five cmp identical.
- **`lane/gov-caller-census`** has the same dance with three packets, `untracked-bak/`.

## Next

1. **#56 review.** Then Lane 1 commits the row and runs the file again with it in. The stand-in may differ from the real row in its passes and outputs.
2. **Q11 (open): `svc:` group members.** Latent; not built.
3. **The 422 `no_person` on engine O, after 188b lands (RULED 2026-10-14).**
   - Population: rows 13–16.
   - It also refuses `svc:`.
4. **#54 onto 74's decide(), once 188b is under 189 (RULED: wait).** Check first: `git merge-base --is-ancestor origin/lane/gov-enumerate-gate <189 tip>`, and that 74's decide() commit is pushed. Rerun #54's five files gated.
5. **The AnswerArtifact "how resolved" field, only when a writer appears (RULED).** The trigger is `test_the_answer_artifact_writer_writes_no_origin_today` going red.

## Lessons

- **A join arm decided over a population with one outcome cannot see a disagreement.** Real policy has no unusable group, so mutants K2 and K3 left the join green. Give the join a fixture holding every outcome, and assert that both outcomes occur.
- **`Path.read_text()` with no encoding is cp1252 on this box.** A policy file with non-ASCII bytes fails collection, and that crash is not a red.
- **`run_files.sh` exits with its last test, not with pytest's rc.** Read the `rc=` in the log.
