# ADR-0068 — The edge tier: tier profiles as configuration, a case journal, one owning tier per step

**Status:** Proposed 2026-11-11 (lane/01, drafted at the architect's order). **Not ratified.** It goes to the
architect, then to the reviewing party, before ratification. Not on the 0.4.85 train. Nothing below is built.
**Date:** 2026-11-11
**Deciders:** architect (to ratify). Drafted by lane/01. Positions §1–§5 were accepted in principle by the
reviewing party, which added the four requirements recorded as §6–§9 (architect, via Chris, 2026-11-11). The
architect accepted the shape on 2026-11-11 and ruled entry and occurrence identity (§3: a minted UUIDv7, with a
uuid5 only as the dedupe lookup key). It is open as a draft PR so it can be read, and it stays Proposed.
**Amended 2026-11-11** at the architect's review, with four amendments:
  - §2: the snapshot's maximum age, and the re-check on reconnect;
  - §2: the door checks issuer and audience;
  - §3: an entry with no labels, and one whose labels are empty;
  - §4: who writes `case_closed`.
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
  - the manual set it carries copies of (§9);
  - `snapshot_max_age` and `on_snapshot_stale` (§2). Both are required. A profile that lacks either is refused
    when it loads, because no default is chosen in code.
- **No code names a tier.** The audience template `{trigger.owning_tier}` already takes the tier as data; this
  record makes the rest of the tier data too.
- **A definition that gives a step to a tier whose profile lacks a capability the step declares is refused
  when it loads.** It is not discovered at run time on a disconnected tier.

### §2 The minimal edge profile

An edge tier that owns a step must run, offline:
- **the door**, verifying tokens against an identity key it holds locally. Verifying a token includes its
  issuer and its audience:
  - each is checked against a list read from the tier's served values, never a literal in code;
  - **an empty list refuses every token.**

  cortex-bff does this from 0.4.85 (#349, merged at `3c85f53d`; `src/iagent/auth.py` `verified_claims`,
  served from `cortexBff.auth.acceptedIssuers` and `acceptedAudiences`). An edge door does the same from its
  own profile's served values;
- the case runner, for the steps it owns;
- the case journal (§3);
- a task list served per viewer (§6);
- a **policy snapshot**: the grants, label entitlements, ownership rows and delegation rows it needs (§5). The
  snapshot carries a version and a digest, and every journal entry names the snapshot version it was decided
  under;
- versioned manual copies (§9).

**When the snapshot is too old.** Each tier profile declares two rows:
- `snapshot_max_age`: the maximum age of its policy snapshot;
- `on_snapshot_stale`: what happens once that age is exceeded. The value is `keep_acting` or
  `refuse_new_acts`.
  - Under `keep_acting`, the tier goes on deciding on the snapshot it holds.
  - Under `refuse_new_acts`, it writes no new `acted` entry until a fresher snapshot arrives. It records each
    refusal.

Both rows are required, and no default is chosen in code (§1). Age is read on the tier's own clock (see "What
this does not establish").

**Either way, every entry names its `policy_version`.** When the edge reconnects, the central tier re-checks
every act written under a version older than the current policy:
- An act the current policy would now refuse is recorded as a **`policy_finding` entry**. It names the
  act's `entry_id`, the version it was decided under, the current version, and the rule that now refuses it.
- **A finding never rewrites the entry it is about.** The act stands in the journal as it was decided. The
  finding is a new entry beside it, which a reader or a later step can act on.

Retrieval and synthesis capabilities are optional, per profile. A step that needs one cannot be owned by a tier
whose profile lacks it (§1, last bullet).

### §3 The case journal replicates by append-only entry

- Every case has a journal. An entry is never rewritten or deleted; a correction is a new entry that names the
  entry it corrects.
- An entry carries:
  - `entry_id`: **a UUIDv7, minted once by the writing tier** (ADR-0067 §1: an identity is a v7 minted by the
    authority that owns the thing). A replay keeps the same id because the journal hands back the entry already
    minted. The id is never recomputed;
  - `case_id`;
  - `occurrence_id` (ADR-0067), where the entry is caused by one. A `task_opened` or `task_closed` entry is its
    own occurrence, and its `occurrence_id` is that entry's minted v7;
  - `dedupe_key`, where a writer may retry: a uuid5 over (case, step, transition). It is a **lookup key only,
    never an identity**. Before minting, the writer looks the key up; if an entry holds it, that entry's minted
    id is handed back and nothing new is written;
  - `tier` and `tier_seq`: the writing tier and that tier's own gap-free sequence;
  - `actor` (an authz_id) and `on_behalf_of`;
  - `kind`: for example `case_opened`, `step_started`, `task_opened`, `task_closed`, `acted`, `routing_fault`,
    `ownership_handed`, `case_closed`, `policy_finding` (§2);
  - `labels`;
  - `policy_version` (§2);
  - a digest of the payload.
- **Replication is by entry.** A tier sends each peer the entries that peer has not acknowledged. The receiver
  applies them by `entry_id`, so a second delivery is a no-op. A receiver never mints for an entry it receives;
  the id travels with the entry.
- **Catch-up is a cursor read:** `(tier, tier_seq)` for each peer. A reader that reconnects asks for entries
  after its cursor and gets every one it missed, in order, per tier.
- **Projections are derived from the journal.** That includes the task list and the case view, so two tiers that
  hold the same entries serve the same projection.
- **Each tier boundary decides releasability as R-088 does.** It decides on the entry's labels and fails closed.
  - **An entry with no `labels` field is refused**, and the refusal is recorded. It is never given a default.
  - **An entry whose labels are empty is judged by that boundary's declaration**, dimension by dimension. A
    boundary can declare `required` (an empty or absent value is withheld there) or `empty_means`
    (`admits_everyone` or `admits_no_one`). Both are set per boundary in
    `policy/classification/dimensions.yaml`. Where a boundary declares neither, the dimension type's own
    meaning holds, as ADR-0064 tabulates it.
  - In every case the meaning is read from policy at that boundary. It is never a default chosen in code.

### §4 One owning tier per step

- Each step in a definition declares its owning tier, either by profile name or by a role resolved from the
  trigger (as `owning_tier` is resolved today).
- **Only the owning tier writes a step's `acted` and `task_closed` entries.** An entry for that step from any
  other tier is applied as a record of a refused write, never as the step's outcome. With one writer per step,
  two outcomes for one step cannot both be accepted.
- **`case_closed` is written only by the tier that owns the step that reaches the terminal stage.** A
  `case_closed` from any other tier is applied as a record of a refused write, as above. The case stays open,
  so closing a case has one writer as well.
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

1. **The per-viewer task list, label scoping included.** This is the approvals[].task PR, **the first PR on the
   train after 0.4.85**. Until it ships, a task holder is admitted to a case without the label check on every
   deployed release. It builds §6 on today's tables before the journal exists, because §6 does not depend on
   the journal. It also adds a per-viewer **Needs-you read**: what waits on this viewer, by kind, label-scoped
   as the task list is. The UI reads its count from that route instead of composing it.
2. **`policy/tiers.yaml`** with its validation (§1), including the two snapshot rows (§2), and the load-time
   refusal (§1, last bullet). The reconnect re-check writes `policy_finding` entries (§2) once the journal
   exists.
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
- **The door.** Through 0.4.84, cortex-bff checked a token's signature and expiry and nothing else: it ran
  `verify_aud: False`, with no issuer. #349 (merged at `3c85f53d`, on 0.4.85) adds both checks, from served
  lists. The engines' SDK check (`transport_auth`) still checks neither; that fix is SDK v0.9.20.
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
  - A retried write with the same `dedupe_key` hands back the first entry's minted id and writes nothing.
  - Every `entry_id` is a version-7 UUID; none is a uuid5.
  - Two tiers given the same entries in different orders serve equal projections.
  - A cursor read after a gap returns every missed entry.
  - An entry with no `labels` field is refused at the boundary and recorded. Control: the same entry with its
    labels is applied.
  - An entry whose labels are empty is judged by the boundary's declaration:
    - `admits_no_one` withholds it;
    - `admits_everyone` releases it;
    - `required` withholds it as `dimension_missing`;
    - a boundary that declares nothing applies the type's meaning.

    A source check finds no default for an empty set in the boundary's code.
- **§2, the door.** A token with the wrong issuer is refused, and so is one with the wrong audience. An empty
  served list refuses every token. Control: the correct token is admitted.
- **§2, the snapshot.**
  - A profile without `snapshot_max_age` or `on_snapshot_stale` is refused when it loads.
  - Past the age, under `refuse_new_acts`, an act is refused and recorded. Control: the same act within the
    age is admitted.
  - Past the age, under `keep_acting`, the act is admitted and names its `policy_version`.
  - After reconnect, an act the current policy refuses gets exactly one `policy_finding`, and the act's entry
    is byte-identical before and after. Control: an act the current policy still admits gets no finding.
- **§4.**
  - An `acted` entry for a step from a tier that does not own it is recorded as a refused write, and the step's
    outcome is unchanged.
  - A `case_closed` from a tier that does not own the terminal step is recorded as a refused write, and the
    case stays open. Control: the owner's `case_closed` closes it.
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
- **Which tier writes `case_opened`.** This is the one case-level write left with more than one possible writer.
  §4 gives step outcomes and `case_closed` one writer each, and the current owner writes `ownership_handed`.
  `routing_fault` and `policy_finding` record decisions and set no case state, and every projection is
  derived (§3). Nothing here says which tier opens a case. So two tiers that each receive an occurrence for
  the same episode during a partition could each write a `case_opened`. This record does not decide that, and
  proposes no merge rule for it.
- **Ratification.** This draft decides nothing until the architect ratifies it after review.
