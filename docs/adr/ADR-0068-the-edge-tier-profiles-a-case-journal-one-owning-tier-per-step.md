# ADR-0068 — The edge tier: tier profiles as configuration, a case journal, one owning tier per step

**Status:** Proposed 2026-11-11 (lane/01, drafted at the architect's order). **Not ratified.** It goes to the
architect, then to the reviewing party, before ratification. Not on the 0.4.85 train. Nothing below is built.
**Date:** 2026-11-11
**Deciders:** architect (to ratify). Drafted by lane/01. Positions §1–§5 were accepted in principle by the
reviewing party, which added the four requirements recorded as §6–§9 (architect, via Chris, 2026-11-11).
**Related:**
  - ADR-0067 (one identity per thing): an occurrence is its episode plus
    `detected_at_ns`. The journal's entries (§3) carry that occurrence id where one exists.
  - ADR-0029 (the process-workflow model): the step model. A step is the unit a tier
    owns (§4).
  - R-088 (`docs/rulings/README.md`): releasability is decided twice and each decision fails closed. It holds at
    every tier boundary (§3, last bullet).
  - `policy/gateway_delegates.yaml`: today's only delegation rows, for a service naming a person. §5 adds rows
    for a person delegating to a person.

---

## The problem

A step can be acted on at a tier that is cut off from the central tier for hours or days. Today there is one
deployment shape, and the case's state lives in two kinds of place, both updated in place:
- the case runner's per-episode keyed state;
- the projection tables (`human_task_projection`, `ingest_status_projection`).

Neither can be merged after a partition. Nothing records which tier may decide a step, and nothing stops two
tiers from both deciding it.

## Decision

### §1 A tier is a profile, and a profile is configuration

- A tier is a named row in a policy file (proposed: `policy/tiers.yaml`), validated by `validate_policy` like
  every other rail. A row states:
  - the tier's name and its parent tier;
  - the capabilities it runs;
  - the stores it holds;
  - the peers it replicates with;
  - the manual set it carries copies of (§9).
- **No code names a tier.** The audience template `{trigger.owning_tier}` already takes the tier as data; this
  record makes the rest of the tier data too.
- **A definition that gives a step to a tier whose profile lacks a capability the step declares is refused
  when it loads.** It is not discovered at run time on a disconnected tier.

### §2 The minimal edge profile

An edge tier that owns a step must run, offline:
- the door, verifying tokens against an identity key it holds locally;
- the case runner, for the steps it owns;
- the case journal (§3);
- a task list served per viewer (§6);
- a **policy snapshot**: the grants, label entitlements, ownership rows and delegation rows it needs (§5). The
  snapshot carries a version and a digest, and every journal entry names the snapshot version it was decided
  under;
- versioned manual copies (§9).

Retrieval and synthesis capabilities are optional, per profile. A step that needs one cannot be owned by a tier
whose profile lacks it (§1, last bullet).

### §3 The case journal replicates by append-only entry

- Every case has a journal. An entry is never rewritten or deleted; a correction is a new entry that names the
  entry it corrects.
- An entry carries:
  - `entry_id`: a uuid5 over (case id, writing tier, tier sequence). It is deterministic, so a replay produces
    the same id;
  - `case_id`;
  - `occurrence_id` (ADR-0067), where the entry is caused by one;
  - `tier` and `tier_seq`: the writing tier and that tier's own gap-free sequence;
  - `actor` (an authz_id) and `on_behalf_of`;
  - `kind`: for example `case_opened`, `step_started`, `task_opened`, `task_closed`, `acted`, `routing_fault`,
    `ownership_handed`, `case_closed`;
  - `labels`;
  - `policy_version` (§2);
  - a digest of the payload.
- **Replication is by entry.** A tier sends each peer the entries that peer has not acknowledged. The receiver
  applies them by `entry_id`, so a second delivery is a no-op.
- **Catch-up is a cursor read:** `(tier, tier_seq)` for each peer. A reader that reconnects asks for entries
  after its cursor and gets every one it missed, in order, per tier.
- **Projections are derived from the journal.** That includes the task list and the case view, so two tiers that
  hold the same entries serve the same projection.
- **Each tier boundary decides releasability as R-088 does.** It decides on the entry's labels and fails closed.
  An entry that arrives without labels is refused and recorded, never given a default.

### §4 One owning tier per step

- Each step in a definition declares its owning tier, either by profile name or by a role resolved from the
  trigger (as `owning_tier` is resolved today).
- **Only the owning tier writes a step's `acted` and `task_closed` entries.** An entry for that step from any
  other tier is applied as a record of a refused write, never as the step's outcome. With one writer per step,
  two outcomes for one step cannot both be accepted.
- **Ownership moves only by an `ownership_handed` entry that the current owner writes.** Connectivity never moves
  it: a central tier that cannot reach the edge does not take the step back.

### §5 Ownership and delegation are policy rows

- Ownership assignments and delegations live in policy, never in code, and never as a group name in code.
- A delegation row states:
  - the delegator, the delegate and the scope (task kinds or audiences);
  - **an expiry, which is required;**
  - the grantor, the reason and `ratified_by` (a seat), as `gateway_delegates.yaml` rows do.
- **An expired row grants nothing.** The tier evaluates expiry on its own clock, and the entry records the clock
  reading it used.

### §6 The task list scopes on labels as well as on the recipient (requirement 2)

- A task is served to a viewer only if both hold:
  - the viewer is its recipient, matched by authz_id against the recipient row, or by a capability read from
    policy;
  - the viewer is entitled to every label dimension of the object the task carries.
- **A task that fails the label check is withheld from that viewer, never redacted.** It is recorded as a
  `routing_fault` entry and a decision line naming the task, the addressee and the label dimension that failed.
  The task's audience reached someone who cannot see its object, so the fault is in the routing.
- The same rule applies to every read that admits a viewer because they hold a task, including `approvals[].task`
  on the case read and admission to the case itself.

### §7 A delegated act is marked as delegated (requirement 3)

An `acted` entry made under a delegation records:
- the delegator;
- the delegate, who is the actor;
- the expiry of the delegation row it used;
- the row's identity.

It replicates with `delegated: true`. A reader on any tier can tell a delegated act from a direct one without
consulting policy.

### §8 A reader's stream stays dark until its seal is deployed (requirement 1)

- A stream of task entries opened to an outside reader stays closed until the per-viewer seal of §6 is deployed
  on the instance that reader reads.
- "Deployed" is read from the deployment's release record for that instance, not from a branch, a tag or a
  changelog.
- The reader is told the release and the instance, as read, when it is true.

### §9 Edge manuals are versioned copies (requirement 4)

- A tier serves a manual as a copy that carries:
  - `revision`: the publisher's revision of the source of record;
  - `digest`: a sha256 of the content served;
  - `age`: the time since the copy was taken from the source of record.
- Every response that cites a manual node carries all three, so the UI can show them.
- An `acted` entry names the revision and digest of each manual node consulted.

## What iagent builds from it

This list takes effect only after ratification, and each item ships in its own PR.

1. **The per-viewer task list, label scoping included.** This is the approvals[].task PR on the train after
   0.4.85. It builds §6 on today's tables before the journal exists, because §6 does not depend on the journal.
2. **`policy/tiers.yaml`** with its validation (§1) and the load-time refusal (§1, last bullet).
3. **The journal** (§3), with `task_opened` and `task_closed` as its first entry kinds, written in the same
   transaction as the projection write. It exposes a cursor read behind the door.
4. Delegation rows with expiry (§5), and the delegated-act fields (§7).
5. Manual copies with revision, digest and age (§9).
6. Step ownership and `ownership_handed` (§4).

## Deltas

Each delta is today's state, measured on `4a1e1b5a`.

- **Tiers.** A tier exists only as a value substituted into an audience template (`{trigger.owning_tier}`), and
  as tier groups in `policy/groups.yaml`. One of those groups has been unused by any definition since 2026-10-28.
  There is no profile, no capability check per tier, and no policy snapshot.
- **The journal.**
  - Case state is the runner's per-episode keyed state: the open case, its head revision, and occurrences
    de-duplicated by `event_id`. There is also an append-only list of instance outcomes. Neither has an entry
    id, a tier, or a sequence.
  - `human_task_projection` is updated in place (`mark_task_resolved`, `expire_open_task`,
    `supersede_open_task` in `src/iagent/human_tasks.py`). Its row ids are random and one per recipient.
  - There is no occurrence id for a task opening or closing. The expiry and supersede closes record no actor and
    no decision.
- **Task events.** Opening and closing a task emit a database write and a log line, nothing a reader can
  consume. The live inbox shape filters on `recipient_id = X AND status = 'pending'`, so a close reaches the
  reader only as the row leaving the shape, with no decision or actor. No route takes a cursor.
- **The per-viewer list.**
  - `GET /me/human_tasks` filters on `recipient_id` and `status = 'pending'` only (`human_tasks.inbox_where_params`).
    It checks no labels when it reads.
  - Recipients are expanded from the directory once, when the task is registered, and only one level deep.
  - `list_tasks_for_workflows` (`human_tasks.py:854`), which the case read uses, is not scoped by recipient.
  - `holds_task_on_case` (`human_tasks.py:745`) admits a viewer to a case because they are a task recipient,
    without the label check §6 requires.
- **Delegation.** `policy/gateway_delegates.yaml` rows let a service name a person on a named route. They have no
  expiry. There is no row for a person delegating to a person, and no act is marked as delegated.
- **Manuals.** No manual read or schema carries a revision, a digest or an age.

## Check

Each item below is asserted when the corresponding piece is built, not before.

- **§6.** For one task:
  - an addressed holder with the label sees it;
  - a reader who is not addressed does not;
  - **an addressed holder without the label sees nothing, and a `routing_fault` is recorded.**

  The control for that last arm is the same holder, given the label, seeing the task. The same arms run on the
  case read's `approvals[].task`.
- **§3.**
  - Applying one entry twice yields one entry.
  - Two tiers given the same entries in different orders serve equal projections.
  - A cursor read after a gap returns every missed entry.
  - An entry without labels is refused at the boundary.
- **§4.** An `acted` entry for a step from a tier that does not own it is recorded as a refused write, and the
  step's outcome is unchanged.
- **§5, §7.**
  - An expired delegation grants nothing.
  - A delegated `acted` entry carries the delegator, the delegate, the expiry and the row's identity, and
    `delegated: true` survives replication.
- **§8.** The reader is told the release and instance as read from the release record, and the reader's packet
  quotes that read.
- **§9.** Every response that cites a manual node carries `revision`, `digest` and `age`. A seal fails if any one
  of them is missing.

## What this does not establish

- **The transport between tiers.** This record fixes what an entry is and how it is applied, not how it travels.
- **Clock agreement between tiers.** Expiry (§5) and `age` (§9) are read on the deciding tier's own clock, and the
  entry records that reading. Bounding the skew is not decided here.
- **Which capabilities a given deployment's edge runs, and any deployment's tier map.** Both are rows, written by
  whoever deploys.
- **Merge rules beyond one writer per step.** §4 removes the need for them for step outcomes. Case-level fields
  written by more than one tier are not covered, and none is proposed.
- **Ratification.** This draft decides nothing until the architect ratifies it after review.
