# ADR-0061 — A workflow is described in dialogue and compiled to the rows the case runner already runs

**Status:** Proposed, draft. Written before review. A prototype of the elicitation loop and three
synthetic fixtures are built and measured (§8). No route, no verb, no canvas.
**Date:** 2026-10-24
**Deciders:** architect (decision); Chris (review); lane/74 (draft)
**Related:**
  - [`ADR-0039`](ADR-0039-workflow-definition-authoring-schema-and-bpmn-export.md): workflow
    definitions. YAML is authoritative. Its amendment of 2026-09-12 puts choice in decision tables
    at trigger and at termination. It already names drawing as an *input method* that compiles
    through a strict front end and commits the YAML it produces. This ADR adds dialogue as a second
    input method under the same rule.
  - [`ADR-0057`](ADR-0057-the-model-is-edited-by-conversation-and-changed-by-review.md): the domain
    model is edited by conversation and changed by review. This ADR is the same decision, applied
    to workflows: socratic questions, deferral as a declared absence, the proposer excluded, a PR,
    then a roll.
  - [`ADR-0027`](ADR-0027-composable-approval-policy.md): composable approval policy. It governs
    the ratification task in §6.
  - [`ADR-0036`](ADR-0036-config-layering-seed-overlay-composition.md): seed + overlay composition
    by key. The compiled bundle is an overlay.
  - [`ADR-0050`](ADR-0050-canvas-templates-are-ratified-yaml-a-panel-is-a-pre-resolved-step.md):
    ratified YAML, changed by PR, applied by the roll.

**Numbering.** 0057 is the highest number on master at `7a45a3cb`. 0058 is on
`lane/74-adr-0058-draft`, and 0060 is on `lane/01-adr-0060`. The training lane has claimed 0059
in prose. 0061 is the next number free on every pushed branch on 2026-10-24.

---

## Context

A process owner can describe a PCN review, a maintenance release or a course approval in a few
sentences. Today, turning that into something the case runner runs means someone else writes four
kinds of YAML row by hand:
- a **trigger** (`policy/triggers/`);
- a **selection table** and one **chaining table** per definition (`policy/decisions/`);
- the **definitions** (`policy/workflows/`);
- the **task kinds** their approvals answer (`policy/task_kinds/`).

The rows are reviewable because they are not a program (ADR-0039). That property also makes them
unforgiving to write. A chaining table must be **total** over what its definition can emit,
`timed_out` included the moment any step declares a deadline. Every non-terminal target must be
a definition. Every definition must be followed by a table, because a case may end only at a
terminal a table declares. A `reason_required` verb must be one the kind accepts.

A process owner's description almost never states these things. It states the happy path.

## Decision

### 1. The spec is the overlay bundle. There is no other format.

The dialogue produces exactly the rows in the Context list. It produces them in an overlay
directory, composed by key with the seed as any overlay is (ADR-0036). It does not produce:
- an intermediate "workflow spec" that is later translated;
- a new step kind;
- a new table kind;
- a new runtime.

If the case runner's loaders accept the bundle, it is runnable. If they refuse it, it is not.

What the bundle cannot express is refused by name, never dropped. ADR-0039's import rule
applies verbatim: **refuse loudly, never ignore.** Examples:
- a branch inside a definition;
- a condition on something no engine measures;
- a join of parallel work that `dispatch_fanout` does not give.

The agent names the item back to the user, with the reason. If a choice needs computation, the
computation is a verb (ADR-0039, amendment); the dialogue does not invent one.

### 2. The dialogue elicits five facets, each landing in a named place

| facet | what the user says | where it lands |
|---|---|---|
| **trigger** | what starts it, what identifies one instance, what must be known at the start, what it branches on | trigger row (`key`, `episode`, `requires`); selection table |
| **actors** | who does each step, who may never do it | a step's `audience`, `role`, `excludes` |
| **steps** | the stages and their order | definitions, each linear (ADR-0039) |
| **approvals** | what an approver can answer, which answers need a reason, how long they have, what each answer leads to | task kind (`accepts`, `reason_required`); `deadline_seconds`; chaining table |
| **outputs** | what is recorded or sent, how the end is confirmed, where it ends | `emit` steps; the confirming `signal_await`; chaining `terminals` |

The user never sees a YAML word. The user is never asked for a value the system can derive.
Derived values include:
- a definition's `participants`, taken from its steps' roles;
- a task kind's rendering;
- placeholders, read from the event's declared fields.

### 3. Each turn: restate, then ask one question about a gap

After each utterance, the agent restates the whole draft in plain words. It then asks **one**
question. That question is about the highest-priority **gap**. A gap is one of two things.

**(a) Something the runtime or a seal would refuse.** These come from the case runner's own
loaders and from the seals that already run at merge. The dialogue adds no rules of its own here:
- the trigger, workflow and decision-table models;
- `decide()` over every point of a table's domain;
- `chain()`;
- totality and uniqueness;
- the chaining-table-bound-to-its-definition seal.

So an outcome with no row becomes a question: "when the engineering review ends `needs_info`,
what happens next?" The question is asked because the runtime would refuse the bundle without
the answer, and the question names that answer.

**(b) A small, fixed set of answers that ADR-0057 §2 would call questions.** The runtime has a
default for each of these, and the default is a decision nobody made:
- who is excluded from an approval (absent means nobody, which permits self-approval);
- each approval's deadline (absent means none);
- which answers need a reason;
- what the trigger requires;
- whether anything is recorded.

The agent never asks about something the draft already states. Order:
1. contradictions;
2. then missing items, by facet: trigger, actors, steps, approvals, outputs.

### 4. A contradiction is asked, never resolved by the last answer

There are two kinds:
- **Overwrite.** A later answer sets a value the draft already holds to something different. The
  earlier value stays. The agent quotes both and asks which holds.
- **Cross-check.** Two answers are each fine alone but refused together. For example, a chaining
  row for `deferred` when the reviewer was said to answer only approve, request changes or
  reject. The agent asks the question that settles it.

Last-write-wins is refused by name. It turns a misremembered sentence into a process change
that nobody reviewed.

### 5. A deferral is a declared absence, with its reason

As in ADR-0057 §2, a gap is closed by an answer or by an explicit deferral, and a deferral
records its reason. "I don't know yet" is a deferral; silence is not.

**A deferral travels with the proposal and is shown to the ratifier.** It matters because the
runtime reads some absences as answers: a deferred deadline runs as *no deadline*. The ratifier
must see that this was deferred, not decided.

**Two gaps may not be deferred:**
- **Who is excluded from an approval.** Absent means nobody, so a deferral here silently permits
  the requester to approve their own case. This is the same separation-of-duty floor as
  ADR-0057 §4's proposer exclusion. An explicit "nobody is excluded" is an answer, and it is
  ratifiable.
- **A gap the runtime refuses** (§3a). A deferral there leaves a bundle the runner will not load.
  It can be kept as a draft, but it cannot be filed.

### 6. The running process never changes from a conversation

Identical to ADR-0057 §4:
1. A completed proposal (no gaps, or only deferrable gaps deferred) files a **ratification task**
   to the owning domain's workflow stewards.
2. **The proposer may not ratify their own proposal.**
3. Approval produces a **PR** of the bundle under the deployment's overlay, with its deferrals.
   The seals that gate every hand-written row gate this one.
4. **The roll applies it.**

The conversation produces a proposal and nothing else. No conversation writes a row the runner
reads.

### 7. The model extracts; it does not decide

A model may turn an utterance into a patch: facts to set, and gaps to defer. Everything after
that is deterministic code:
- validation;
- gap finding;
- choosing the question;
- detecting contradictions;
- restating.

The model never chooses what to ask and never writes a row without the validator. A model
mistake therefore surfaces in one of three ways: as a question, as a contradiction, or as a wrong
value in the restatement the user reads every turn. It is never a silent row.

The prototype's model arm runs only against the fleet's pinned model on the LAN GPU host (ruled
2026-10-09). It is sent synthetic fixtures only.

### 8. Measured: the prototype against three synthetic fixtures

Fixtures: `tests/fixtures/socratic/` holds three synthetic workflows:
- a PCN review;
- a maintenance case release;
- a training-course approval.

Each has a transcript (an opening description, plus an answer bank keyed by gap), an expected
bundle, and its expected deferrals. Each fixture plants one contradiction and one deferral.

Prototype: `agent_fleet/restate_analyst/socratic_elicitation.py`. It is unregistered and has no
route. Seals: `tests/socratic/test_the_elicitation_loop_asks_only_what_is_missing.py`.

<!-- NUMBERS: filled from scripts/socratic_measure.py, oracle and model arms -->

## Consequences

- **The process owner describes. A steward reviews a diff.** The steward reviews the same rows a
  hand author would have written, gated by the same seals.
- **The dialogue's questions are the runtime's refusals, asked early.** A bundle that reaches the
  ratifier has already passed every check that would have refused it at merge.
- **The question list cannot drift from the runtime.** Every runtime refusal is derived from the
  runner's own models, so a new loader refusal becomes a new question with no dialogue change.
  The five completeness questions in §3(b) are the only hand-kept list.

Proposed units of work. This document assigns nobody:

| unit | likely home |
| --- | --- |
| a `proposeWorkflow` verb hosting the loop | the case runner's engine |
| the proposal rendered as a canvas: definitions, tables, deferrals | cortex-ui |
| the workflow stewards' ratification audience and route | shared with ADR-0057's |

## Alternatives considered (rejected)

- **The model writes the YAML directly.** A bundle that fails to load is discovered at merge, or
  at the roll. Worse, one that loads but encodes an answer nobody gave is never discovered.
- **A friendlier intermediate spec, translated to rows.** That is a second format with its own
  drift, and the translator becomes the runtime nobody reviews. ADR-0039 refused the same thing
  for BPMN import.
- **A questionnaire: every field asked in a fixed order.** It asks about what the user already
  said. The measure in §8 is questions asked against what was missing.

## Open questions (named, not decided here)

- **Where a deferral is stored once merged.** The workflow models forbid extra keys, so it
  cannot ride in the definition. The candidates are a sidecar row kind that no runtime reads, or
  the PR and the ratification record only.
- **Who the workflow stewards are, per deployment.** This may be the same audience as ADR-0057's.
- **Editing a ratified workflow by dialogue.** The prototype starts from an empty bundle. Starting
  from the composed rows is the same loop with a non-empty draft; it is not measured here.
- **Vocabulary.** The agent offers the event's declared fields and the deployment's declared
  audiences. A workflow that needs an audience nobody has declared is a grant change (a human's
  act), not a dialogue answer.

## Indicators for revisiting

- Users describe processes the bundle cannot express often enough that the refusals in §1 are
  the dialogue's main output.
- The extraction arm's error rate makes the restatement, not the question, the user's main work.
- A new step kind or table kind lands. Its refusals must become questions (§3a) before the
  dialogue offers it.
