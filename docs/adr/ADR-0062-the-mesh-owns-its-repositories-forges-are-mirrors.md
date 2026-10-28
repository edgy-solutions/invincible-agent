# ADR-0062 — The mesh owns its repositories; forges are mirrors

**Status:** Draft. It is open as a draft PR. §4 belongs to lane/74 and §5 to lane/gov, and both
are placeholders until their owners write them in this PR. Nothing is built.
**Date:** 2026-10-28
**Deciders:** architect (decision); Chris (review); Lane 1 (draft: §1–§3, §6, §7); lane/74 (§4);
lane/gov (§5)
**Related:**
  - [`ADR-0041`](ADR-0041-user-contributed-documents-ingest-on-arrival-provenance-gated-truth.md):
    the dropper rule. Whoever proposes a change may not approve it. Review in engine-r uses the
    same exclusion.
  - [`ADR-0042`](ADR-0042-live-view-artifacts-recomputing-cards-on-the-one-presentation-path.md):
    the directive cites "ADR-0042 C3/C4" for the customer-context check (§2). That citation
    does not resolve; see Open questions.
  - [`ADR-0054`](ADR-0054-data-classes-every-write-declares-what-it-is.md): data classes. §2
    declares engine-r's repository store in ADR-0054's four fields.
  - [`ADR-0057`](ADR-0057-the-model-is-edited-by-conversation-and-changed-by-review.md): a model
    change is ratified by review, and approval produces "a PR". Once engine-r holds `policy/`, that
    step becomes an engine-r proposal (§6).
  - ADR-0061 (a workflow is described in dialogue and compiled to rows). It is on
    `lane/74-socratic-workflow`, **not on master**. §4 is written against it.

## Context

A forge is a hosted git service with a review layer on top. In the deployments this platform
targets, forges are deployed, deprecated and replaced faster than anyone can support them.
Several products can be live at once, and their life spans are shorter than the data they hold.

Git's data model is stable. Objects, refs and history from ten years ago read the same today.
The forge's layer is not stable: branch protection, required reviewers, review threads, merge
policies, webhooks and audit logs. Each forge models these differently, and none of them export
cleanly. When a forge is retired, everything recorded in that layer leaves with it.

The mesh already governs its own changes in this layer, by convention:

- **A merge is gated, and it is by sha.** The merger merges the agreed sha and reads back the
  second parent.
- **A pushed release tag never moves.** A defect is a patch, and the release job is repaired only
  by a logged dispatch at the release sha (ruled 2026-10-25, #93).
- **Every commit carries its lane in a trailer** (R-058), and a pre-push hook refuses a commit
  without one.
- **No secrets and no infra detail in a commit.** This is enforced by a leak scan before every
  commit.
- **A proposer may not approve their own proposal** (ADR-0041, ADR-0057 §4).

Today these rules live in hooks, charters and habit. One forge enforces them, and that forge has
no knowledge of them. Moving forges would mean rebuilding every rule in the next forge's model.

**Decision drafted here:** the mesh holds its repositories of record itself. Any forge is a mirror
and a place where humans can interact. It is never the record.

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

- **Application source and its CI.** Both stay on the forge for now. Engine code, the chart and
  the build pipeline are not moved by this ADR.
- **Large binaries.** Images, model weights and captured fixtures above a size bound stay in
  their stores (registry, object store). A repository may reference them by digest; it does not
  hold them.
- **An agent-scale VCS.** Our write rate is hundreds of commits a day across all lanes. That
  rate is well within what git handles on a single writer, and nothing here is designed for a
  write rate orders of magnitude higher.

### 2. engine-r

engine-r is the mesh engine that holds repositories of record. ("engine-r" is the working name.
This ADR does not allocate it; see Open questions.)

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
  lane and no human pushes a ref directly.
- Ref updates for a repository run on one single-writer key per repository, as a Restate
  virtual object keyed by repository id. Two merges into one repository are serialized by
  construction, not by a lock someone has to remember.

**Verbs, in mesh terms.**

| verb | what it does |
| --- | --- |
| `propose` | Creates a proposal: a branch under `refs/proposals/<id>`, its commits and a stated intent. The proposal records its **head sha**. |
| `review` | Files an **approval task** for the proposal. The task carries the diff of the proposal head against the target ref. It is the same kind of task as ADR-0057 §4's ratification task, and it renders in cortex as a card. Who may review is §5's. |
| `merge` | Merges the proposal **by sha**. The merge names the head sha that was reviewed. If the proposal moved after review, the merge refuses. The result is a merge commit whose second parent is the reviewed sha (never a squash). A merge closes its proposal. |
| `tag` | Creates a tag at a named sha. A release tag is immutable (below). |
| `audit` | Reads the record of ref updates for a repository, path or proposal (below). |

**Commit identity.**

- Commits are **signed by the engine** on behalf of the caller's `authz_id`.
- The caller's identity, and how strongly it was established, travel in trailers:

  ```
  On-Behalf-Of: <authz_id>
  Provenance-Rung: <rung>
  Proposal: <proposal-id>
  ```

- The engine's signature attests that **the mesh** accepted the commit. The trailers say **for
  whom**, and how strongly the mesh knew who that was. Which ladder supplies `<rung>` is open.

**Pre-receive checks.**

Existing rules become checks that run inside `merge` and `tag`, before any ref moves. A refusal
carries the standard refusal envelope.

1. **A merge by sha closes its proposal.** The merge must name the reviewed head sha. A merged
   proposal cannot be merged again or reopened under the same id.
2. **A release tag never moves**, except by a logged repair. The repair is its own verb call with
   a reason, and it is recorded in the audit (#93's rule, moved from habit into the engine).
3. **No secrets.** The leak scan we run before commits today becomes a pre-receive check over
   the proposal's diff.
4. **No customer-identifying context.** The directive cites "ADR-0042 C3/C4" for this rule. The
   citation does not resolve on master (Open questions). The check is named here; its text is
   not.
5. **Every commit carries the §2 trailers.** This replaces R-058's lane trailer for repositories
   held in engine-r.

**Audit.** Every ref update writes one record:

- repository, ref, old sha, new sha;
- verb;
- `authz_id` and rung;
- proposal id and review task id;
- the check results;
- time.

The record lives with the engine, not on a forge. `audit` reads it back, by repository, by path
(through the commits that touched it) or by proposal.

### 3. Mirrors

**Outbound.**

- Each forge has one **push-mirror**, and the mirror is dumb.
- After every ref update, engine-r pushes the mirrored refs to the forge. The mirror carries no
  logic and no state of its own.
- On the forge, the mirror's identity is the only identity allowed to push. The forge's own merge
  path is disabled for mirrored repositories, so a forge-side merge cannot create a second
  history.

**Inbound.**

- The forge's PR and comment webhooks become **mesh tasks**.
- A forge PR becomes an engine-r proposal. engine-r fetches the PR's head into
  `refs/proposals/<id>`, quarantined from every ref the mesh reads.
- The proposal then goes through the same review and checks as any other.
- If it is approved, **engine-r merges** and the mirror pushes the result back. The forge sees its
  PR's head sha on the target branch.
- Forge comments attach to the review task as discussion. They are input to the task, not a
  record of the decision.

**Replacing a forge means re-pointing one mirror.** Nothing of record lives on the forge: no
policy, no review decision, no audit. A retired forge takes away its copy of the history and its
copy of the discussion. Both already exist in engine-r.

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
> The brief: who may propose, review, merge and tag, per repository and per path. This lives on
> the policy rail with grantors, and refusals carry the envelope. A second-approver rule applies
> to `policy/` and to release tags, "same shape as a4". (No rule labelled "a4" was found on
> master; see Open questions.)

### 6. Consequences and non-goals

**No forge UI is rebuilt.**

- cortex is the review surface: a proposal's review task is a card with its diff.
- File browsing, blame, history graphs and code search remain wherever a human already reads
  them, which is usually a mirror.

**CI for application code stays on the forge.** The build pipeline still runs from the forge
repository that holds the engines and the chart. Repositories in engine-r have no forge CI. Their
checks are §2's pre-receive checks.

**History already on GitHub is imported once, then mirrored.**

- The one-time import brings the full history into engine-r.
- From that moment on, engine-r is the record and GitHub is a mirror like any other.
- Whether the import keeps today's shas depends on the repository shape (Open questions). Packets
  cite master shas, so a rewrite would orphan those citations.

**ADR-0057 §4 changes for `policy/`.** Approval produces "a PR". Once engine-r holds `policy/`,
it produces an engine-r proposal, and the merge is engine-r's. The rule that a proposer may not
ratify their own proposal carries over unchanged.

**Backup becomes an obligation.** Authority here means the repositories' volume is the record.
A mirror holds the git objects, but not the audit records or the review tasks.

**Lanes change how they hand off.** If `sessions/` lives in engine-r, a lane places a packet by
`propose`, not by writing an untracked file into a shared tree.

**Non-goals:**

- application source;
- the CI pipeline;
- large binaries;
- an agent-scale VCS;
- a general-purpose code host for anyone other than the mesh.

### 7. First slice

`policy/` and `sessions/` of invincible-agent are the first repositories in engine-r on sandbox,
mirrored to GitHub. One real policy change goes **propose → review → merge → mirror**, end to
end. It is a change that was going to be made anyway, chosen when the slice runs.

The slice is complete when it has been measured, with the audit record shown. The slice report
must show:

1. **The repositories are imported, and the result is stated.** The report gives the import's
   commit count and head sha against GitHub's. If the import kept the shas, the heads are equal.
   If it did not, the report says so.
2. **The policy change.** The report shows:
   - the proposal id and its head sha;
   - the review task id, and who approved it;
   - the merge sha, whose second parent is the reviewed head;
   - the mirror's sha on GitHub after the push, which must equal engine-r's;
   - the wall-clock time of each leg.
3. **The audit record** for that merge, as `audit` returns it.
4. **Three refusals, each observed and each carrying the envelope:**
   - a direct push to the GitHub mirror is refused;
   - an approval by the proposer is refused;
   - a merge naming a sha other than the reviewed head is refused.
5. **The mirror is re-pointed.** A second mirror target is configured and receives the same
   refs, and nothing else changes. This is a sandbox stand-in for replacing a forge.

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

## Open questions (named, not decided here)

**Shape, storage and naming**

- **Repository shape.** One option extracts `policy/` and `sessions/` as their own repositories.
  That rewrites their shas and orphans every packet's sha citation. The other holds the whole
  invincible-agent repository and scopes verbs and §5's policy by path.
- **How a merge reaches a running engine.** Policy is baked into images at `/app/policy` and
  applied by a roll. The alternative is that engines read `policy/` from engine-r at runtime.
  What a merge triggers follows from that choice.
- **Storage placement and backup.** This covers where the repositories' volume lives, how it is
  backed up, and the single-node concentration of stateful volumes we already carry.
- **Component name.** This ADR does not allocate `engine-r`. The name has to be registered in
  each of the engine name registries, following `docs/runbooks/adding-an-engine.md`.

**Signing and identity**

- **Signing key custody and rotation.** This includes the signature format, and whether the
  mirrors display it as verified.
- **"Provenance rung".** No ladder of that name exists on master. The nearest is the trust
  table's `supervised` / `monitored` / `trusted` (README, ADR-0034), but that is a rung of
  autonomy, not of identity. Which ladder the trailer carries is open.
- **Forge identity to `authz_id`.** How an inbound forge account maps to a caller, and what
  happens to a PR from an account that maps to no one.

**Mirrors**

- **Which refs mirror.** One option is the target branches and tags only. The other also mirrors
  proposal refs, which makes in-flight work visible on the forge.
- **Inbound reachability.** Webhooks need the forge to reach the mesh. Polling the forge is the
  alternative.

**Citations that do not resolve on master**

- **"ADR-0042 C3/C4"** (§2, check 4). ADR-0042 has no C-numbered clauses. Its §3 and §4 cover
  measures as verbs and content against arrangement, not customer context. Which text the
  customer-context check enforces is open.
- **"The card standard"** (§2, `review`). No document of that name exists on master. The review
  card's shape is open.
- **"a4"** (§5). No rule of that label exists on master. This belongs to gov.
- **ADR-0061** (§4) is not on master. §4 depends on it landing.

**Lanes**

- **How lanes work on `sessions/` in engine-r.** Today a packet is an untracked file that the
  owning lane commits. In engine-r, a packet is a proposal, and the questions are who reviews it
  and whether it merges without review.

## Indicators for revisiting

- The write rate on one repository exceeds what a single writer serializes without queueing that
  lanes notice.
- A deployment requires a forge to remain the record, for compliance or contract.
- libgit2 lacks something a verb needs (a signature format, a merge strategy) and a shell-out
  becomes the only way.
- Application-source CI wants to move off the forge. That is a separate ADR, but it would reopen
  §1's scope.
