# ADR-0062 — The mesh owns its repositories; forges are mirrors

**Status:** Draft. On 2026-10-28 the architect accepted §1–§3, §6 and §7 and ruled on the open
questions. The rulings are folded in here. The ADR moves to Proposed when lane/74 writes §4 and
lane/gov writes §5. Nothing is built.
**Date:** 2026-10-28
**Deciders:** architect (decision); Chris (review); Lane 1 (draft: §1–§3, §6–§8); lane/74 (§4);
lane/gov (§5)
**Related:**
  - [`ADR-0026`](ADR-0026-persona-entitlement-topaz-authorization.md): Topaz authorization. A
    merge to a grant path takes effect through the Topaz sync (§6).
  - [`ADR-0041`](ADR-0041-user-contributed-documents-ingest-on-arrival-provenance-gated-truth.md):
    the dropper rule. Whoever proposes a change may not approve it. Review in engine-r uses the
    same exclusion. `sessions/` has one ruled exception (§2).
  - [`ADR-0054`](ADR-0054-data-classes-every-write-declares-what-it-is.md): data classes. §2
    declares engine-r's repository store in ADR-0054's four fields.
  - [`ADR-0057`](ADR-0057-the-model-is-edited-by-conversation-and-changed-by-review.md): a model
    change is ratified by review, and approval produces "a PR". In engine-r, that step becomes a
    proposal (§6).
  - ADR-0061 (a workflow is described in dialogue and compiled to rows). It is on
    `lane/74-socratic-workflow`, **not on master**. §4 is written against it.

## Context

A forge is a hosted git service with a review layer on top. In the deployments this platform
targets, forges are deployed, deprecated and replaced faster than anyone can support them.
Several can be live at once, and their life spans are shorter than the data they hold.

Git's data model is stable. Objects, refs and history from ten years ago read the same today.
The forge's layer is not: branch protection, required reviewers, review threads, merge policies,
webhooks and audit logs. Each forge models these differently, and none of them export cleanly.
When a forge is retired, everything recorded in that layer leaves with it.

The mesh already governs its own changes by convention:

- **A merge is gated, and it is by sha.** The merger merges the agreed sha and reads back the
  second parent.
- **A pushed release tag never moves.** A defect is a patch, and the release job is repaired only
  by a logged dispatch at the release sha (ruled 2026-10-25, #93).
- **Every commit carries its lane in a trailer** (R-058), and a pre-push hook refuses a commit
  without one.
- **No secrets, no infra detail and no customer-identifying context in a commit.** A leak scan
  runs before every commit.
- **A proposer may not approve their own proposal** (ADR-0041, ADR-0057 §4).

Today these rules live in hooks, charters and habit. One forge enforces them, and that forge has
no knowledge of them. Moving forges would mean rebuilding every rule in the next forge's model.

**Decision:** the mesh holds its repositories of record itself. Any forge is a mirror and a place
where humans can interact. It is never the record.

## Decision

### 1. Scope

**In scope at runtime** is what the mesh reads in order to run:

- `policy/`: grants, canvases, task kinds, workflows, overlays, systems of record and the rest of
  the policy rail;
- workflow specs (§4);
- ADRs;
- overlays;
- fixtures and goldens;
- packets (`sessions/`).

**Out of scope:**

- **Application source and its CI.** Engine code, the chart and the build pipeline are still
  authored and built on the forge, and **the forge remains their writer** until a follow-on ADR.
  engine-r holds these paths because it holds the whole repository (below), but it refuses to
  merge any change to them (§2, check 6).
- **Large binaries.** Images, model weights and captured fixtures above a size bound stay in
  their stores (registry, object store). A repository may reference them by digest; it does not
  hold them.
- **An agent-scale VCS.** Our write rate is hundreds of commits a day across all lanes. That
  rate is well within what git handles on a single writer, and nothing here is designed for a
  write rate orders of magnitude higher.

**Repository shape.** engine-r holds the **whole invincible-agent repository**. Verbs and §5's
policy are scoped **by path**. No history is rewritten, so every packet's sha citation stays
valid.

### 2. engine-r

engine-r is the mesh engine that holds repositories of record. The name stands. It is
registered per [`docs/runbooks/adding-an-engine.md`](../runbooks/adding-an-engine.md) in the
first-slice PR, not by this ADR.

**Storage.**

- Bare repositories live on cluster storage.
- Access is in-process through libgit2 (pygit2). There is **no shell-out** to a `git` binary and
  **no forge** in the path.

**Data class (ADR-0054).**

| field | value |
| --- | --- |
| reproducibility | **stateful**. The repositories are the record. They cannot be rebuilt from anything else once the forge stops being the record. |
| authority | **here**. engine-r is the system of record for the repositories in §1. |
| sync obligation | **mirror-down**, to each configured forge (§3). |
| releasability | RESERVED (as ADR-0054 leaves it) |

**One writer.**

- **The engine is the only writer of refs.** It performs every merge and every tag. No forge, no
  lane and no human pushes a ref directly. The forge's writing of application paths (§1) is the
  one exception, and it is settled at cutover (Open questions).
- Ref updates for a repository run on one single-writer key per repository, as a Restate
  virtual object keyed by repository id. Two merges into one repository are serialized by
  construction, not by a lock someone has to remember.

**Verbs, in mesh terms.**

| verb | what it does |
| --- | --- |
| `propose` | Creates a proposal: a branch under `refs/proposals/<id>`, its commits and a stated intent. The proposal records its **head sha**. |
| `review` | Files an **approval task** for the proposal. The task carries the diff of the proposal head against the target ref. It renders in cortex on the review card layout that `PromotionReviewCard` established: a top line, rows on the left, the source on the right, and actions. cortex-ui's review card spec is the reference; cortex names its file. Who may review is §5's. |
| `merge` | Merges the proposal **by sha**. The merge names the head sha that was reviewed. If the proposal moved after review, the merge refuses. The result is a merge commit whose second parent is the reviewed sha (never a squash). A merge closes its proposal. |
| `tag` | Creates a tag at a named sha. A release tag is immutable (below). |
| `audit` | Reads the audit notes (below) for a repository, a path (through the commits that touched it) or a proposal. |

**Review exclusion.**

- ADR-0041's rule holds: a proposer may not approve their own proposal.
- **The one exception is in `sessions/`.** A packet proposal merges without review when the
  proposer is the owning lane of that path.
- **`policy/` always needs review.**

**Commit identity.**

Commits are **signed by the engine** on behalf of the caller. Three trailers say for whom, and
how that caller was authenticated:

```
On-Behalf-Of: <authz_id>
Auth-Via: local | brokered:<idp> | service
Proposal: <proposal-id>
```

`Auth-Via` records **authentication strength**:

- `local`: a mesh-local login;
- `brokered:<idp>`: brokered through the named identity provider;
- `service`: a service identity.

It is not the provenance ladder in `src/iagent/provenance.py` (`OBTAINED_VIA`), which grades
extracted values, not callers. The engine's signature attests that **the mesh** accepted the
commit; the trailers say **for whom**.

**Signing.**

- **Format:** git's ssh-signature format. git and libgit2 both support it.
- **Key custody:** the private key is held in a Kubernetes Secret.
- **Verification on mirrors:** the public key is published, so mirrors can show the engine's
  commits as verified.
- **Rotation:** yearly. Retired public keys are kept for verification, so old commits stay
  verifiable.

**Pre-receive checks.**

Existing rules become checks that run inside `merge` and `tag`, before any ref moves. A refusal
carries the standard refusal envelope.

1. **A merge by sha closes its proposal.** The merge must name the reviewed head sha. A merged
   proposal cannot be merged again or reopened under the same id.
2. **A release tag never moves**, except by a logged repair. The repair is its own verb call with
   a reason, and its audit note says so (#93's rule, moved from habit into the engine).
3. **No secrets.** The leak scan we run before commits today becomes a check over the
   proposal's diff.
4. **No customer-identifying context.** The diff contains no customer-identifying context —
   system names, column names, template names, hostnames, program names — in docs, code,
   fixtures or packets. Synthetic names only. This is Chris's standing rule, written into the
   engine.
5. **Every commit carries the three trailers** above. For repositories held in engine-r, this
   replaces R-058's lane trailer.
6. **Only governed paths merge.** A proposal whose diff touches a path engine-r does not govern
   (application source, §1) is refused with the policy envelope, reason **"path not governed by
   engine-r"**. This holds until the follow-on ADR. It is a new refusal site, so it is classified
   in the PR that builds it (ruled 2026-10-27).

**Audit.**

- **Where it lives.** Every accepted ref update writes an audit record as a **git note** under
  `refs/notes/audit`, on the merge commit (or on the tag object, for a tag). The record lives in
  the repository itself, content-addressed, and it mirrors with the objects. There is no second
  store.
- **What it holds:**
  - repository, ref, old sha and new sha;
  - the verb;
  - `On-Behalf-Of` and `Auth-Via`;
  - the proposal id;
  - the review task id;
  - the result of each pre-receive check;
  - the time.
- **Write order.** The note is written in the same single-writer step as the ref update, before
  the mirror push.
- **The completeness check.** Every merge commit on a target ref must carry a note, so a merge
  without one is itself an audit finding.
- **Refusals** move no ref and write no note. They are returned with the envelope.

### 3. Mirrors

**Outbound.**

- Each forge has one **push-mirror**, and the mirror is dumb.
- After every ref update, engine-r pushes the mirrored refs to the forge. These are the **target
  branches, the tags and `refs/notes/audit`**, so the audit travels with the objects it
  describes. **Proposal refs stay in engine-r.**
- The mirror carries no logic and no state of its own.
- On the forge, the mirror's identity is the only identity allowed to push. The forge's own merge
  path is disabled for mirrored repositories, so a forge-side merge cannot create a second
  history.

**Inbound.**

- **How changes are found.** By default, engine-r **polls** each forge for PRs and comments,
  because the networks this platform is deployed on rarely allow inbound webhooks. Where a forge
  can reach the mesh, a webhook is an optimisation over polling, not a replacement for it.
- **What a PR becomes.** A forge PR becomes an engine-r proposal. engine-r fetches the PR's head
  into `refs/proposals/<id>`, quarantined from every ref the mesh reads.
- **Who it belongs to.** The forge account maps to an `authz_id` through the same identity
  provider mapping that `policy/users.yaml` uses. A PR from an account that maps to no one becomes
  a proposal parked at `awaiting_identity`, visible to maintainers. It is never refused silently.
- **How it lands.** The proposal goes through the same review and checks as any other. If it is
  approved, **engine-r merges**, and the mirror pushes the result back. The forge sees its PR's
  head sha on the target branch.
- **Forge comments** attach to the review task as discussion. They are input to the task, not a
  record of the decision.

**Replacing a forge means re-pointing one mirror.** Nothing of record lives on the forge: no
policy, no review decision and no audit that engine-r does not also hold.

### 4. Workflows through the repository

> **Owned by lane/74. To be written in this PR.**
>
> The brief: a Socratic workflow spec is a proposal in engine-r. Its approval is the review task,
> and the runnable spec is the merged file. ADR-0061's loop ends in a `propose` verb, not a file
> write. (As drafted on `lane/74-socratic-workflow`, ADR-0061 ends in ratification and then a PR
> of the YAML bundle.)

### 5. Merge policy

> **Owned by lane/gov. To be written in this PR.**
>
> The brief:
>
> - Who may propose, review, merge and tag, per repository and per path, on the policy rail
>   with grantors. Refusals carry the envelope.
> - Which paths need a second approver. `policy/` and release tags do, in the same shape as
>   saf's second-approver rule; gov cites its tests in #114 and #115.
> - Which lane owns which `sessions/` path, for §2's exception.

### 6. Consequences and non-goals

**No forge UI is rebuilt.**

- cortex is the review surface: a proposal's review task is a card with its diff (§2).
- File browsing, blame, history graphs and code search remain wherever a human already reads
  them, which is usually a mirror.

**Application code stays on the forge: its writer and its CI.** A forge PR that touches
application source can still arrive as an inbound proposal (§3), but engine-r refuses to merge it
("path not governed by engine-r", §2 check 6). The forge remains the writer of those paths, and
their CI runs there, until a follow-on ADR.

**How a merge reaches the engines is unchanged for now.** Policy is baked into images at
`/app/policy` and applied by a roll. Two kinds of path take effect differently:

- **Grant paths:** `policy/program_members.yaml`, `policy/groups.yaml` and
  `policy/asset_grants.yaml`.
  - These **apply on merge, through the Topaz sync.** Authorization decisions change when the
    sync completes, not at a roll.
  - **engine-r runs the sync itself**, in-cluster, with the same credential the task-grant-sync
    hook uses, read from a Kubernetes Secret. No human is in the apply path. The hook stays, for
    rolls.
  - The baked copy still lags. Some engines also read these files from their baked copy: for
    example, the refusal hint's group list comes from `canvas_template.load_groups`. That copy
    catches up at the next pin-bump roll, and until then a hint can name the old groups.
- **Every other `policy/` path applies by roll.** A merge to `policy/` opens a **pin-bump
  proposal**, the change that moves the deployment's image pin to a build containing the merge.
  Its roll applies the change.

Engines reading policy from engine-r at runtime is a follow-on ADR, not this one.

**History already on GitHub is imported once, then mirrored.** The import brings the whole
repository's history into engine-r with its shas unchanged. At cutover (§7, Open questions),
engine-r becomes the record and GitHub a mirror like any other. Until then, the slice mirrors
to a separate repository.

**ADR-0057 §4 changes for `policy/`.** There, approval produces "a PR". Here it produces an
engine-r proposal, and engine-r performs the merge. The rule that a proposer may not ratify their
own proposal carries over unchanged.

**Backup becomes an obligation.** The mirrors carry the objects and the audit notes, but not the
review tasks or the proposals. The repositories' volume is the only complete copy.

**Lanes change how they hand off.** A lane places a packet by `propose`. Under §2's exception, a
packet merges without review when its proposer owns the path.

**Non-goals:**

- moving the authoring or CI of application source;
- large binaries;
- an agent-scale VCS;
- a general-purpose code host for anyone other than the mesh;
- user repositories (§8).

### 7. First slice

engine-r holds the invincible-agent repository on sandbox. It mirrors to a **separate GitHub
repository, `invincible-agent-mirror`**, not to the repository the lanes push to today. Mirroring
to the live repository would make engine-r and the lanes two writers of one master, which is
what this ADR forbids. Cutting over the real repository is its own decision, made after the slice
has measured. The slice exercises the `policy/` and `sessions/` paths.

The slice's real policy change is an **access request**, end to end:

1. **Propose.** A caller is refused. The refusal card's **Request access** action files a grant
   proposal to the path's `grantable_by`.
2. **Review.** The grantor's card approves it with **Grant**, or refuses it with **Deny**.
3. **Merge.** The merge applies the grant through the Topaz sync, not a roll.
4. **Retry.** The requester retries and succeeds.

This replaces today's case-1 fulfillment, `human_tasks.write_grant_and_sync`. That path writes
`asset_grants.yaml` inside the running pod and syncs, but never commits. Its own docstring says
the grant cannot be audited until the change is committed with the approver as author. In this
slice, the merge commit is that commit, signed on behalf of the grantor and carrying its audit
note.

The cortex side (the Request access action and the Grant and Deny actions) is specified now and
built after this ADR reads Proposed.

The slice is complete when it has been measured, with the audit record shown. The slice report
must show:

1. **The import.** The report gives the import's commit count and head sha against the live
   repository's at the import sha, and the two heads are equal. The whole repository is imported,
   so no sha is rewritten.
2. **The access request.** The report shows:
   - the requester's refusal;
   - the proposal id and its head sha;
   - the review task id, and the grantor who approved it;
   - the merge sha, whose second parent is the reviewed head;
   - the sync's completion, run by engine-r with no human in the apply path;
   - the requester's successful retry;
   - the sha on `invincible-agent-mirror` after the push, which must equal engine-r's;
   - the wall-clock time of each leg.
3. **The audit note** for that merge, as `audit` returns it, and the same note read back from the
   mirror.
4. **Four refusals, each observed and each carrying the envelope:**
   - a direct push to `invincible-agent-mirror` is refused;
   - an approval by the proposer is refused;
   - a merge naming a sha other than the reviewed head is refused;
   - a proposal touching an application-source path is refused, with "path not governed by
     engine-r".
5. **The mirror is re-pointed.** A second mirror target is configured and receives the same refs,
   and nothing else changes. This is a sandbox stand-in for replacing a forge.
6. **The engine readback.** After the pin-bump roll that the merge opened, an engine that reads
   the merged policy from its baked copy serves a value equal to the merged file.

### 8. Reserved: user repositories as a knowledge source

This is a non-goal of this ADR, recorded so that nothing here forecloses it. Repositories that
users own (not the mesh's own) could become a knowledge source the mesh retrieves from under the
same content-level gate as every other source. **engine-r's inbound mirror (§3) is reserved as
that fetch layer.** It is the subject of its own ADR later.

## Alternatives considered (rejected)

- **Stay on the forge, behind an adapter per forge.** The policies, reviews and audit would still
  live in each forge's layer. The adapter would chase forge APIs as fast as the forges change,
  which is the problem this ADR exists to stop.
- **A self-hosted forge as the record.** It is another forge, with the same life-cycle risk and
  its own policy model to rebuild the rules in.
- **Shelling out to the `git` binary.** A subprocess in the write path brings a second program's
  configuration, hooks and environment into every ref update. In-process libgit2 keeps one writer
  with one set of rules.
- **Policy in a database rather than git.** That gives up the stable data model, content
  addressing, diffs and the import and export story that motivate the ADR.
- **Extracting `policy/` and `sessions/` as their own repositories.** That rewrites their shas
  and orphans every packet's citation (ruled out 2026-10-28).
- **An audit store beside the repository.** It is a second store that would not travel with the
  mirror. A git note does (ruled out 2026-10-28).

## Open questions (named, not decided here)

The architect ruled on the draft's open questions and on four follow-ups on 2026-10-28. All the
rulings are folded in above. These remain open:

- **ADR-0061 is not on master.** §4 depends on it landing.
- **Cutover of the real repository** is its own decision, made after the slice has measured.
  Part of that decision: the forge remains the writer of application paths (§1) while engine-r
  writes the governed ones, and both live in one repository with one master. The slice avoids
  the question by mirroring to a separate repository. Cutover cannot avoid it.
- **Storage placement and backup** for the repositories' volume, given the single-node
  concentration of stateful volumes we already carry.

## Indicators for revisiting

- The write rate on one repository exceeds what a single writer serializes without queueing that
  lanes notice.
- A deployment requires a forge to remain the record, for compliance or contract.
- libgit2 lacks something a verb needs (a signature format, a merge strategy) and a shell-out
  becomes the only way.
- Application-source CI wants to move off the forge. That would be a separate ADR, but it would
  reopen §1's scope.
