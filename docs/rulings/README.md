# Rulings register

**A `RULED` line cites an entry here, or it is not a ruling.** That rule has been in force in
the lane charter for some time and until 2026-09-11 it cited a file that did not exist —
`invincible-agent-5f` found it by searching with a positive control, and correctly refused a
dispatch item on the grounds that "per the ruling" named no register. Every ruling made in
conversation was unshipped until this file existed.

**What belongs here:** a decision that constrains future work and was not obvious from the code.
**What does not:** anything derivable from the repo, and anything still under discussion — a
proposal is not a ruling, and relaying one does not promote it.

**How to cite:** `RULED <date> — see [rulings#r-00N](../rulings/README.md#r-00n-slug)`, placed
**at the section it governs**, not collected at the top of a document. ADR-0047 established that
house style and ADR-0051 follows it.

**Status vocabulary.** `RULED` — decided, in force. `PROPOSED` — stated but not decided; must not
be implemented. `SUPERSEDED` — struck at its first hit with a pointer to what replaced it, never
deleted, because a stale statement left beside a live one reads as policy rather than history.

---

## R-001 — EAC: all three methods on one panel

**RULED 2026-09-09.** Source: architect, on `program_finance`'s `finEacCalculation` panel.

> *"my recommendation is all three methods on one panel; pinning hides the divergence that is
> the finding."*

EAC is spoken-mandatory **because** the three methods disagree materially — **$13.13M /
$14.15M / $14.79M against a $12.00M budget**, on the engine's own seed. A template that
silently picks one is **choosing the answer**, and the reader cannot tell a choice was made:
the panel renders, the number is real, and the divergence that IS the finding is invisible.

**Scope, so this does not over-reach:** it governs a **required slot whose value changes the
answer materially**. `plan_schedule`'s optional `scope_initiative_id` filters a portfolio-wide
answer and declaring it changes nothing about what the panel means; `portfolio.yaml` declaring
its verbs' own defaults remains correct. The discriminator is whether a reader shown the panel
would want to know a choice was made.

**Not yet satisfiable.** `fin_eac_calculation` takes `method: EACMethod` — one Literal — and
raises `MethodRequired` otherwise. One panel is one invocation is one method. **Honouring this
needs an engine change** (the verb returning all three rows, or a sibling comparison verb).
Until then `method: CPI` stands as a placeholder **and is explicitly NOT a considered choice**.
5f verified this at `5a9def7` and stopped rather than shipping a placeholder that reads as
settled — correct.

**Related:** this is the template-level form of three rules the repo already enforces — a
declared default that changes the card is a claim; an optimistic default is dishonest; a
plausible value where an absence belongs is worse than the absence.

---

## R-002 — `lens` on the template schema

**RULED 2026-09-11.** Source: architect, this thread. **Promoted from PROPOSED on this date** —
until this entry existed it was a relay, and 5f was right to refuse it.

`lens` is a field on the template schema. `program_finance` declares the **finance** lens.
**Absent means portfolio.**

**Consumers, and the ordering between them:**

* **cortex-ui** reads the lens **from the board record**, never inferred. Until this entry
  existed, cortex-60 was correct to leave it untouched.
* **The template schema change is an ADR-0050 amendment** and wants that amendment written, not
  a silent field addition.

**Blocked behind [R-005](#r-005-shared_slots-are-template-scoped).** `lens` lands with the
Phase 2 template work, which does not move until the seeder is scoped.

---

## R-003 — `template_id` is the field; `canvas_type` is read-only legacy

**RULED 2026-09-10.** Source: architect. **Shipped** — cortex-ui `6168a39`.

`template_id` is the field. `canvas_type` is honoured as read-only legacy **with a log line
naming field, value and replacement**, fired **only when the legacy value was actually
honoured** — when `template_id` is also present and wins, reporting that `canvas_type` "was
honoured" would report an honouring that did not happen.

**A silently-ignored field is indistinguishable from a field that still works**, which is why
the notice is part of the ruling rather than an implementation detail.

---

## R-004 — ADR-0051 sustainment safety: four rulings

**RULED 2026-09-10.** Source: architect. Recorded in place at the sections they govern
(ADR-0051 §5:290, §5:312, §3:242, §9:435), per ADR-0047's house style.

| # | ruling | where |
|---|---|---|
| a | **Author's visibility audience** — `risk_assessment_author:SUSTAINMENT`, view-only, granted at draft time. The existence-oracle protects against **outsiders, not authors**; that sentence is the rule it instantiates. | §5:290 |
| b | **`rejected` is reason-required too**, not only `accepted` — both verbs. Seal 6 mutates them **separately**, because one mutation covering both passes with one still wired. | §5:312 |
| c | **`trendMishaps` → slice 3.** | §3:242 |
| d | **SAFETY compartment deferred.** | §9:435 |

**§10.3 is struck through rather than deleted**, so a reader can tell *answered* from *never
asked*. Neither remaining §10 question blocks increments 0–4; **§10.2 gates a claim, not a
build**.

**These rulings must travel with the declaration, not with the code table.** `_VERBS_BY_KIND`
and cortex-ui's `taskKindRegistry` are **interim by construction and retire together**. The SDK
`TaskKind` row already carries `reason_required` as a field, validated as a subset of `accepts`
— so R-004b is a property **of the declaration** from the first schema, and the cutover seal
compares it row for row. Otherwise the bad half survives: a served declaration saying how a task
renders while a code table still decides what it can do.

---

## R-005 — `shared_slots` are template-scoped

**RULED 2026-09-11.** Source: architect, this thread. **Lane 1 owns the implementation.**

Declaring `program` globally regresses `portfolio` to 409, because the seeder demands a value
for **every declared slot**. The fix is **scope**:

* `shared_slots` are **template-scoped**.
* The seeder binds **only what the seeding template declares**.
* **`portfolio` declares none**, so it is unaffected.

**This is the critical path.** Nothing in Phase 2 moves until it lands, and Phase 2 gates slice 2
and every safety template. It is `gateway.py` — Lane 1's file.

**Prior refusals were correct and are now resolved by this entry.** 5f refused twice with code
evidence (`gateway.py:1949/1954` 409 on unbound shared slots, `:1963` 501 on anything but
`portfolio`) and named the ordering: (1) the seeder dispatches each panel's declared verb,
(2) something binds a shared slot into panels, (3) then declare. This ruling is (2).

---

## R-006 — Engine B retirement

**RULED 2026-09-06.** Source: ADR-0046 §8.4 / §8.5, route C.

Engine B (LangGraph support) is retired. Its waiver in `_NOT_A_REGISTERING_AGENT` now reads *by
design* rather than *by omission*: it registers nothing because there was nothing honest to
register, its intended use case's principal input being read by no node. **Still waived, for the
opposite reason**, until the chart block is removed and the key stops existing.

---

## R-007 — §9.2 — OPEN

**Not yet ruled.** The architect decides §9.2; **slice 1 closes on that decision**. Recorded here
as an open slot so that a `RULED` line citing it cannot be written before the decision exists.

---

## R-008 — Lane branches push on every commit; MERGING to master is the gated action

**RULED 2026-09-11.** Source: architect, this thread. Also stated in `AGENTS.md` beside the
worktree charter; **this entry is the citable form**, and the difference between the two is the
point of the entry.

    git push origin lane/<lane>      # after every commit. Always. Not a gated action.

**"Push only when asked" was written for one shared checkout on master**, where a push
published every lane's work at once. On a worktree, `git push origin lane/<x>` publishes **only
that lane's commits and merges nothing**. The reason for the permission is gone; the permission
outlived it. **Merging to master stays gated.**

**It has cost real time twice.** A worktree rebases onto ORIGIN, so a lane's local commits are
invisible to every other lane **by construction** — worse than the shared tree, where an
uncommitted file was at least readable. `tests/_mesh_verbs.py` sat committed-and-unpushed for
fifteen hours while the lane that asked for it waited. Seal 3's result then sat on an unpushed
branch under a phase gate reading *"do not start 1.1 until the run B result is written down"* —
**it WAS written down and nobody could read it.**

### Why this one needed a register entry more than any other ruling here

**A RELAYED PERMISSION-WIDENING MUST NEVER BE TAKEN ON A PEER'S WORD.** This ruling reached
invincible-agent-5f through Lane 1. They did not act on the relay. They verified the commit,
read the clause in `AGENTS.md`, adopted it because the licensed act is genuinely narrow — only
their own commits, merging nothing — **and disclosed it to their own user as reversible rather
than treating it as settled between peers.** That was correct, and it is the behaviour this
register has to make unnecessary rather than merely praise.

**The fix for a ruling a lane cannot trust is not to state it more loudly. It is for the ruling
to exist somewhere citable**, so a lane can check it instead of being told it. Note what "push
only when the user asks" is: an instruction each lane holds **from its own user**, not from this
repo. A rule written into a shared file by a peer — however well argued, however
architect-ruled — is exactly the shape that must not silently widen another agent's
permissions.

So: **this entry licenses nothing on its own.** It records what the architect decided, in a
place a lane can read and cite. A lane adopting it should do what 5f did — verify, adopt on its
own judgement, and disclose to its user — and the register exists so that the verifying step
has something to land on.

---

## R-010 — Canvas-template CI on `pull_request` is a blessed exemption

**RULED 2026-09-08.** Source: architect thread. Governs
[`.github/workflows/validate-canvas-templates.yml`](../../.github/workflows/validate-canvas-templates.yml);
the job and its reasoning are in [`canvas-templates-slice-1`](../plans/canvas-templates-slice-1.md).

**It overrides [`no-ci-gate-on-the-suite`](../plans/no-ci-gate-on-the-suite.md)**, which makes CI
jobs `workflow_dispatch`-only because a never-executed job wired to `push` burns minutes, goes red
for environment reasons, and trains people to ignore it. That reasoning is unchanged and still
governs everything else.

**Why this job is the exception:** ADR-0050 §1.3 requires an invalid template to fail **at merge**.
A `workflow_dispatch`-only job does not deliver merge-time failure, so shipping one and calling
§1.3 satisfied would be precisely the decorative seal ADR-0050 is written against — a check whose
green means only that nobody ran it.

**Why the convention's cost does not apply here:** the job is seconds of hermetic pure Python over
~200 lines of YAML — **no cluster, no database, no network**. The failure mode the convention
protects against (environment-caused reds that train people to ignore a gate) has no purchase on a
job with no environment.

**The demotion is pre-committed, not promised.** One environment-caused red and it goes to
`workflow_dispatch`. The standing rule loses to an argument only until it wins on evidence.

**Scope — this is an exemption, not a new convention.** It licenses this one job. A second
`pull_request` job cites its own argument or does not ship; "R-010 did it" is not that argument.
The discriminator is the pair: **a decision-bearing gate whose whole value is merge-time refusal,
AND a check with no environment to be flaky about.** A job missing either half is governed by
`no-ci-gate-on-the-suite` as before.

---

## R-011 — Task kinds: two after-cutover items on two lanes, and a row that was never created

**RULED 2026-09-11.** Source: architect, correcting their own M3.3 dispatch. Governs the
task-kind declaration layer ([`policy/task_kinds/`](../../policy/task_kinds/) and
[`adding-a-task-kind.md`](../runbooks/adding-a-task-kind.md)) and the register's lane assignment.

Recorded here rather than relayed, because the lane it was addressed to (`invincible-agent-01`)
had ended by the time the correction was ready to send. That is this file's own thesis arriving
on schedule: **a decision recorded in a conversation does not constrain anything — and a decision
addressed to a session address does not survive the session.**

**(a) The two after-cutover items belong to DIFFERENT lanes.** The dispatch put both on the
task-kinds lane.

| item | lane | why |
|---|---|---|
| the **groups ruling** — `grant_to` is users-only | whoever owns `task_grants.yaml` | a grant-rail decision, not a declaration one |
| the **`pcn_disposition` string rename** | the task-kinds lane | expand/contract with a dual-read interval |

The groups constraint is declared **verbatim in three namespaces** —
[`capability_grants.yaml`](../../policy/capability_grants.yaml),
[`ontology_compartments.yaml`](../../policy/ontology_compartments.yaml),
[`task_grants.yaml`](../../policy/task_grants.yaml) — each deferring group audiences for the same
reason; two state outright that `validate_policy` REFUSES a `grant_to` absent from `users.yaml`.
**ADR-0051 §5's one-audience-per-authority-level is the workaround that constraint forces**, not a
design preference. It was scheduled after the M3.3 cutover because the declaration is what groups
would attach to — a real dependency, which is what made the misattribution plausible.

The rename is the task-kinds lane's, because the kind string is simultaneously a live value in
`human_task_projection` rows and a UI render contract: it moves with a dual-read interval or it
strands rows. **It is deliberately NOT bundled into M3.3** — one migration at a time.

**(b) The overlay `pcn_disposition` row was never created HERE, by design — and the ruling is the
deliverable, not the row.** The dispatch listed the row as an artifact. It cannot exist in this
repo: `test_no_domain_name_entered_the_platform_seed` fails the build on a domain token in
`policy/task_kinds/`, which holds exactly four structural rows. What was delivered is the RULING
that the row lives work-side carrying its own `accepts`. The architect's framing: *a name for
something that cannot exist where it was put* — the same shape as the Engine S draft.

Record the ruling as delivered and the row as work-side, never created here. **A register carrying
a phantom deliverable is worse than one admitting a gap** — the same principle that had the
task-kind runbook's index row marked ROW ADDED rather than quietly filled.

**(c) Roster consequence, because this ruling was nearly lost to it.** `iagent-mesh-sdk-ca` is the
M3.3 / task-kinds lane, working in `iagent-mesh-sdk` **with commits in `invincible-agent`**. An
engine-repo search never finds it; `doc-tools-7f` and the cortex session are the same shape.
**The role-to-address map in `AGENTS.md` must carry the REPO beside the address** — and an address
alone is insufficient regardless, since session addresses churn hourly and `invincible-agent-01`
is already gone. A roster keyed only on them reproduces the failure it exists to prevent.

---

## Why this file exists at all

Two lanes independently refused work today on the grounds that a cited ruling could not be
found, and both were right. The failure was not that the rulings were wrong — they were the
architect's and they were sound — but that **a decision recorded in a conversation does not
constrain anything.** It cannot be cited, cannot be checked, and reaches a lane as a relay that
the lane is then obliged to treat as a proposal.

Same shape as the mirror script's false promise, the stale charter clause, and the ADR comment
that described a fix instead of making it: *a lesson written beside a list does not maintain the
list*, and a ruling written beside a conversation does not govern a repo.
