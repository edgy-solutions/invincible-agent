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
  - [`ADR-0027`](ADR-0027-composable-approval-policy.md): composable approval. §5's second
    approver is an N-of-one-audience join. Decision 6 (an unsatisfiable join fails closed and is
    released) binds it. Where the join is decided is open (§5).
  - [`ADR-0041`](ADR-0041-user-contributed-documents-ingest-on-arrival-provenance-gated-truth.md):
    the dropper rule. Whoever proposes a change may not approve it. Review in engine-r uses the
    same exclusion. `sessions/` has one ruled exception (§2).
  - [`ADR-0054`](ADR-0054-data-classes-every-write-declares-what-it-is.md): data classes. §2
    declares engine-r's repository store in ADR-0054's four fields.
  - [`ADR-0057`](ADR-0057-the-model-is-edited-by-conversation-and-changed-by-review.md): a model
    change is ratified by review, and approval produces "a PR". In engine-r, that step becomes a
    proposal (§6).
  - ADR-0061 (a workflow is described in dialogue and compiled to rows). It is on
    `lane/74-socratic-workflow`, **not on master**. §4 is written against it at `3495ba5f`.

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

- Bare repositories live on cluster storage, on a PVC `engine-r-repos` (20Gi, Neo4j's storage
  class, on the node pool that holds the other stateful volumes; no new node). The volume is
  **not pinned** to a node.
- **Backup** is the mirror (§3) plus a nightly tar of the PVC to the object store.
- The **signing key** is ed25519. It is generated in-cluster into the Secret `engine-r-signing`,
  and its public half is committed at `docs/keys/engine-r.pub` so that mirrors verify.
- **Every key is generated in-cluster.** Its private half goes in a Secret and its public half in
  a ConfigMap `<secret>-pub`, so the public half can be read without reading the Secret. This
  covers engine-r's own keys, which today means the signing key. A forge credential is not a key
  (§3).
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
   - The terms come from `policy/leak_terms.yaml`. The committed seed holds the sandbox hostnames
     and the synthetic program names only.
   - A work deployment adds its own terms in an overlay that is never committed.
   - Check 4 **exempts exactly one path, `policy/leak_terms.yaml`** (ruled 2026-10-28), because
     an edit to it adds the terms themselves. An arm proves that a term in any other file is
     still refused. Edits to the exempt file take two approvers (§5).
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
- **A forge credential is an app installation, never a key** (ruled 2026-10-29). That rules out
  deploy keys, SSH keys and personal tokens. On GitHub the credential is a GitHub App:
  - it has Contents: write, and is installed on the mirror repository only;
  - its Secret holds `app.pem`, `app_id` and `installation_id`;
  - for each push, engine-r signs a JWT with the app key and exchanges it for an installation
    token that lasts at most an hour;
  - engine-r pushes over HTTPS as `x-access-token`.

  No long-lived push credential leaves the Secret. The ruling followed an org policy that
  disables deploy keys.

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

Written by lane/74, against ADR-0061 at `3495ba5f`. The architect accepted it on 2026-10-29 and
ruled the domain-steward carve-out, which is folded in below. ADR-0061 describes a workflow in dialogue
and compiles it to the rows the case runner already runs. This section says where those rows go
when the dialogue ends: **a Socratic workflow spec is a proposal in engine-r, its approval is the
review task, and the runnable spec is the merged file.**

**The loop ends in `propose`, not a file write.**

- Only a dialogue that ends `runnable` (ADR-0061 §5) proposes. One that ends `cannot_run` stays
  a draft in the dialogue's own state. It creates no proposal ref and files no task.
- The proposal's diff is the bundle and nothing else:
  - rows in the four row directories (`triggers/`, `decisions/`, `workflows/`, `task_kinds/`)
    under the deployment's overlay, `policy/overlays/<deployment>/`;
  - the bundle file, which declares the bundle's `domain:` and its deferrals (below).

  A dialogue never targets the seed directories (`policy/workflows/` and its siblings), and its
  proposal touches no path outside its overlay.
- The proposal's stated intent (§2) is the last restatement the person confirmed (ADR-0061 §3).
- ADR-0061 §6 changes. Its ratification task **is** the review task, and its "PR of the bundle"
  **is** the proposal. There is one task and one record, not a task followed by a PR.

**The proposer is the person who described the workflow.**

- The dialogue's host (ADR-0061's `proposeWorkflow`, in the case runner's engine) calls `propose`
  **with the person's identity**, forwarded as the fleet forwards it today. `On-Behalf-Of` names
  the person, and `Auth-Via` is how that person authenticated.
- **It never proposes under its own service identity.** §5 excludes the proposer from the review
  audience. With the host as proposer, the exclusion would remove a service identity, which can
  never approve anyway (§5), and leave the person who described the workflow free to approve it.
  ADR-0041's rule would hold on paper and fail in fact.
- **A dialogue has one describer.** The host refuses a turn from a second `authz_id`. §2's
  `propose` records one proposer, so a dialogue with several describers would need `propose` to
  carry an exclusion list. This section does not ask for that shape (Open questions).
- The forwarding is a new hop in the identity chain (`HOPS` in
  `tests/test_the_person_reaches_the_migrated_route.py`). The PR that builds it adds the hop.

**Who reviews.**

- **The domain-steward carve-out (ruled 2026-10-29).** A workflow bundle declares `domain:`. Its
  review audience is `repo_review:POLICY` **plus** that domain's steward group. There are two
  approvers, and neither is the proposer.
- **Why the bundle declares it.** ADR-0061 asks for "the owning domain's workflow stewards", but
  §5 matches rows by path. A workflow row carries no domain, and the overlay path names a
  deployment, not a domain. So the domain has to be declared in the bundle itself.
- **gov adds the row** to `policy/repository_paths.yaml`, keyed on overlay path and domain (§5).
  The row says how the two audiences combine within its two approvers: either audience may
  supply either approval, or one approval must come from each.
- **The domain is a required slot** (ADR-0061 §3c). Without it, a bundle cannot select its row,
  so the dialogue cannot end `runnable`. The prototype has no such slot yet (`3495ba5f`).

**What the card shows.**

- The review card is cortex's review card spec (§2), showing the diff.
- A workflow proposal adds one requirement: **deferrals are rows on the card, not only lines in
  the diff.** ADR-0061 §5 requires the ratifier to see what was deferred rather than decided,
  because the runtime reads some absences as answers: a deferred deadline runs as no deadline.

**The bundle file: its domain and its deferrals.** This answers ADR-0061's open question on
where a deferral is stored once merged.

- Each bundle carries one file, `policy/overlays/<deployment>/bundles/<trigger key>.yaml`. It holds
  two things:
  - `domain:`, which selects the review row (above);
  - `deferrals:`, which maps each gap key to its reason, in the shape of the prototype fixtures'
    `expected/deferrals.yaml`.

  No runtime reads it.
- It merges in the same proposal as the rows. The domain and the deferrals therefore outlive the
  review task and mirror with the rows (§3).
- Answering a deferral later is a new proposal that changes the row and removes the line.
- **Not measured.** The prototype keeps deferrals in the dialogue's state and writes no file. The
  fixtures' `deferrals.yaml` is the measurement's expected value, not the prototype's output. The
  building PR owes an arm proving the case runner's loaders ignore a `bundles/` directory in an
  overlay.

**The checks at merge include the runner's loaders.**

- `runnable` at the end of the dialogue is not enough, for two reasons:
  - the prototype's `runnable()` loads the bundle **alone**, as its own seed in a temporary
    directory (`socratic_elicitation.py` at `3495ba5f`), never composed with the deployment's seed
    and its other overlays;
  - the target ref can move between the end of the dialogue and the merge.
- So any proposal that touches a row directory runs the case runner's own loaders (triggers,
  decision tables, workflow definitions, task kinds) **over the composed policy at the merge
  result**, as a pre-receive check. A loader refusal carries the envelope and moves no ref.
- The same check refuses a bundle file whose `domain:` is absent or is not a domain in
  `policy/domains.yaml`. Without a domain, there is no row to select.
- §5's `validate_policy` check does not stand in for this one. At `c346e782`,
  `policy/sync/validate_policy.py` loads none of the four row kinds.
- As with §5's check, §4 names this one, and adding it to §2's list is §2's job.

**A change after review comes back through the dialogue.**

- A reviewer who wants a change says so on the task. The person reopens the dialogue, and its
  next `runnable` end pushes a new head to the **same** proposal.
- The head moves, so every pending approval is void (§5, rule 5). Review starts again at the new
  head.
- A refusal on the review task closes the proposal. The draft stays in the dialogue's state.

**Merged is not running.**

- The runnable spec is the merged file, but the merge does not run it.
- A merge to `policy/` opens a pin-bump proposal (§6). The workflow runs from the engine's baked
  copy after that roll. Runtime reads from engine-r are a follow-on ADR (§6).
- The person is told the difference. A merge sha says what was approved. The workflow runs from
  the first roll whose build contains that sha.

**What the dialogue never bundles.** A workflow that needs an audience nobody has declared needs
a grant change, which is a human's act (ADR-0061, Open questions). The dialogue does not answer
it, and a workflow proposal never carries a `policy/task_grants.yaml` row. The audience is its
own proposal, merged and applied first.

### 5. Merge policy

Written by lane/gov. §2 says what the verbs do; this section says **who**.

**One rail says who: `policy/repository_paths.yaml`.**

- It is a rail like the others in `policy/`: a reviewed file, plus a grantor row at
  `policy/grantors/repository_paths.yaml` (family `repository_paths`, not object-scoped).
- It is not a grant path, so it **applies by roll** (§6). engine-r reads its baked copy.
- A change to the rail therefore governs the proposals that come after its roll. It never
  governs the proposal that makes it.

```yaml
repository_paths:
  invincible-agent:                      # repository id, as engine-r keys it (§2)
    paths:
      policy/:                           # a path prefix; the longest matching prefix wins
        review: repo_review:POLICY       # a task audience in policy/task_grants.yaml
        approvers: 2
        granted_by: <who ratified the row>
        reason: <why>
      sessions/:
        review: owning_lane              # the one value that is not an audience (below)
        approvers: 1
    tags:
      invincible-agent-*:                # a tag-name pattern
        review: repo_release:invincible-agent
        approvers: 2
```

**How a path is matched.**

- **Longest prefix wins.** A path takes the row with the longest matching prefix.
- **A path that matches no row is not governed.** That is §2's check 6, and this rail is the one
  place check 6 reads.
- **The rail cannot widen check 6.** `validate_policy` refuses a row outside §1's governed roots
  (`policy/`, `docs/adr/`, `tests/fixtures/`, `sessions/`). Only the follow-on ADR (§1) can let
  engine-r merge application source.
- **Several rows means all of them.** A proposal whose diff touches several rows needs every row
  satisfied. One approver counts toward each row whose audience they hold.

**What `review` means.** `review` names a task audience in `policy/task_grants.yaml`, and to
approve you must hold `can_act` on it. That is the same Topaz permission the HITL queue already
decides on, so there is no second decider. An audience's `grant_to` holds users only, and its
groups' members are users, so **a service identity never approves**. Agents propose; a person
approves.

**Who, per verb.**

| verb | who | how it is decided |
| --- | --- | --- |
| `propose` | any caller whose `authz_id` is in `policy/users.yaml`, service identities included | Proposing grants nothing and moves no target ref. An unmapped forge account parks at `awaiting_identity` (§3). |
| `review` | a holder of `can_act` on each touched row's audience, **never the proposer** | The proposal's review task excludes the proposer from its audience, which is ADR-0057 §4's form of ADR-0041's dropper rule. |
| `merge` | **nobody holds a merge grant** | engine-r merges when every touched row's approvals are complete **at the reviewed head sha** and the pre-receive checks pass. Any party to the proposal may ask for the merge; asking decides nothing. `On-Behalf-Of` is the approver whose approval completed it, and the audit note names every approver. |
| `tag` | a holder of `can_act` on the tag row's audience | A tag is proposed as a (name, sha) pair, and engine-r creates it once the approvals are complete. A release-tag repair (§2 check 2) takes the same approvals plus its reason. A tag that matches no row is refused. |

**The first rows (repository `invincible-agent`).** The new audiences (`repo_review:*` and
`repo_release:*`) are rows in `policy/task_grants.yaml`. The first-slice PR adds them; this ADR
does not.

| path or tag | review audience | approvers |
| --- | --- | --- |
| `policy/` (overlays included) | `repo_review:POLICY` | **2** |
| `policy/asset_grants.yaml` | `access_grant:<DOMAIN>`, taken from each row the diff changes; a changed row with no domain, or whose domain has no such audience, goes to `repo_review:POLICY` (ratified 2026-10-29) | **2** (the slice's access request uses `program_members.yaml` instead, so this row's count is not exercised by §7) |
| `policy/program_members.yaml` | `repo_review:POLICY` (the family has no audience of its own yet) | **1**: one Grant (ruled 2026-10-28) |
| `policy/groups.yaml` | `repo_review:POLICY` (the family has no audience of its own yet) | **2** |
| `policy/repository_paths.yaml`, `policy/task_grants.yaml`, `policy/grantors/` | `repo_review:POLICY` | **2** |
| `policy/leak_terms.yaml` | `repo_review:POLICY` | **2**; exempt from check 4 (§2, ruled 2026-10-28) |
| a workflow bundle (§4): its bundle file `policy/overlays/<deployment>/bundles/<trigger key>.yaml` and the rows it carries under that deployment's `triggers/`, `decisions/`, `workflows/` and `task_kinds/` | `repo_review:POLICY` **and** `workflow_steward:<DOMAIN>`, the domain read from the bundle file's `domain:` (the domain-steward carve-out, ruled 2026-10-29; below) | **2**: one from each audience |
| `docs/adr/` | `repo_review:ADR` | 1 |
| `tests/fixtures/` (no goldens directory exists at `93ea39af`) | `repo_review:FIXTURES` | 1 |
| `sessions/` | the owning lane (below) | 0 when the exception applies, otherwise 1 |
| release tags `invincible-agent-*` | `repo_release:invincible-agent` | **2** |

**The workflow-bundle row: §4's domain-steward carve-out (ruled 2026-10-29).**

- **What selects the row.** A proposal that adds or modifies a bundle file. The row covers that
  file and every path the proposal touches under the **same deployment's** four row directories.
  `<DOMAIN>` is the bundle file's `domain:` at the proposal head.
  - This is the one row that is not matched by path prefix or tag pattern alone: the bundle file
    in the diff selects it, and its `domain:` selects the audience.
  - It is more specific than `policy/`, so it wins for the paths it covers. Every other path in the
    proposal still takes its own row ("several rows means all of them").
  - An edit under the row directories with **no** bundle file in the proposal takes the `policy/`
    row. So do the seed directories, such as `policy/workflows/`: a dialogue never targets them
    (§4).
- **How the two audiences combine: one approval from each.**
  - The steward's approval is the reason the carve-out exists. ADR-0061 asks for "the owning
    domain's workflow stewards". If either audience could supply either approval, two
    `repo_review:POLICY` approvals would merge a domain's workflow with no steward, and the
    carve-out would change nothing.
  - The policy reviewers' approval stays because a bundle's rows are policy rows: triggers,
    decisions and task kinds.
  - **The two approvers are distinct** (rules 2 and 6). A person in both audiences supplies one of
    the two, never both.
  - **Rule 7 per audience.** If either audience, less the proposer and the pending approver, is
    empty, the proposal closes with that reason.
- **The steward audience is `workflow_steward:<DOMAIN>`**, a task audience in
  `policy/task_grants.yaml`.
  - None exists yet. Who stewards a domain's workflows is each deployment's grant.
  - A bundle whose domain has no such audience can never complete. It closes under rule 7 and
    names the missing audience. There is no fallback, because the domain is a required slot (§4)
    and a fallback would drop the steward.
  - The row lands in `policy/repository_paths.yaml` in the PR that adds the first steward
    audience. Rule 8 already refuses a `<DOMAIN>` template that resolves to no audience.

**The second approver: saf's rule, in the same shape.** saf built it for the delete of a
safety-critical part in #114 (`409b5344`) and #115 (`a7f5995c`). Its arms are in
`tests/test_a_delete_of_a_safety_critical_part_needs_a_second_approver.py`, and engine-r keeps
each one:

1. **The first approval is recorded as pending, with its `authz_id`, on the review task's
   record.** Nothing merges
   (`test_the_first_approval_records_pending_with_the_authz_id_and_deletes_nothing`).
2. **The same `authz_id` again is 409 `same_actor`.** Nothing merges
   (`test_the_same_authz_id_again_is_409_same_actor_and_deletes_nothing`).
3. **A different `authz_id` in the audience completes it, once**
   (`test_a_different_authz_id_completes_the_delete_once`).
4. **A pending approval lasts seven days**
   (`test_a_pending_inside_seven_days_still_completes`). An approval after that is a fresh first
   approval, not a completion
   (`test_an_action_after_seven_days_is_a_fresh_first_approval_not_a_completion`).

engine-r adds what a part delete does not need:

5. **Both approvals are of one head sha.** A proposal that moves voids its pending approval,
   because the merge names the reviewed sha (§2).
6. **Neither approver is the proposer.**
7. **An approval that can never complete fails closed and is released** (ADR-0027 Decision 6).
   If the audience, less the proposer and the pending approver, is empty, the proposal closes with
   that reason. It does not park.
8. **`validate_policy` refuses a row whose audience has fewer distinct users than `approvers`.**
   Groups are expanded one level, as the queue expands them. Rule 7 is then a runtime event (a
   member left, or the proposer is a member), never a configuration.
   - Two audiences are held to one more user than any row naming them requires: `repo_review:POLICY`
     and `repo_release:invincible-agent` (ruled 2026-10-29). So a two-approver `policy/` change, or
     a release tag, still has two eligible approvers after the proposer is excluded. In the sandbox
     both audiences hold alice, bob and carol.
   - A `<DOMAIN>` template is checked for every audience it can resolve to, and for its fallback.

§5 fixes the **observable** rule, which is these arms. It does not fix where completeness is
decided. ADR-0027 Decision 4 makes that a Topaz evaluation, but saf's rule decides in the engine.
See Open questions.

**`sessions/`: which lane owns which path.**

- **A file's owner is the lane its `from:` line names**, read as an address:
  - `<repo>/<branch>`, or a seat `<repo>/seat/<name>`;
  - the legacy `ia-<worktree>/lane/<branch>` is read but never written (ruled 2026-10-07).

  For a new file this is the `from:` line at the proposal head. For an existing file it is the
  line at the target head.
- **A file whose `from:` line does not parse has no owner and never takes the exception.** It
  goes to review. An unparseable line fails toward review, never toward a silent pass. At
  `93ea39af`, 359 `sessions/*.md` files break down as:

  | `from:` line | files |
  | --- | --- |
  | `<repo>/<lane-or-seat>/<name>` | 143 |
  | legacy form | 95 |
  | no `from:` line | 47 |
  | something else (prose, a session name, a repository with no lane) | 74 |

  So an edit to any of those last 121 files goes to review.
- **The exception (§2) applies only when all of these hold:**
  - every path in the diff is under `sessions/`;
  - every file is added or modified, with no deletion and no rename;
  - every file has the same owner, and that lane is **bound to the proposer** (below);
  - no existing file's `from:` line changes.
- **A new file whose `from:` names a lane not bound to the proposer is refused.** A packet does
  not speak for another lane.
- **Every other `sessions/` proposal** goes to one approver: a principal bound to the owning lane,
  or `repo_review:SESSIONS` when there is no owner.
- **Checks 3–5 run on every packet**, with or without the exception.
- **The binding is a rail, `policy/lanes.yaml`.** It maps an address to the `authz_id`s that may
  propose as that lane. It is a `policy/` path, so it takes two approvers. **No lane holds the
  exception until it is bound.** Today every lane commits as one identity, so a binding needs a
  principal per lane first. See Open questions.

**Application source: what a merge requires.** Nothing, because engine-r merges none of it (§1,
check 6). No forge CI result is an input to any engine-r merge.

For governed paths the inputs are the approvals above and §2's pre-receive checks. One gap
follows from this:

- Today a path-filtered forge workflow validates `policy/canvases/**`.
- No forge workflow runs `validate_policy` at all (checked at `93ea39af`).
- Once engine-r is the writer, a mirror's CI runs **after** the merge, too late to gate it.

So **`validate_policy` and the canvas-template check run as a pre-receive check on any proposal
touching `policy/`, at its head.** §5 names that check; adding it to §2's list is §2's job.

**Refusals carry the envelope.** These are new refusal sites, so each is classified in the PR
that builds it (ruled 2026-10-27). The family column is §5's proposal for that classification. It
is not the classification itself.

| site | status | proposed family | missing binding |
| --- | --- | --- | --- |
| review by a caller without `can_act` | 403 | `task_grants` | `can_act(task_audience:<aud>)` |
| review by the proposer | 403 | `code` (no grant changes it) | the dropper rule |
| the same approver again | 409 `same_actor` | `code` | the second-approver rule |
| a path or tag that matches no row (check 6) | 403 | `repository_paths` | a row covering the path |
| a new packet whose `from:` names a lane not bound to the proposer | 403 | `lanes` | a binding in `policy/lanes.yaml` |

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

The mirror is `edgy-solutions/invincible-agent-mirror`, a private repository that Chris creates
empty. engine-r pushes to it as the GitHub App `engine-r-mirror`, which is installed on that
repository only (§3). The app's credential is in the Secret `engine-r-mirror`. Its value is never
read into a transcript. A check of the Secret uses `kubectl describe` or `-o name`, never a
formatter.

engine-r is its own Deployment, so rolling it never rolls the fleet. It has **its own chart and
release** (ruled 2026-10-28). Two pieces of its registration live in the fleet: its Keycloak
client (`templates/secrets.yaml`), and the `repo_review:*` and `repo_release:*` audiences in
`policy/task_grants.yaml`. Those edits ride the **next planned fleet release** and never get a
roll of their own. A new audience still goes merge, then the Topaz sync, then the roll.

The slice's real policy change is an **access request** for one row of
`policy/program_members.yaml` (one Grant). The names are synthetic (ruled 2026-10-28):

- `repo_review:POLICY` holds **alice** and **bob**.
- **bob** requests program **`NP-MERIDIAN`**, and **alice** grants it. The review audience
  excludes the proposer (§5), so alice is the only possible grantor.

End to end:

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
6. **The engine readback.** The grant applies by sync and opens no roll (§6). So the slice adds
   **one non-grant `policy/` change** through engine-r and rolls **the one engine that reads it**
   (ruled 2026-10-28). After that roll, the engine serves a value equal to the merged file, read
   from its baked copy. The roll touches only that engine, never the fleet.

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

On 2026-10-28 the architect ruled on the draft's open questions, then on the four questions those
rulings raised. All the rulings are folded in above. These remain open:

- **ADR-0061 is not on master.** §4 depends on it landing.
- **A deployment whose overlay is held in another repository.**
  - engine-r holds the invincible-agent repository (§1). Under this ADR, a deployment whose
    overlay lives elsewhere has no engine-r target for its dialogue's proposal.
  - Check 4 meets the same question. A deployment's own terms are in its uncommitted leak-terms
    overlay (§2), and its own workflows name its own systems and audiences. (§4)
- **Several describers.** §2's `propose` records one proposer, so §4 allows one describer per
  dialogue. A shared description needs `propose` to carry every describer as excluded. (§4)
- **A second author on an open proposal.** §2 does not say whether a caller other than the
  proposer can add a commit to `refs/proposals/<id>`. If one can, §5 must say whether that
  caller is excluded from review. §4 routes every change through the dialogue, so workflows do
  not raise the question, but nothing in §2 stops a hand commit. (§4)
- **Cutover of the real repository** is its own decision, made after the slice has measured.
  Part of that decision: the forge remains the writer of application paths (§1) while engine-r
  writes the governed ones, and both live in one repository with one master. The slice avoids
  the question by mirroring to a separate repository. Cutover cannot avoid it.
- **Ruled 2026-10-28, folded in above:**
  - storage and backup (§2);
  - the signing key (§2);
  - the mirror repository (§7);
  - the forge credential: an app installation, never a key (§3, §7; ruled 2026-10-29, replacing
    the deploy key that an org policy disables);
  - one Grant: the slice's change is one `program_members.yaml` row, with one approver (§5, §7);
  - check 4's term list (§2);
  - check 4's exemption for `policy/leak_terms.yaml`, with two approvers (§2, §5);
  - engine-r's own chart and release, with its fleet registration riding the next planned fleet
    release (§7);
  - measurement 6: one non-grant `policy/` change and a roll of the one engine that reads it (§7);
  - the slice's names: `repo_review:POLICY` holds alice and bob, and bob requests `NP-MERIDIAN`
    while alice grants it (§7);
  - keys are generated in-cluster, with their public halves in ConfigMaps, and the volume is not
    pinned (§2).
- **Raised by those rulings (Lane 1, 2026-10-28): the walk's program name and check 4's seed.**
  - B6's seed holds "the synthetic program names", and `NP-MERIDIAN` is a synthetic program name.
    If the seed lists it, check 4 refuses the slice's own grant: bob's proposal adds a
    `program_members.yaml` line naming `NP-MERIDIAN`.
  - Proposed: the seed's synthetic names are **decoys**, used only by check 4's refusal arm. A
    name a grant may carry, `NP-MERIDIAN` included, is never in the seed. An arm proves bob's
    proposal clears check 4.
- **Where the second-approver join is decided.**
  - ADR-0027 Decision 4 makes "are all required approvals present" a Topaz evaluation, and
    rejects an engine that tracks partial state and decides completion.
  - saf's rule (#114, #115) decides in the engine.

  §5 fixes the observable rule and leaves where it is decided open. ADR-0027's composable layer
  is unbuilt. (§5)
- **A principal per lane.**
  - The `sessions/` exception binds a lane to the `authz_id`s that may propose as it
    (`policy/lanes.yaml`).
  - Today every lane commits as one identity, so no binding distinguishes one lane from another.
  - Until each lane has its own principal, no lane holds the exception, and every packet goes to
    review. (§5)

## Indicators for revisiting

- The write rate on one repository exceeds what a single writer serializes without queueing that
  lanes notice.
- A deployment requires a forge to remain the record, for compliance or contract.
- libgit2 lacks something a verb needs (a signature format, a merge strategy) and a shell-out
  becomes the only way.
- Application-source CI wants to move off the forge. That would be a separate ADR, but it would
  reopen §1's scope.
