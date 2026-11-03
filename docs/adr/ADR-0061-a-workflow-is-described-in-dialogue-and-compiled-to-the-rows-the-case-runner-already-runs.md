# ADR-0061 — A workflow is described in dialogue and compiled to the rows the case runner already runs

**Status:** Proposed, ruled 2026-11-02: this ADR records the design and its measurements, including
the gap below. **The bar for "the loop works" is not met.** It is met when a run is runnable with all
four stages reachable and each stage has the steps the person described (ruled 2026-11-02).
`runnable` now refuses any definition no table routes to from the trigger. Runs 38 to 40 are all
runnable with all four stages reachable, and none has every step: all three lost the impact review's
`render` step, and two lost the record's filing step (§10).
Runs 32 and 33 met the 10-30 gate in its words with stages unreachable (§10). Under that refusal they
are `cannot_run`. A prototype of the elicitation loop and three synthetic fixtures are built and
measured (§8). No route, no verb, no canvas.
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

**(c) Required slots, asked by name** (ruled 2026-10-25, widened 10-27 and 10-30). These slots
are asked of every definition in the draft, whether or not a selection table reaches it yet:
- the task kind of each approval step;
- who is barred from answering each approval step (`excludes`, §10);
- the trigger's stages: every stage a case can pass through, in the person's order (10-30, §10);
- each declared stage that is not drafted yet (10-30, §10);
- the routing table after each stage that can end;
- the values of every routing table whose `after` names a drafted stage, whether or not that
  stage can end yet: each input it matches with no domain (10-30, §10);
- that table's rows: each declared value no row decides (10-30, §10).

The model omitted these more often than anything else (§8). A slot asked by name ("Required: the
task kind for the approval ...") is asked before the stage is wired in, not after.

**Confirmed once** (the turn check, ruled 2026-10-30, §10). A required slot the draft already
holds a value for is asked once more, to confirm, when no turn asked about it: its value was set
in a turn that asked something else, or in the opening. The slots checked are the trigger's
stages, each approval step's task kind, each approval step's `excludes`, and each complete
routing table. An unanswered confirm is left open; it may not be deferred.

The agent never asks about something the draft already states, except a confirm. Order:
1. contradictions;
2. then missing items, by facet: trigger, actors, steps, approvals, outputs;
3. then confirms, by facet.

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

A required slot (§3c) may not be deferred either.

**Enforced in the prototype** (ruled 2026-10-25). An unanswered non-deferrable gap is left open,
never recorded as deferred. That holds for a model's `defer` as well. The loop asks everything
else first, re-asks each open gap once, then stops. It ends in one of two states:
- `runnable`: no gap left, nothing open, and the runner's loaders accept the bundle;
- `cannot_run`, with the list of what is missing.

There is no "done".

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

Instrument: `scripts/socratic_measure.py`. A scripted user answers each question from the
transcript's bank. Two arms:
- **Oracle:** the extractor returns each utterance's pre-written facts.
- **Model:** the pinned fleet model (ruling of 10-09) extracts. It sees each utterance's words and
  the context's event fields and audiences, never the facts or `expected/`.

Correctness is measured two ways:
- **exact:** the final bundle equals the expected one;
- **semantic:** the diff after renaming definitions by the order a case reaches them (`wf0`, `wf1`,
  ...), ignoring names and free text.

`runnable()` loads the final bundle through the real `load_triggers`, `load_tables`,
`load_all_workflows`, task-kind `compose`, `chaining_index` and `decide`. Three of its checks restate
a rule instead of calling the runner's code:
- every definition has a table `after:` it;
- every task kind a step names is declared;
- every attribute a row matches is measured or required.

**Oracle arm.** All three fixtures came out exact, with no runnable errors and in about 0.1 s each:

| fixture | questions / bank | repeated | unanswerable | contradictions | deferrals | gaps left |
| --- | --- | --- | --- | --- | --- | --- |
| PCN review | 12 / 12 | 0 | 0 | 1 / 1 | 1 / 1 | 0 |
| maintenance case release | 9 / 9 | 0 | 0 | 1 / 1 | 1 / 1 | 0 |
| training-course approval | 10 / 10 | 0 | 0 | 1 / 1 | 1 / 1 | 0 |

The oracle's correctness is close to built-in: its facts carry ids the user never says. What it
does measure:
- the loop asks every banked question exactly once and nothing else;
- it raises each planted contradiction and records each planted deferral;
- the expected bundles pass the runner's own loaders.

**Model arm, three runs.** In run 1 the user looked answers up by the exact gap key. In runs 2 and
3 the user aligned the model's names to the expected ones by structure, never by string similarity:
- a definition by the selection or chaining row with the same `when` that reaches it;
- a step by its position among steps of the same kind;
- a task kind by the step that names it.

Through that aligner, the oracle gives the identical table; a test asserts this.

| run | fixture | questions / bank | unanswerable | contradictions | deferrals | runnable errors | semantic diffs | deferred refusals | seconds |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | PCN | 7 / 12 | 6 | 0 / 1 | 0 / 1 | 2 | 9 | n/m | 205 |
| 1 | maintenance | 5 / 9 | 5 | 0 / 1 | 0 / 1 | 3 | 6 | n/m | 126 |
| 1 | training | 8 / 10 | 8 | 0 / 1 | 0 / 1 | 4 | 9 | n/m | 144 |
| 2 | PCN | 7 / 12 | 6 | 0 / 1 | 0 / 1 | 2 | 9 | 4 | 171 |
| 2 | maintenance | 4 / 9 | 4 | 0 / 1 | 0 / 1 | 3 | 6 | 2 | 137 |
| 2 | training | 10 / 10 | 6 | 0 / 1 | 0 / 1 | 3 | 8 | 3 | 548 |
| 3 | PCN | 10 / 12 | 6 | 0 / 1 | 0 / 1 | 4 | 7 | 5 | 490 |
| 3 | maintenance | 3 / 9 | 3 | 0 / 1 | 0 / 1 | 3 | 6 | 2 | 96 |
| 3 | training | 9 / 10 | 4 | 0 / 1 | 0 / 1 | 1 | 8 | 1 | 570 |

Notes on the table:
- "n/m" means not measured: the metric was added after run 1.
- No run had a model or transport error, a repeated question, or an exact result.

What the model runs show:

1. **The loop closed on a spec that cannot run, every time.** Every model run ended with no gaps
   left and 1 to 4 runnable errors. In runs 2 and 3, each runnable error is a runtime refusal that went unanswered
   and was then recorded as deferred (the "deferred refusals" column), or it follows from one. §5
   says a runtime refusal may not be deferred, and the prototype does not yet enforce that.

   Example, maintenance in run 3:
   - The trigger names a workflow where a selection table belongs.
   - "Which table routes this trigger" was unanswerable, so it was deferred.
   - With no selection table, no definition is reachable, so the case checks went quiet. The loop
     stopped after 3 questions.

   Enforcing §5 is the first build item: an open refusal ends the dialogue as **not runnable**,
   never as done.
2. **Two extraction defects repeat across runs.** In the six aligned runs:
   - an approval step named no task kind in 5;
   - a definition had no chaining table in 4;
   - the model also emitted a task kind without `accepts` once.

   These are errors in the rows themselves, not naming differences.
3. **No model run reached a planted contradiction or deferral** (0 of 9 each). Both sit after
   stages the model's draft left unrouted, or after the loop had already closed.
4. **The PCN fixture has a defect, in the fixture rather than the model.** The opening says "a fit,
   form or function change". The expected selection row matches `change_class: fff`, and that value
   appears nowhere the model can see. Run 3 split it into three rows (`fit`, `form`, `function`), a
   reasonable reading. The aligner then could not pair the impact review, so its 2 questions were
   unaligned. The fix is for the context to carry each event field's value vocabulary (see Open
   questions).
5. **The scripted user is limited.** The bank holds only the questions the oracle's path raises.
   "Unbanked" questions in the model runs are of two kinds:
   - questions the opening already answered, which are model misses. The maintenance and training
     openings state `requires`, yet `trigger.requires` was asked in run 2 on both fixtures and in
     run 3 on training.
   - questions off the oracle's path that a person could answer.

   The instrument cannot tell these apart automatically, so the unanswerable count is an upper
   bound on what a person would leave unanswered.

**Seals and mutants:**
- `tests/socratic` collects 37 tests.
- With the three shipped decision-table seals and the ADR index: 155 passed.
- Across the repo-wide source-walking seals: 179 passed, 6 skipped.

Both runs were on the committed tree.

The positive control: the shipped seed bundle validates with each sample overlay and with both. That
required scoping case checks to definitions reachable from a selection table. The seed's
code-opened workflows are not cases. That scoping is a reading of `chain()`'s population. The
architect approved it on 2026-10-25 (§9, ruling 2).

Mutants, run in memory:

| mutant | result |
| --- | --- |
| a chaining table loses a declared row | 1 error, from the real `decide()` |
| a human_await loses its audience | 10 errors, from the real `WorkflowDefinition` |
| a chaining table removed | 1 error, from the restated check |
| a good bundle run after a bad one | 0 errors: no stale loader state |
| last write wins | planted contradictions asked 0 / 1. The maintenance bundle still came out exact, because the kept value was the expected one; only the question count shows the loss there |
| completeness questions removed | 8, 8 and 9 questions. Training and maintenance still came out exact, so only the missing deferral records show the loss |
| aligner pairs definitions by file order instead of by path | a draft missing a stage answers that stage's question as a different stage's, where the real aligner leaves it unaligned; a seal pins both |

**Caveats:**
- The seals ran with SDK v0.9.10 (master's pin) on the path, because the lane venv carries 0.9.5.
- Three model runs of a non-deterministic model is a sample: the per-fixture numbers moved between
  runs by up to 3 questions and 3 runnable errors.
- The fixtures are synthetic and were written by the same lane as the prototype.

### 9. Rulings of 2026-10-25, and three more model runs

The architect ruled on §8:
1. **A refusal is never deferred.** The loop keeps asking, or stops with "cannot run, missing X",
   never "done". Built: §5.
2. **Case checks bind only definitions reachable from a selection table.** Approved.
3. **Fix the PCN fixture's `fff`, which the model never sees.** The seal over the class found two
   more kinds of value the model could not see, on all three fixtures:
   - answer labels the transcript only paraphrased, such as "send it back for rework" for
     `rework`, and `needs_info`, `passed` and `changes_requested`;
   - `timed_out`, the runner's outcome when a deadline expires, which no user coins.

   The widening to the whole class was approved after the fact. What changed:
   - each fixture's context carries its event fields' values, and the model sees them;
   - each answer that defines an answer list speaks its labels;
   - the extractor's grammar states `timed_out`.

   The seal is `test_every_when_value_is_visible_to_the_model`, with three positive controls:
   - PCN without its event values;
   - the grammar without `timed_out`;
   - PCN without its answer-label sentence.
4. **The approval task kind and the post-stage routing table are required slots,** asked by name.
   Built: §3(c).

By the same ruling, this ADR stays a draft until the model arm produces one runnable spec. If it
produces none, the most common missing field becomes the next build item, not another three runs.

**Oracle arm, after the rulings.** Unchanged:
- 12, 9 and 10 questions;
- exact on all three fixtures;
- status `runnable`, both plain and through the aligning user.

**Model arm, runs 4 to 6**, on `73759832`, with the same aligning user:

| run | fixture | questions / bank | repeated | unanswerable | runnable errors | semantic diffs | deferred refusals | status | missing | seconds |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 4 | PCN | 10 / 12 | 2 | 8 | 0 | 6 | 0 | cannot_run | 2 | 149 |
| 4 | maintenance | 5 / 9 | 1 | 5 | 1 | 6 | 0 | cannot_run | 2 | 74 |
| 4 | training | 8 / 10 | 1 | 5 | 2 | 7 | 0 | cannot_run | 3 | 203 |
| 5 | PCN | 8 / 12 | 2 | 6 | 0 | 6 | 0 | cannot_run | 2 | 125 |
| 5 | maintenance | 12 / 9 | 3 | 10 | 3 | 6 | 0 | cannot_run | 6 | 137 |
| 5 | training | 13 / 10 | 4 | 10 | 0 | 9 | 0 | cannot_run | 4 | 167 |
| 6 | PCN | 10 / 12 | 2 | 8 | 1 | 6 | 0 | cannot_run | 3 | 124 |
| 6 | maintenance | 5 / 9 | 2 | 3 | 5 | 6 | 0 | cannot_run | 7 | 455 |
| 6 | training | 5 / 10 | 2 | 5 | 0 | 8 | 0 | cannot_run | 2 | 181 |

Notes on the table:
- **Runnable:** none of the nine.
- **Exact:** 0 of 9.
- **Planted contradictions or deferrals reached:** 0 of 9.
- **Repeats:** every repeat is the designed re-ask of an open gap. On every row, "repeated" equals
  the number of open gaps.
- **Deferred refusals:** 0 on every row; §5 holds. In runs 1 to 3, refusals were deferred and the loop
  closed with no gaps left.
- **Timeouts:** run 6 had three model-call timeouts.
  - Two were on maintenance.
  - One was on training's opening. That draft stayed empty, so run 6 training measures the
    transport, not the model.

**What was missing.** The census counts everything missing from each final draft:
- the open gaps;
- the gaps left;
- the `runnable()` errors, recomputed from the saved draft.

Items are grouped by shape, with names replaced. The count is the number of the nine
fixture-runs in which a class appears:

| class | fixture-runs |
| --- | --- |
| who is barred from an approval (`actors.<wf>.<step>.excludes`), left open | 5, holding 10 keys |
| a table matches an attribute no trigger requires and the runner does not measure | 3 |
| a chaining table does not route `timed_out` | 3 |
| a table's `after:` names no definition | 2 |
| a definition has no table `after:` it | 2 |
| two tables declare the same `after:` | 2 |
| nine other classes | 1 each |

Run 6 training's empty draft is left out of the count.

In runs 4 and 5 on PCN, the two `excludes` slots were the only items missing, with no runnable
error. Whether answering them would have opened further gaps was not measured.

**The most common missing field is who is barred from an approval.** In all 10 keys, the
transcript states the answer: "including whoever logged the notice", "nobody is barred", "who is
not the author". Two causes, five keys each:
- **The model was given the statement and did not set the field.** This happened on the PCN impact
  review in all three runs, from the opening. It also happened in run 5 on training's content review
  (from the opening) and on its training-manager stage, whose step question was answered from the
  bank.
- **The statement never reached the model.** The model built the stage from a passing mention in the
  opening, so the step's own answer, which says who is barred, was never asked for. The `excludes`
  question that followed has no bank entry, because the oracle takes that fact from the step's
  answer. This happened on the PCN acknowledgement in all three runs, and on training's security
  review in runs 4 and 5.

  A person would answer that question. The scripted user cannot.

That is the next build item, and it has the same two halves. (a) is an instrument defect; without
it, the model half cannot be measured:
- (a) the scripted user answers a question from the bank entry whose facts set the path asked
  about, which is structural like the rest of the aligner;
- (b) the extractor's grammar makes `excludes` required on every approval step, with `[]` when the
  user says anyone or nobody.

Two smaller findings:
- The `timed_out` class persists in 3 fixture-runs despite the grammar line.
- The class "a table matches an unrequired attribute" is new in these runs.

**Seals on `73759832`**, with SDK v0.9.10 on the path:
- `tests/socratic` collects 55 tests.
- With the three shipped decision-table seals and the ADR index: 173 passed.
- Across the repo-wide source-walking seals: 179 passed, 6 skipped.

Mutants, applied on disk and restored with `cmp`:

| mutant | named red |
| --- | --- |
| non-deferrable gaps deferred as before | T1 and T3 |
| required slots restricted to reachable definitions | T6 only |
| `_status` ignores runnable errors | T5 only |

### 10. The go of 2026-10-27: `excludes` built, and three runs on PCN

The order: "fix the scripted user so the statement reaches the model, then make `excludes`
required on every approval step, then three runs on the PCN fixture only (the one where excludes
was the sole gap). Report runnable or the next most-common field."

**Built on `c61f6868`:**
- **(a) The scripted user answers by path.** When a translated question has no bank key, it is
  answered by the entry whose facts set the path asked about. Three key shapes have a path: who is
  barred, a deadline, and a task kind's `reason_required`. A fact on the same file at another path
  does not count. The opening is a candidate first, then the bank in order; a `contradiction:`
  entry never answers a plain question. So the person repeats what they said first, and the planted
  `excludes` contradiction stays reachable. These answers are counted apart, as `answered_by_path`.
- **(b) `excludes` is a required slot** on every approval step, reachable or not. An explicit `[]`
  is set. The grammar states it as REQUIRED.
- `--fixture` runs named fixtures only.

**The oracle is unchanged:** 12, 9 and 10 questions, exact, `runnable`, plain and aligned. It
answers nothing by path.

**Model, runs 7 to 9, PCN only:**

| run | questions / bank | runnable errors | semantic diffs | open | answered by path | status | seconds |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 7 | 7/12 | 0 | 6 | 0 | 1 | **runnable** | 180 |
| 8 | 14/12 | 6 | 6 | 5 | 0 | cannot_run | 92 |
| 9 | 6/12 | 2 | 7 | 2 | 0 | cannot_run | 128 |

There were no model-call errors and no transport errors. Run 7's status was recomputed from its
saved bundle: `runnable()` returns no errors, and no gap is open or left.

**`excludes` is gone from the census.** It is missing in none of the three runs. Before, it was
missing in 5 of 9 fixture-runs and in every PCN run. Run 7's one answer by path is the
acknowledgement's deadline, from `steps.pcn_acknowledge` ("there is no time limit").

#### Run 7 is runnable, and it is not the workflow the transcript describes

| | expected | run 7 |
| --- | --- | --- |
| trigger and its `requires` | `pcn_received` | the same, under another name |
| selection table | `fff` to impact review, `minor` to acknowledgement | the same |
| definitions | four: impact review, acknowledgement, program approval, record | two: impact review, acknowledgement |
| impact review's answers | approved, rejected, needs_info; two need a reason | `disposition` |
| acknowledgement's answers | acknowledged, escalated; escalating needs a reason | `acknowledged`; no reason |
| routing after the two stages | five rows: escalation back to impact review, approval on to program approval | two rows, each to a terminal it named |
| who is barred from the impact review | the submitter (the planted contradiction) | nobody |

Three causes, each read from the saved run:
1. **A required slot was satisfied by what the model wrote itself.** The opening says the engineer
   "gives a disposition". The model wrote a task kind accepting `disposition`, and a routing table
   sending it to a terminal it named. Both slots were set, so neither was asked. Those two bank
   answers carry the three answer labels and the program-approval stage. Then the record stage, and
   the "barred from both reviews" statement, are reached only through program approval. None of the
   seven questions asked was a task kind or a routing table.
2. **An unanswered contradiction was deferred, and the earlier value stood.** The acknowledgement's
   deadline was answered by path from `steps.pcn_acknowledge`. That entry also says "acknowledge
   it, or escalate it, and escalating needs a reason". The model's patch changed the task kind it
   had already written. The loop asked the three contradictions that raised: the answers,
   the reasons, and the routing table's outcome values. The scripted user had no bank key for
   them; the path fallback covers plain questions only. For the two task-kind contradictions, the
   entry that sets the path is the entry that raised them. Unanswered, each was deferred as "user
   could not answer". The final bundle has neither `escalated` nor its reason, so the earlier
   value stood and the user's later statement was dropped. (The turn log is not saved; that is
   read from the deferrals and the final bundle.) An overwrite contradiction is not in §5's
   non-deferrable set.
3. **`outputs.record` was deferred unanswered.** No bank key matches it, here or in runs 4 to 6;
   the oracle never asks it.

So `runnable` is a property of the bundle against the loaders. It does not say the bundle is what
the person said. The ruling's condition is "one runnable spec". **This ADR is left a draft**, for
the architect to decide whether run 7 meets it; if it does, the status moves to proposed with
these numbers.

One measurement defect: run 7 recorded the planted deferral, under the model's key, which
translates to the planted one. The report's column reads 0/1 because it compares keys without
translating them.

#### The next most common item

Grouped by name, no class in runs 8 and 9 appears in more than one run. Grouped by facet, two
appear in all three runs:

| item | runs | keys |
| --- | --- | --- |
| a contradiction the scripted user could not answer | 3 of 3 | 6: three deferred in run 7, two open in run 8, one open in run 9 |
| an `outputs` question with no bank key (`record`, `end`, `<stage>.ends`) | 3 of 3 | 4 |

Contradictions lead by keys, and they are cause 2 of run 7. They have two halves, like `excludes`:
- (a) the instrument: the scripted user answers a contradiction by path too. That is measured for
  the two in run 7, and not checked for the other four;
- (b) the subject: may an overwrite contradiction be deferred? While it may be, a later statement
  can be dropped and the bundle still reads `runnable`.

Cause 1 is not a count. A required slot set from a passing mention looks exactly like one the
person spelled out, and no check here tells them apart.

**Seals on `c61f6868`**, with SDK v0.9.10 on the path:
- `tests/socratic`: 59 passed.
- With the three decision-table seals and the ADR index: 177 passed.
- Across the repo-wide source-walking seals: 179 passed, 6 skipped.

Mutants, applied on disk and restored with `cmp`:

| mutant | named red |
| --- | --- |
| the path fallback removed | the end-to-end delivery seal |
| a path matched by file alone | the entry-that-sets-the-path seal (program approval) |
| the bank tried before the opening | the entry-that-sets-the-path seal (impact review) |
| the `excludes` slot removed | T6 |
| an explicit `[]` read as unset | the explicit-empty seal |

#### 2026-10-30: runs 7 to 9 were taken before the example files were fixed

The standing rule of 2026-10-30 says config names the case. The model's system prompt broke it.
- **What was wrong.** The prompt shows the model one chaining table and one task kind, as format
  only. The extractor named both by file: `safety_acceptance_chaining.yaml` and
  `risk_acceptance_low.yaml` in the `sample` overlay. They were read from the repo checkout, so a
  deployment could not show its own rows without a code change.
- **What runs 7 to 9 measured.** They ran with those two files as the examples. Their numbers stand
  as a measurement of that prompt. They are not a measurement of the prompt the code builds now.
- **Fixed.** `served_examples()` takes the examples from the policy the runtime composes.
  - The decision tables come through `load_tables`, so `DECISION_TABLE_DIR` applies.
  - The task kinds come from the seed beside them plus `TASK_KIND_OVERLAY_DIRS`.
  - The first by sorted name is chosen, so the prompt is stable for a given policy.
  - With this tree's policy and neither variable set, the examples are
    `maint_fault_escalate_chaining` and `access_request`.
  - A policy with no chaining table or no task kind is refused. The prompt is never built
    without examples.
- **Fixture list.** The test and `scripts/socratic_measure.py` used to name the three fixtures in
  code. They now derive the list from `tests/fixtures/socratic/*/transcript.yaml`, and the test
  refuses an empty bank.
- **Seals:**
  - `tests/socratic` gives 62 passed.
  - Three seals are new:
    - a deployment's own table and kind become the examples;
    - no example is a refusal;
    - the extractor names no overlay file.
  - Run against the unfixed module (restored by copy and `cmp`), all three are red.
- **Runs 7 to 9 again, on PCN, against this prompt** (architect, 10-30). They ran as runs 10 to 12
  on 2026-10-30, with no walk or roll in flight. Same model, same fixture, same harness as runs 7
  to 9. The only change was the example files.

| run | questions / bank | runnable errors | semantic diffs | open | answered by path | status | seconds |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 10 | 8/12 | 2 | 6 | 3 | 0 | cannot_run | 106 |
| 11 | 8/12 | 2 | 6 | 3 | 0 | cannot_run | 116 |
| 12 | — | — | — | — | — | **crashed** | 160 |
| 12 again | 14/12 | 3 | 6 | 4 | 1 | cannot_run | 137 |

- **Runs 10 and 11 fail the same way.** Both runnable errors are the two chaining tables.
  - Run 10: neither table declares a domain for `outcome`.
  - Run 11: neither table has a row for the outcome its step ends on (`acknowledged`, `approved`).
  - In both runs, the two chaining contradictions are left `open`, along with one outputs key.
  - The semantic diffs are identical in the two runs: the chain and steps of the first two
    workflows, and the whole of the other two.
- **Run 12 never finished.**
  - The model patched `steps[0].deadline_seconds`, a positional list index.
  - The path grammar takes only a key or a `name[key=value]` selector, so `parse_path` raised
    `PatchError`.
  - `run()` has no handler for that error, so it ended the whole run, not the turn.
  - This is a defect in the loop, not in the prompt fix. The same code ran under runs 7 to 9; the
    model just did not emit a positional path there.
- **Before and after.** Before the fix: 1 runnable out of 3, and run 7 was runnable with half the
  workflow missing. After the fix: 0 runnable out of 2 completed runs, plus the crash.
  - Two runs are too few to call the new prompt better or worse.
  - The new prompt does give a steadier failure: runs 10 and 11 agree on every count, while runs 7
    to 9 ranged from 0 to 6 runnable errors and from 0 to 5 open items.
  - In all five runs the planted contradiction went undetected (0 of 1) and the planted deferral
    went unrecorded (0 of 1).
- **Ruled (architect, 10-30): an unparseable path is a model error charged to that turn.** The
  loop records it, asks the model to restate, and continues. A run never crashes on model output.
  - `_apply_or_charge` tries each turn's patch on a copy of the draft.
  - A `PatchError` is recorded as `{turn, error}` in the run's `model_errors`.
  - The model is asked again `PATCH_RESTATES` (1) times, with the refusal in a `REFUSED` section.
  - A patch that is still refused moves the turn on, and nothing of it lands in the draft.
  - `socratic_measure` adds the refusals to `model_errors` and lists them as `refused_patches`.
  - Two new seals: a restatement lands, and a stubborn patch lands nothing while the run goes on.
    Against the unfixed loop, both are red with run 12's `PatchError`.
- **Run 12 again, at the fix.**
  - `cannot_run`: 3 runnable errors, all three of them tables that declare no domain for an input.
    The two chaining tables have no domain for `outcome`; the selection table has none for
    `change_class`.
  - 4 open: the two chaining contradictions, `trigger.routing` and `outputs.end`.
  - The semantic diffs are the same six as runs 10 and 11.
  - It asked 14 questions. 4 keys were asked more than once, and 11 questions were unanswerable.
  - The model made no unparseable patch this time: 0 refused patches, 0 model errors. So this run
    does not exercise the new arm; the seals do. Whether a live model's refused patch is restated
    usefully is still unmeasured.
- **After the fix, 0 of 3 runs are runnable.** All three fail on chaining tables with no domain or
  row for `outcome`. The planted contradiction and the planted deferral were missed in every run.

#### 2026-10-30: a chaining table's values and rows are required slots; runs 13 to 15

Ruling (architect, 10-30): the model never supplies a chaining table's allowed values or an outcome
row, so these are required slots that the loop asks for by name. The planted contradiction and the
planted deferral are a separate build item, and come after this one.

- **Built** (`dcbffff4`). `required_slots` asks two things of the routing table after each
  definition, reachable or not:
  - **values:** `<facet>.<wid>.next.domain.<input>` for each input in the table's `matches` with no
    domain. The input is `outcome` when the table declares no `matches`.
  - **rows:** `<facet>.<wid>.next.<value>` for each combination of declared values that no row
    decides.
- **How "no row" is decided.** The slot fires only when the runner's own `decide` refuses the value
  and one more row for exactly that value would make it choose. Two matching rows, or a row with
  no `then`, stay a contradiction.
- **The vague question is dropped while a slot covers it.** The whole-table contradiction is not
  asked while a slot names what is missing.
- **Like the other required slots,** these may not be deferred. The grammar's REQUIRED list states
  them too.
- **The scripted user** answers a chaining slot from the bank entry that sets that path in the
  expected table. It finds the table by its `after`, not by file name.
- **Seals:**
  - six new; `tests/socratic` gives 70 passed;
  - against the unfixed code, the four slot seals are red and the two controls green;
  - the two-rows control is red against the rejected rule (every refusal by `decide` is a missing
    row).

Three runs on PCN at `dcbffff4`, same model and harness as runs 10 to 12, with no walk or roll in
flight:

| run | questions / bank | runnable errors | semantic diffs | open | answered by path | model errors | status | seconds |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 13 | 4/12 | 0 | 5 | 0 | 0 | 0 | **runnable** | 169 |
| 14 | 5/12 | 1 | 6 | 0 | 1 | 1 | cannot_run | 179 |
| 15 | 4/12 | 2 | 7 | 1 | 0 | 0 | cannot_run | 129 |

- **The chaining errors are gone in 2 of 3 runs, and none of the new slots was ever asked.**
  - Runs 10 to 12: every chaining table had either no values or no rows.
  - Runs 13 and 14: every chaining table has `matches`, a domain and rows.
  - Run 15: the impact review's table is complete. The acknowledge table is empty: no `matches`, no
    domain, no rows.
  - No chaining slot key appears in any run's question list. Two things changed at `dcbffff4`: the
    slots, and a REQUIRED line in the grammar. These runs can only credit the line. The slots
    themselves are measured only by the seals.
- **Run 15 shows a hole in the slots.** The acknowledge stage has no disposing step, so `_emits`
  finds no last step, and `required_slots` binds no chaining slot to a stage that cannot end. The
  loop asked `outputs.acknowledge.ends` twice instead. The scripted user had no answer for it, so it
  was left open. The table's values and rows were never asked about.
  - Owed: bind the value and row slots to every table with an `after`, whether or not the stage
    before it can end yet. Not done here, because the ruling asked for three runs at this build.
- **Run 13 is runnable, and it is not the workflow described**, like run 7 (§10). Of the four
  stages, the program approval and the record were never drafted. Runs 10 to 15 all drafted the
  same two of the four. The model never drafted the stages after `impact_review` and `acknowledge`.
  That is now the largest semantic diff, and nothing asks for it: in each run the routing names a
  terminal where the transcript names a further stage.
- **Run 14 refused a selection table.** The model gave it an `after:` that names no definition, so
  the runner's loader refused it. This is a new refusal class in these runs.
- **The restate arm ran live once,** in run 14. At turn 3 the model sent the positional path
  `steps[0].deadline_seconds`. The refusal was charged to that turn, and the restated patch was applied: 1 refused patch,
  no second refusal. 1 of 1 restated.
- **The planted contradiction and deferral** were missed again in all three runs. That is the
  separate build item.

#### 2026-10-30: the trigger declares its stages, and the chaining slots bind to the table; runs 16 to 18

Ruling (architect, 10-30), in order:
1. bind the chaining slots to every routing table that names an earlier stage;
2. have the trigger declare its stages, and have the loop ask for each stage not yet drafted;
3. then the contradiction and the deferral.

Three runs after (1) and (2).

- **Built** (`63148f22`).
  - **(1)** The value and row slots bind to every table whose `after` names a drafted definition,
    whether or not that stage has a disposing step yet. Run 15's acknowledge table is now asked its
    values.
  - **(2)** The trigger carries `stages`: the definition ids a case can pass through, in the
    person's order.
    - A trigger with no `stages` is a required slot, `trigger.stages`.
    - Each declared stage with no definition is a required slot, `steps.<stage>`.
    - The grammar's REQUIRED list states both.
  - **`stages` is draft-only.** The runner's `Trigger` refuses an unknown field, so `finalize` drops
    `stages` from the served bundle, and `problems` validates the trigger without it. Carrying
    `stages` into the served bundle would be a runner change. That is not ruled here.
- **The scripted user.**
  - Each fixture transcript answers `trigger.stages` with the expected definition ids. The expected
    bundles are unchanged.
  - The scripted user pairs a draft stage with an expected one by position in the two `stages`
    lists. It does this only when the lists are the same length, and never over a pairing the
    selection-table walk already made. This lets it answer about a stage that no routing row names
    yet.
- **Seals:**
  - five new; `tests/socratic` gives 75 passed;
  - against the unfixed module, the four slot seals are red, and so are t6 and the three t7 counts
    (which now include `trigger.stages`);
  - the `stages`-dropped seal has a control: the runner's `Trigger` refuses `stages`;
  - with positional pairing switched off, the pairing seal and the aligned-oracle seal are red.

Three runs on PCN at `63148f22`, same model and harness, with no walk or roll in flight. The bank is
now 13: it includes the stages answer.

| run | questions / bank | runnable errors | semantic diffs | open | answered by path | model errors | status | seconds |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 16 | 18/13 | 0 | 5 | 2 | 7 | 0 | cannot_run | 429 |
| 17 | 9/13 | 0 | 6 | 0 | 1 | 0 | **runnable** | 267 |
| 18 | 32/13 | 4 | 8 | 10 | 13 | 1 | cannot_run | 661 |

**Run 17 is the first real one** (architect, 10-30): runnable, with all four stages drafted. Run 7
was runnable with half the workflow missing; runs 8 to 15 never drafted more than two stages. Run
17 still carries 6 semantic diffs against the expected bundle, and it asked no chaining slot.

- **The stages gap is closed in 2 of 3 runs.**
  - Runs 16 and 17 asked `trigger.stages` first. Both then asked `steps.<stage>` for the program
    approval and the record, and drafted all four stages. Runs 10 to 15 never drafted more than two.
  - Run 18 stated `stages` without being asked. It drafted three of the four stages, plus a
    `needs_information_wait` stage that the transcript does not describe. The record was never
    drafted. The loop raised a contradiction on the trigger's `stages`. The scripted user could not
    answer it, and it was deferred. The scripted user also could not answer `outputs.record`.
- **Chaining slots were asked live for the first time,** in runs 16 and 18:
  - run 16: `approvals.impact_review.next.{approved,rejected,needs_info}`,
    `approvals.acknowledge.next.acknowledged` and `approvals.program_approval.next.timed_out`;
  - run 18: also the values slots, `approvals.{impact_review,acknowledge}.next.domain.outcome`.
  - Run 17 asked none. The model wrote every table whole, unasked, as in runs 13 and 14.
- **Run 16: no runnable errors, and 3 of 4 chains match the expected chains.** Its status is
  `cannot_run` because two contradictions the loop raised are still open:
  - the routing after the impact review decides `needs_info`;
  - the routing after the acknowledgement decides `escalated`;
  - neither is an answer that stage's task kind accepts.
  The scripted user has no bank entry for a contradiction the loop raises about the model's own
  draft. Each was asked twice and left open.
- **Run 18 shows a new class: an outcome put in `terminals` instead of given a row.**
  - Each chaining table lists the outcome that ends the case (`rejected`, `acknowledged`,
    `approved`, `elapsed`) in `terminals`, with no row for it.
  - In the runner, a terminal is a state a row's `then` names, not an outcome. So `decide` still
    has no row for it. The 4 runnable errors are all of this kind.
  - The row slot was asked for each of these outcomes. Every answer put the value into `terminals`
    again, so the slot never closed and was asked again. Of the 32 questions, 22 are distinct;
    the other 10 are repeats.
  - Owed:
    - the grammar should say that a terminal is a `then` target, and that an outcome which ends the
      case still needs a row naming the terminal;
    - a slot asked twice with no change in the draft is a stall the loop could report instead of
      asking it a third time.
  - Neither is built here. Both wait for the ruling on order.
  - *Correction (10-30):* there is no third time. The loop already stops at two asks and leaves
    the key open. What was owed is a signal, not a cap: the second ask, when its answer changed
    nothing, is reported as stalled rather than as unresolved. Built in the turn-check subsection
    below.
- **The restate arm.** Run 18 sent the positional path `steps[0].deadline_seconds` again, at turn
  18. It was refused once, with no second refusal.
- **The planted deferral was recorded live in all three runs, and the counter reads 0 of 1.**
  - Each run deferred the impact review's deadline with the planted reason, "We have not agreed a
    turnaround for the engineering disposition yet."
  - It was recorded under the draft's own step names (`step1`, `impact_review`,
    `impact_review_step`). The counter is an exact match on the expected key,
    `approvals.pcn_impact_review.engineering_disposition.deadline`.
  - The planted contradiction was detected in none of the three runs.
  - Both belong to item 3, which is next.

#### 2026-10-30: item 3, the planted deferral and contradiction; one half is the instrument

The two misses have different causes. One is in the instrument, the other in the subject.

**The deferral: the instrument. Fixed.**
- The column compared the recorded keys with the planted keys without translating them. A model
  drafts under its own ids, so a planted deferral recorded live read 0. Run 7 found this; it was
  not fixed until now.
- `measure` now translates each recorded deferral and each asked contradiction into the expected
  bundle's spelling before comparing. It uses the scripted user's own alignment, against the final
  files. A key that cannot be aligned is compared as recorded.
- **Seal.** An oracle extractor that renames the impact review and its approval step, as the runs
  did. The run records the deferral under the renamed key, and both planted columns must read 1.
  `tests/socratic` gives 76 passed. With the compare left untranslated (a mutant, restored with
  `cmp`), the seal is red at the deferral column.
- **Rescored from the saved runs** (no new model run): the planted deferral was recorded in 10 of
  the 12 PCN runs, 7 to 18. Runs 8 and 10 did not record it.

**The contradiction: the subject. Not fixed; it needs a ruling.**
- Rescored the same way, the planted contradiction was asked in 0 of 12 runs. It is a real miss.
- How it is planted:
  - The opening says anyone may take the engineering disposition, including whoever logged the
    notice. So that step's `excludes` is `[]`.
  - The bank entry for the program approval's `excludes` says the submitter "may never sign off
    either review". That overwrites `[]`, and the overwrite is the contradiction.
  - The entry is reached only when the loop asks who is barred from the program approval.
- **What the runs did.** Runs 10 to 18 drafted `excludes: []` on every approval step, and no
  `excludes` question was ever asked.
  - That includes the program approval in runs 16 to 18. Its bank answer says nothing about who
    may answer.
  - The required slot (§10(b)) was satisfied by a value the model wrote itself. This is cause 1 of
    run 7 again. The grammar's "never fill a default" line did not stop it.
- So the contradiction is not missed by the detector: the question that carries it is never asked.
  Nothing in the loop can tell a slot the person filled from a slot the model filled. Three ways to
  make that difference visible, none built:
  1. **Attribution by quote.** Every value set for a required slot carries the person's words it
     came from. The loop keeps the value only when those words appear in that turn's statement.
     Otherwise it drops the value, and the slot is asked.
     - This is "detect and attribute, never insert" applied to the slots.
     - It changes the patch grammar, and needs the model to quote.
  2. **Turn binding.** A required slot counts as filled only if it was set in the turn that asked
     it. Otherwise it is asked once to confirm.
     - No grammar change.
     - It also re-asks slots the person did state in passing, such as the opening's `[]` for the
       disposition. Re-asking that one is exactly what would surface the planted contradiction.
  3. **A grammar line only,** naming `excludes: []` as a value the statement must say. Runs 10 to
     18 already ignore the general rule.

#### 2026-10-30: the turn check, a stalled signal, and a terminal is what a row points to

Ruling (architect, 10-30): build the turn check (remedy 2 above) and take three runs. Put the two
run-18 fixes in the same build: the grammar line "a terminal is what a row points to", and a
stalled signal on a repeated question whose answer changed nothing.

- **The turn check.** For each required slot the draft holds a value for, take the last turn that
  set each of its leaves. The slot is attributed if, at or after that turn, the person answered
  either:
  - a question whose key is the slot's key, or a dotted prefix of it either way;
  - for a task kind, the question about that step's stage, which asks what the approver decides;
  - a confirm or an overwrite contradiction that names the leaf.

  The opening asks nothing, so it attributes nothing. An unattributed slot becomes a `confirm`
  gap: "the draft says ..., but you were never asked about it. Is that right? If not, what is
  it?" Its `revises` is the slot's own leaves, so an answer that differs replaces the value, and a
  leaf the answer touches outside the slot is an overwrite contradiction, asked as any other.
  - Slots checked: `trigger.stages`; `approvals.<wf>.<step>.task_kind` (the step's task kind and
    the kind's `accepts`); `actors.<wf>.<step>.excludes`; `<facet>.<wf>.next` for a complete
    routing table (`matches`, `domain`, `rows`, `terminals`).
  - A confirm is asked once, after every missing item. Unanswered, it is left open; it may not be
    deferred.
- **What it costs.** The check cannot tell a slot the person stated in passing from one the model
  invented; both were set by a turn that asked something else. So each fixture now confirms the
  slots its person stated in passing: PCN 1, maintenance 2, training 4. The bank answers each in
  the person's own words. The oracle question counts (t7) move from 13/10/11 to 14/12/15.
- **The stall.** When a question is asked the second time and its answer leaves the files and the
  deferrals exactly as they were, the key is recorded in `stalled` and left open as "stalled:
  asked again and the answer changed nothing". It is not counted as unresolved. The loop already
  stopped at two asks; the stall only names why.
- **The terminal.** The grammar gains: "A terminal is what a row points to (`then: <terminal>`),
  not an outcome: every value in the domain still needs its own row, and an outcome that ends the
  case has a row whose `then` names a terminal listed in `terminals`." A row slot for an outcome
  already listed in `terminals` says so in its question: the row still has to name it.
- **The scripted user narrows its path answers.** When it answers by path (no bank entry under
  the asked key), it now repeats the person's words but sets only the one fact asked. Before, it
  replayed the whole entry it matched, often the opening. That re-set values the person had since
  revised, and under the turn check the re-sets raised overwrite contradictions nobody planted
  (training: `accepts`, `reason_required`). This changes the instrument: the "answered by path"
  answers of runs 19 on are narrower than those of runs 7 to 18.
- **The measure row** gains `confirms`, `stalled` and `contradictions_asked`.
- **Seals.** `tests/socratic` gives 88 passed (12 new):
  - each fixture's oracle run confirms exactly the slots its person stated in passing;
  - an extractor that writes `excludes: []` on the program approval unasked, as runs 10 to 18
    did: the slot is confirmed, the answer overwrites it, the planted contradiction is asked, and
    the result is runnable and equal to the expected bundle. Control: answered in its own turn,
    the slot is asked as missing, never confirmed;
  - an unanswered confirm is asked once and left open, never deferred (an `excludes` key, and a
    task kind, which no other rule keeps from deferral);
  - the opening attributes nothing, with a control;
  - a repeated question whose answer changes nothing is stalled; control: a second answer that
    changes the draft is not;
  - the grammar line, and the terminal hint in the row question, with a control.
- **Mutants,** each restored and checked with `cmp`, each red on an assertion: every slot
  attributed; no stage relation for the task kind; a confirm deferrable; a confirm asked twice; a
  stall on the first ask; a stall that ignores a change; no grammar line; no row hint; the
  scripted user not narrowed.

Three runs on PCN at `f218ad2d`, same model and harness, with no walk or roll in flight. The bank is
now 14: it includes the acknowledgement's `excludes`.

| run | questions / bank | runnable errors | semantic diffs | open | answered by path | model errors | confirms | stalled | contradiction | deferral | status | seconds |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 19 | 27/14 | 0 | 5 | 2 | 5 | 1 | 8 | 0 | **1/1** | 1/1 | cannot_run | 542 |
| 20 | 22/14 | 0 | 3 | 2 | 6 | 0 | 8 | 0 | **1/1** | 1/1 | cannot_run | 466 |
| 21 | 34/14 | 0 | 6 | 6 | 5 | 1 | 9 | 0 | **1/1** | 1/1 | cannot_run | 541 |

- **The planted contradiction was asked in all three runs.** It was asked in 0 of the 12 PCN
  runs before (7 to 18, rescored). In each run the loop:
  1. confirmed the program approval's `excludes`, which the model had written unasked;
  2. got the bank answer that the submitter may never sign off either review;
  3. asked the overwrite contradiction on the impact review's `excludes`, which is the planted one.

  This is the path the seal fixes. The planted deferral was recorded in all three runs too.
- **All four stages were drafted in all three runs, with no runnable errors.**
  - Run 18's class (an outcome put in `terminals` with no row) did not recur: 0 runnable errors in
    each run.
  - Runs 19 and 21 raised contradictions on a table's `terminals` and `rows`. Each was deferred.
- **All three are `cannot_run`, for the same reason.** The model drafted the record stage's wait as
  a human approval. The expected stage is an emit and a `signal_await`: the records group files it
  and says so.
  - So the turn check confirms two slots the person never stated, in each run: who is barred from
    the record step, and the routing after the record.
  - The scripted user has no answer for either. A confirm may not be deferred, so both stay open.
  - In runs 19 and 20 those two confirms are the only open keys.
  - The confirm did its job: it found a value the model invented. A real person would say the
    record is not an approval. The scripted user can only answer from the bank, so it cannot
    refute an invention. That is a limit of the instrument, not a fix for the subject.
- **Run 21 also left a stage undrafted.** The model named the acknowledgement `minor_ack`, so the
  declared stage `acknowledgement` stayed undrafted. Three chaining tables kept a `timed_out` row
  the runner refuses, as runtime refusals. Those four keys were each asked twice, and the user could not answer.
- **The stall did not fire.** An answer the user could not give is already reported as
  unanswerable, before the stall check. Run 21's four repeats are all of that kind. No run had a
  second answer that applied and changed nothing.
- **The confirms ask the model's own spelling.** 8, 8 and 9 confirms per run, against 1 under the
  oracle. Every unasked `excludes` and task kind the model wrote is asked once. Each costs one
  turn: questions per run ranged 9 to 32 in runs 16 to 18, and 22 to 34 here.
- **Another contradiction recurs:** the program approval's bar overwrites the acknowledgement's
  `excludes` too, in all three runs. The transcript bars the submitter from "either review", not
  from the acknowledgement. Each time it was asked and deferred.
- **The restate arm.** A positional path was refused once in run 19 (`steps[0].excludes`). In
  run 21, a row selector with a dotted key (`rows[when.outcome=...]`) was refused once.
- **Owed, not built.** A confirm the person cannot answer leaves the draft `cannot_run` for ever.
  Two ways a person could answer "that is not right", for a ruling:
  - let the scripted user refute a confirm whose slot is absent from the expected bundle;
  - let a confirm's answer remove the slot's value.

  Each changes the instrument, the loop, or both.

  Both are built, together, in the next subsection. Neither works alone: a rejection the loop
  cannot act on leaves the draft `cannot_run`, and the loop's rewrite has nothing to answer.

#### 2026-10-30: a confirm may be answered "that is not right"

Ruling (architect, 10-30): build the confirm rejection and take three runs. If a run is runnable
with the planted contradiction caught, this ADR leaves draft.

- **The loop: a confirm's answer may rewrite what it names.** Each confirm now carries a rewrite
  scope beside its `revises`:
  - for a step's slot (`excludes`, task kind): the whole step (`steps[id=<step>]`), and, when the
    step names a task kind, that kind's file as a whole;
  - for `trigger.stages` and a routing table's `next`: their own leaves, as before.

  An answer to a confirm may carry `unset` entries, applied before its sets.
  - An unset outside the scope is refused, and so is any unset that answers something other than
    a confirm.
  - A set inside the scope overwrites without a contradiction. A set outside it is an overwrite
    contradiction, as before.
  - A kind file in the scope can be removed whole, never rewritten leaf by leaf.
  - An unset forgets the turns that set what it removed.

  What an answer attributes is still its `revises`, so the oracle question counts are unchanged
  (14/12/15).
- **The grammar.** The reply is `{"set": [...], "unset": [...], "defer": [...]}`, and an unset
  entry is `{"file", "path"}`. One rule is added: "When the question is a confirm ("Required, to
  confirm: ...") and the user says it is not right, redraft what the question names from their
  words: set the new values, and UNSET the fields that no longer apply (path "" of
  task_kinds/<kind>.yaml removes a task kind only that step named). Never unset anything else."
  The parser accepts `unset` and checks its entries' shape.
- **The instrument: the scripted user refutes a step that is not there.** The user rejects a
  confirm only when all of these hold:
  - it is a confirm of a step's slot (`excludes` or task kind);
  - the stage it is in aligns with an expected stage;
  - either the expected stage has no step of that kind, or the expected step holds no such value.

  The answer is "No, that is not right.", followed by the person's own words for that stage from
  the bank. It carries no fact; the model must redraft from the words. The user never denies a
  value the expected bundle holds, and any other confirm it cannot answer stays unanswerable. Each
  rejection is recorded in a new `rejected` column. This changes the instrument: from run 22 on, a
  step the model invented can be refuted. In runs 19 to 21 it could not.
- **The residue.** A deferral of a slot the redraft removed stays recorded. Under the oracle with
  the run-19 invention, those are the record approval's deadline and the filing kind's
  `reason_required`. The files equal the expected bundle, but the deferral list names two slots
  the bundle no longer has. Nothing cleans them up yet; a reviewer has to read them as stale.
- **Seals.** `tests/socratic` gives 99 passed (11 new):
  - the run-19 shape under the oracle: the extractor drafts the record's wait as a human approval.
    The user rejects the one confirm, in the stage's words. The redraft is runnable and equal to
    the expected bundle, and the planted contradiction is asked. Control: an extractor that
    ignores the rejection leaves the draft `cannot_run`;
  - a confirm rewrites its step and removes the task kind only that step names, with no
    contradiction, and forgets the turns that set what it removed. Control: a set outside the
    step is an overwrite contradiction;
  - an unset outside the scope is refused, three ways: another step's leaf; a leaf of the kind
    file; a kind another step names. An unset that answers a missing slot is refused too;
  - the scripted user never denies a value the expected bundle holds. Control: it rejects only a
    confirm;
  - the grammar and the parser carry `unset`.
- **Mutants,** each restored and checked with `cmp`, each red on an assertion:
  - unsets ignored;
  - the scope ignored for sets;
  - an unset allowed outside a confirm;
  - a scope as wide as the whole file;
  - a kind-file scope that admits leaf unsets;
  - removed leaves keeping their set turns;
  - the parser dropping `unset`;
  - no grammar line;
  - the user never rejecting;
  - the user rejecting a gap that is not a confirm;
  - the user denying a value the expected bundle holds.

  The set-turn mutant at first survived. The rewrite seal now asserts what was forgotten and what
  stayed.

Three runs on PCN at `d9c97b50`, same model and harness, with no walk or roll in flight.

| run | questions / bank | runnable errors | semantic diffs | open | answered by path | model errors | confirms | rejected | contradiction | deferral | status | seconds |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 22 | 25/14 | 0 | 6 | 3 | 5 | 0 | 8 | 1 | 0/1 | 1/1 | cannot_run | 517 |
| 23 | 23/14 | 2 | 6 | 2 | 1 | 0 | 8 | 1 | 0/1 | 0/1 | cannot_run | 474 |
| 24 | 16/14 | 1 | 5 | 3 | 3 | 0 | 6 | 1 | 0/1 | 1/1 | cannot_run | 366 |

**The gate is not met.** No run is runnable, and the planted contradiction is scored in none. This
ADR stays a draft, and no PR is opened.

- **The rejection was given in every run, and the redraft never landed.**
  - In each run the model drafted the record stage's wait as a human approval again, with a task
    kind and `excludes: []`.
  - The scripted user rejected its `excludes` confirm, once per run, in the stage's words.
  - In all three final drafts the step is still a human approval with its task kind and
    `excludes`, and the record's `next` confirm stays open.
  - That is the shape the seal's control describes: a rejection the model does not act on.
  - The measure keeps no per-turn record of the model's replies. So it cannot tell which of these
    happened: the model returned no unset, it returned one outside the scope, or a later turn
    re-set the step. No patch was refused, which rules out an unset outside the scope.
- **The planted contradiction was not scored, for two different reasons.**
  - **Runs 22 and 24.** The submitter's bar reached only the program approval, never the impact
    review, so no overwrite was raised on the planted leaf.
    - In both runs, the impact review's `excludes` was confirmed and answered by path from the
      opening, which writes `excludes: []` there. That is the planted half.
    - The program approval's confirm was answered from the bank: "may never sign off either
      review". The model set the bar on the program approval only.
    - In runs 19 to 21 the same answer had carried the bar to both reviews. Whether it does is
      the model's reading of "either review", not the mechanism.
  - **Run 23.** An overwrite contradiction on the impact review's `excludes` was asked, in the
    planted shape. But the trigger's selection table is not declared, and its `after` names no
    definition. So no stage aligns, and the measure cannot read the key as the planted one. It is
    scored 0/1, as the rule says. It is not rescored by hand.
- **Other open keys.**
  - Run 22: a `timed_out` row on two chaining tables, refused at runtime, asked twice each.
  - Run 24: the acknowledgement's `next` and `ends`.
  - Runs 23 and 24 have a selection table whose `after` names no definition: the trigger was
    named differently from the table.
- **The stall did not fire.** No model errors and no refused patches occurred in any run.
- **Owed, for a ruling.**
  - The measure should record each turn's reply. Without that, a rejection the model ignored
    cannot be told from one it acted on that a later turn undid.
  - The rejection works only if the model redrafts. Two ways to make that more likely: name the
    step to redraft in the confirm's question, or make the rejection's answer carry the stage's
    facts, not only its words. The second changes the instrument again.

#### 2026-10-31: each turn's reply is logged; the confirm names its step; the rejection carries the stage's facts

The architect ruled both of the owed items, and a fix to how the measure names the trigger stage.
The bar stands: a run that is runnable with the planted contradiction caught.

- **Each turn's reply is logged.**
  - The loop's message log now has one entry per turn, starting with the opening (turn 0).
  - Each entry has the question's key and kind, the person's answer, and every reply to it.
  - A reply holds the patch as returned, the model's own text when the extractor keeps it, and
    the refusal if the patch was refused. A restated patch is a second reply in the same turn.
  - A rejection's turn also logs the correction it carried.
  - The measure row gains `turns`, the whole log.
- **A step's confirm names the step.** The question adds "It is about step `filed` of
  workflows/pcn_record.yaml." A confirm of any other slot, such as the trigger's stage list, adds
  nothing.
- **The rejection carries the stage's facts.** This changes the instrument.
  - The scripted user's rejection keeps its words: "No, that is not right.", then the stage in
    the person's own words.
  - It now also carries a correction, in the draft's own names, and marks which confirm it
    corrects.
  - **The step has a counterpart in the expected stage.** The correction unsets only the
    rejected slot's value.
  - **The step has no counterpart.** The expected stage must have exactly one step that nothing
    in the draft is paired with, and that step must name no task kind. The correction then
    rewrites the draft's step into it, leaf by leaf, under the draft's step id:
    - it sets each leaf whose value differs;
    - it unsets each leaf the new step does not have;
    - it removes the task kind only that step named.
  - **Otherwise** the correction is empty, and the rejection is words alone, as before.
  - For runs 19 to 24's record step, the correction sets `kind: signal_await`,
    `signal: pcn_filed` and `accepts: [filed]`. It unsets `task_kind` and `excludes`, and removes
    the filing task kind. The audience already matches, so it is not set.
  - The model is shown the correction, under CORRECTION, only on a rejection. An ordinary
    answer's facts still reach it as words only.
  - The grammar says a CORRECTION is applied as given.
  - Every correction is a set or unset inside the confirm's rewrite scope, so the rules that
    govern any answer to a confirm still hold.
- **The measure names the trigger stage the way run 23 drafted it.** This changes the
  instrument.
  - In run 23 the trigger's `selection` named a field, and the selection table named the trigger
    by `after`.
  - When the trigger's `selection` names no table, and exactly one table names the trigger by
    `after`, that table is the trigger stage. Two such tables choose neither.
  - The semantic diffs are unchanged, so a draft written this way still counts as different.
  - Rescored with this rule, run 23's stored final files read its overwrite contradiction on
    the impact review's `excludes` as the planted one: 1/1. Run 23 is still not runnable (two
    runtime errors), so it does not meet the gate. Runs 22 and 24 stay 0/1.
- **Seals.** tests/socratic: 108 passed, 9 of them new. The redraft seal and its control were changed:
  - The scripted user's correction is the stage in the draft's own names, with its exact sets
    and unsets.
  - With the record drafted as a human approval, the oracle redrafts it from the correction
    alone. The run is runnable and exact, and the planted contradiction is asked. The control
    drops the correction and gets `cannot_run`. The correction was still offered and logged.
  - A step's confirm names its step. The control: the trigger's stage-list confirm names none.
  - The model sees CORRECTION for a rejection. The control: an answer by path with the same
    facts shows none.
  - The grammar mentions CORRECTION.
  - Each turn logs its key, kind, answer and every reply. A refused first reply is followed by
    its restatement in the same turn, and every other turn has one reply.
  - A reply logs the extractor's own text when it keeps one. The control: the oracle keeps none.
  - The measure row's `turns` has one entry per question, plus the opening.
  - The trigger stage falls back to the one table naming the trigger by `after`. The control:
    with two such tables, neither is chosen.
- **Mutants.** 13 mutants, each red on an assertion and restored by cmp:
  - log-missing-reply, refused-dropped, raw-dropped, correction-not-logged;
  - question-no-step;
  - correction-shown-always, correction-never-shown, no-grammar-correction;
  - correction-empty, correction-keeps-kind;
  - fallback-unguarded, fallback-removed;
  - turns-missing.

  Three of them were first red on a KeyError, not an assertion: refused-dropped, raw-dropped
  and correction-empty. Their seals now read with a default, so they fail on the assertion.

Three runs on PCN at `d1909291`, same model and harness, with no walk or roll in flight.

| run | questions / bank | runnable errors | semantic diffs | open | answered by path | model errors | confirms | rejected | contradiction | deferral | status | seconds |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 25 | 25/14 | 3 | 4 | 4 | 5 | 0 | 5 | 1 | 1/1 | 1/1 | cannot_run | 489 |
| 26 | 23/14 | 0 | 5 | 1 | 5 | 3 | 7 | 0 | 0/1 | 0/1 | cannot_run | 669 |
| 27 | 22/14 | 0 | 6 | 1 | 5 | 0 | 8 | 1 | 1/1 | 1/1 | cannot_run | 531 |

**The gate is not met.** Runs 25 and 27 catch the planted contradiction, but neither is runnable.
This ADR stays a draft, and no PR is opened.

- **The correction works.**
  - In runs 25 and 27 the model again drafted the record's wait as a human approval, and the
    scripted user rejected its `excludes` confirm once.
  - Both times the turn log shows the model's reply was the correction, set for set and unset
    for unset, and it was not refused.
  - The task kind only that step named was removed with it.
  - In run 26 the model drafted the record correctly, so nothing was rejected.
- **What left each run not runnable: a runtime refusal the scripted user cannot answer.** In
  each run the open key is one the loop raised from a runtime check. The rule says a runtime
  refusal may not be deferred, so it stays open.
  - **Run 25.** The model drafted the impact-review and program-approval task kinds at turns 0
    and 7 with a `renders_as` that holds only a title. Neither is a valid declaration, so both
    steps name an undeclared task kind. Three runtime errors remain, and four keys stay open.
  - **Run 26.** The acknowledgement's chaining table has a `timed_out` row from the opening,
    which the runtime refuses. It was asked twice and stayed open.
  - **Run 27.** The acknowledgement's chaining table has a `rejected` row, but its task kind
    accepts only `approved` and `escalated`. The loop asked "Can it end 'rejected'?" twice, and
    the scripted user had no answer. No runtime error remains, and that one key is the only
    thing open.
- **The planted contradiction.**
  - Runs 25 and 27: an overwrite on the impact review's `excludes` was asked, and it was read
    as the planted key.
  - Run 26: the impact review's `excludes` was answered by path from the opening. The bank
    answer "may never sign off either review" put the bar on the program approval only, as in
    runs 22 and 24, so no overwrite reached the planted leaf.
- **Model errors.** Run 26's three refused patches used an index path (`steps[0]`) or an
  append (`rows[+]`). Each was restated in the path grammar on the next reply and applied.
- **Owed, for a ruling.**
  - The remaining blocker in runs 26 and 27 is a chaining row for an outcome the expected stage
    does not have. That is the routing-table counterpart of a step the process does not have. The
    scripted user could answer it "no" with the row removed, as it now answers a confirm. That
    would be a change to the instrument.
  - Run 25's blocker is a task kind declared without its required rendering fields. Whether the
    loop should ask for those fields as a required slot, rather than leave them to a runtime
    error the person cannot answer, is a separate question.

#### 2026-10-31: runs 28 to 30 at the confirm rejection

The architect asked for three more runs with the confirm rejection, under the same bar. Three runs
on PCN at `57626cf5`, which has the same code as `d1909291`. Same model and harness, with no walk
or roll in flight.

| run | questions / bank | runnable errors | semantic diffs | open | answered by path | model errors | confirms | rejected | contradiction | deferral | status | seconds |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 28 | 27/14 | 1 | 5 | 2 | 6 | 0 | 7 | 0 | 1/1 | 0/1 | cannot_run | 542 |
| 29 | 26/14 | 0 | 6 | 2 | 5 | 1 | 9 | 1 | 1/1 | 0/1 | cannot_run | 611 |
| 30 | 26/14 | 0 | 6 | 2 | 5 | 2 | 8 | 1 | 1/1 | 0/1 | cannot_run | 580 |

**The gate is not met.** All three runs catch the planted contradiction, but none is runnable.
This ADR stays a draft, and no PR is opened.

- **The contradiction is caught in every run.** An overwrite on the impact review's `excludes`
  was asked, and it was read as the planted key.
- **The correction works.**
  - In runs 29 and 30 the record step was drafted as a human approval again, and its confirm was
    rejected.
  - Both times the model's first reply was the correction, set for set and unset for unset, and
    it was not refused.
  - In run 28 the record was drafted correctly, so nothing was rejected.
- **The same blocker in all three runs: a `timed_out` row the stage does not have.**
  - In each opening, the model gave the impact-review and acknowledgement chaining tables a
    `timed_out` row. Neither step has a deadline, and the expected stages have no `timed_out`
    outcome.
  - The runtime refuses each row. The loop asks "Can it end 'timed_out'?" twice per table, and the
    scripted user has no answer, so both keys stay open.
  - That is the blocker runs 26 and 27 owed a ruling on.
- **Run 28 also has a runtime error.** Its selection table names the trigger by `after`, the
  shape run 23 drafted. The measure now reads that shape as the trigger stage, but the runtime
  refuses it.
- **The planted deferral was not recorded in any of the three runs.** Each time, the person's
  answer "We have not agreed a turnaround for the engineering disposition yet" was drafted as
  `deadline_seconds: null`, not as a deferral. In runs 25 and 27 the same answer was deferred.
  That is the model's reading, not the mechanism. It does not bear on the gate.
- **Model errors.** Runs 29 and 30 had three refused patches between them, each with an index path
  (`steps[0]`). Each was restated in the path grammar on the next reply and applied.
- **Owed, for a ruling: as for runs 25 to 27.** With the rejection working, the planted
  contradiction is caught in five of the six runs since `d1909291`. What stands between those
  runs and the bar is now a routing row for an outcome the stage does not have. The scripted
  user cannot answer it, and a runtime refusal may not be deferred.

#### 2026-11-02: three rulings, built

The architect ruled on what runs 25 to 30 owed, and all three rulings are built.

1. **A routing row for an outcome the stage lacks is answered "no", and the row is removed.** The
   scripted user models a person who knows their process.
   - When a chaining contradiction reaches it with no bank answer, and the table aligns, and the
     expected table does not route that outcome, it says no. Its correction is the table without
     that row and without that outcome in its domain.
   - An outcome the expected table routes is never denied, and a bank answer comes first. The
     planted contradiction in the training fixture still gets its bank answer.
   - This is a change to the instrument. The measure row now has `denied_rows`.
   - Replayed on the final files of runs 26 to 30, it answers every chaining key those runs left
     open and no chaining contradiction remains. Four of the five then have no runtime error. Run 28
     keeps its selection table's `after`, which this ruling does not touch. That replay checks the
     answer only. It is not a run.
2. **Rendering fields are never a dialogue question.** They come from the task kind's declaration
   default. The draft drops `renders_as` whether the model sets it whole, by leaf, inside a whole
   file, or unsets it. A patch holding nothing else declares no task kind. `finalize` then writes
   the default, and a shipped kind's own rendering is untouched. The grammar says never to set it.
3. **A null written for a required value is asked as "defer this?". Null is not a deferral.**
   - This is a new gap kind, asked once, under the key the slot is asked by when absent.
   - A deferral removes the null and records the deferral. A value replaces the null without a
     contradiction. A null the person was asked about stands, until a later turn writes it again.
   - The slots are the three `_completeness` asks for while absent and the runner accepts: a step's
     `deadline_seconds`, a kind's `reason_required` and a trigger's `requires`. The last two were
     refused as a contradiction before, and now reach the same question.

Three things in this build go beyond the words of the rulings, and are for review:

- **`excludes: null`.** Who is barred may not be deferred (§5), so "defer this?" would be a question
  the loop must then refuse. It was read as "nobody is barred". It is now read as absent and asked
  as the required slot it is.
- **A stated "no limit" is asked too.** The ruling is literal, and a null the person stated cannot
  be told mechanically from one the model wrote for "not agreed". So the fixtures gain a bank
  entry where the person states there is no time limit: PCN's acknowledgement and training's
  security review. The bank answers "do not defer it". The oracle's question counts move from 14 to
  15 and from 15 to 16, and PCN's bank is now 15. This is one more question to a person, for each
  null they stated.
- **A model that keeps the null after "not decided" is not stopped.** The person's answer vouches for
  the leaf, so the null stands. The measure shows it as a semantic diff and a missed deferral. It
  does not bear on the status.

The seal for the null found a defect before any run. An answer that writes the null itself, which
is the shape of runs 28 to 30, was charged as "the answer did not settle it" and deferred without
asking. A null not yet asked about is now the next question, not an unsettled answer.

Seals: `tests/socratic`, 136 passed (28 new). 28 mutants, each red on an assertion and restored by
`cmp`. On the first pass one survived, a guard its control never reached, and two were red on a
`TypeError` and a `KeyError`. The seals were tightened, and those three now die on assertions.

#### 2026-11-02: runs 31 to 33 at the three rulings

Three PCN runs at `0c76f6fe`, with the same model and harness and nothing else in flight.

| run | questions / bank | runnable errors | semantic diffs | open | answered by path | model errors | confirms | rejected | contradiction | deferral | status | seconds |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 31 | 28/15 | 0 | 5 | 1 | 5 | 1 | 7 | 0 | 0/1 | 1/1 | cannot_run | 705 |
| 32 | 22/15 | 0 | 5 | 0 | 4 | 0 | 9 | 1 | 1/1 | 1/1 | runnable | 596 |
| 33 | 28/15 | 0 | 4 | 0 | 5 | 0 | 7 | 1 | 1/1 | 1/1 | runnable | 562 |

**The gate is met in its words, by runs 32 and 33. Neither is the workflow the transcript describes.**
Both finish `runnable` with the planted contradiction caught. In both, a stage the person described
cannot be reached, because no table routes to it:

- **Run 32: `program_approval` and `record` are unreachable, two of four definitions.** The opening
  guessed the impact review's `approved` and `rejected` as `completed`. A later bank answer says
  approval goes to program approval. The model rewrote the whole table, kept those rows and added only
  `needs_info`.
- **Run 33: the record definition is unreachable, one of four.** The impact review routes to program
  approval correctly. Program approval's `approved` goes to a terminal, although the person says the
  disposition is then recorded.

Nothing in the loop or in `runnable` flags a definition no table routes to. A step or table with no
path from the trigger is, by design, not asked about, so the question that would catch this is never
reached. This is the same class as run 7 (above): runnable, and not the workflow. I have not built a
check, because the ruling on what `runnable` means is the architect's. A reachability refusal would
turn both runs to `cannot_run`.

**Reasons are lost in all three runs.** `reason_required` is `[]` on the impact review and the
acknowledgement, although the person states the reasons. Setting them later raises an overwrite
contradiction. The scripted user has no bank answer for it, the contradiction is deferred, and the
earlier `[]` stands. The bundle carries the deferral, so a ratifier would see it. This is the same
cause as item 2 of run 7.

**Run 31 does not meet the gate, for two separate reasons.**

- **The contradiction was never raised.** The opening says whoever logged the notice may take the
  impact review, so `[]` there is the right reading. At turn 13 the person says that whoever logged
  the notice may never sign off either review. The model wrote that on program approval only. Nothing
  overwrote the planted leaf, so the final bar on the impact review is nobody, which is the opposite
  of what the person said last.
- **One key stays open.** The record has only an emit step and a chaining table on `dispositioned`, so
  `outputs.record.ends` is a runtime refusal. The scripted user cannot answer it, and it may not be
  deferred.

**What the rulings did:**

- **Ruling 1:** run 31 denied both `timed_out` rows it was asked about, and each row was removed.
  Runs 32 and 33 did not need it. `denied_rows` is empty in both.
- **Ruling 2:** no `renders_as` problem in any run. Final files carry the declaration's default.
- **Ruling 3:** each run asked one null, the acknowledgement's stated "no limit", and that null stands.
  The planted deferral is recorded 1/1 in all three, with the leaf absent. Runs 28 to 30 were 0/1.

The record's confirm was answered "that is not right" in runs 32 and 33, and each carried the stage's
facts. The selection-table shape that run 28 wrote for `after` did not recur.

#### 2026-11-02: at the merge, an emit may dispose

Merging master reddened the positive control on the shipped rows. Master's `595574c2` gave `emit` an
optional `disposes`, and `maint_release` now ends that way. The loop's copy of the runner's rule did
not know the field, so it asked a shipped definition how it ends. The loop now reads the rule as the
chaining seal does: a declared `disposes` ends the definition, and the table is held to that value.

- **The grammar is unchanged.** The model is not told about `disposes`, so the runs above measure the
  same dialogue. Run 31's open key, a record with only an emit, is the shape this field could express.
  Whether the dialogue offers it is the architect's call.
- **The runs above predate the merge.** They ran at `0c76f6fe` against SDK v0.9.10. The suite after
  the merge runs against master's pin, v0.9.12. No model run has been taken since.

Seals: `tests/socratic`, 141 passed (5 new). Four mutants, each red with the file restored by `cmp`.
One of them, reading an undeclared `disposes` as disposing, is red on a `TypeError` in the loop's own
derivation, not on an assertion.

#### 2026-11-02: the architect's rulings on runs 31 to 33

1. Proposed stands. The ADR records the design and its measurements, including the gap. The bar for
   "the loop works" is not met until (2) is built and a run is runnable with all four stages
   reachable.
2. `runnable` refuses any definition no table routes to from the trigger. Runs 32 and 33 become
   `cannot_run`, which is the truth.
3. `reason_required` is a required slot per approval step ("which outcomes need a reason?"), by the
   same mechanism as `excludes`.
4. `disposes` goes in the grammar, asked only for emit steps.

Both interpretations stand: a null for who is barred reads as absent, and a stated "no limit" null is
asked. Three runs follow (2), (3) and (4).

#### 2026-11-02: rulings 2, 3 and 4, built

**Ruling 2, the refusal.** `runnable` reports `definition <id>: no table routes to it from the
trigger` for each definition the walk from the trigger does not reach. Read against the stored
drafts: run 32 now refuses two definitions and run 33 one, so both are `cannot_run`, as ruled. Run 31
was already `cannot_run` on its open slots, and all its definitions are reached.

The walk had to change first. `_reachable` held one list of terminals across all tables, while
`runnable` reads a row's `then` against its own table's terminals. A value that was a terminal in
one table therefore stopped a row in another, and the walk could refuse a bundle the runner runs. It
now reads each table's own terminals.

**A question ruling 2 did not name: my call, for review.** A refusal the person never hears can't be
answered, and §9 says a refusal is never deferred: the loop keeps asking, or stops with "cannot run,
missing X". So `required_slots` also asks `steps.<id>.routed`: "no stage leads to X, so a case can
never reach it. Which stage's ending leads to it, and on which outcome?" It is asked only when no
other required slot is open, because a table still being drafted is asked for by name first, and it
may not be deferred. The answer may rewrite a table's rows, its terminals and its input's domain. The
model writes the row; the loop inserts nothing. The ruling did not ask for this. Without it, a run
that reaches the refusal can only end `cannot_run`.

There is one limit. The person can't yet answer "that is not a stage": a definition the model invented
stays open, and the run stays `cannot_run`. That is the honest result, and the runs below may show it.

**Ruling 3, the reasons.** Each approval step now has the required slot
`approvals.<definition>.<step>.reason_required`, built as `excludes` is. A null reads as absent. A
value nobody stated is confirmed once, and the answer may replace it, so a stated reason is no longer
charged as an overwrite of a `[]` nobody asked for; that charge is what lost the reasons in runs 31
to 33. The per-kind question and the per-kind null are gone. The grammar now says `reason_required`
is required, and that `[]` means no answer needs one.

The cost is in the fixtures. Each person's reasons used to arrive inside a stage answer, which is not
attributed to the step, so each is now confirmed:

| fixture | questions before | questions now | new entries in the person's words |
| --- | --- | --- | --- |
| `pcn_review` | 15 | 18 | 3 |
| `maint_case_release` | 12 | 14 | 2 |
| `training_course_approval` | 16 | 18 | 2 |

The training content review adds no question: its reasons are answered in its own contradiction.

**Ruling 4, `disposes`.** The grammar says an emit step that is itself what settles its workflow sets
`disposes`, that its chaining table routes that value, that a later confirmation is a `signal_await`,
and that only an emit step has `disposes`. A definition that only sends is asked "does sending X
settle it, and with what outcome, or does someone confirm it afterwards?". A definition with no emit
keeps "who or what confirms it?". A `disposes` nobody stated is confirmed under
`outputs.<id>.ends`, and one on any other kind of step is refused by `runnable` and never confirmed.

**The instrument.** The scripted user answers the three new slot forms from the expected bundle:
reasons from the kind the step names, a routed question from the first table with a row into that
stage, and an ending from that stage's last disposing step. It also rejects a reason confirm on a step
the process does not have. The measure row gains `unreachable`.

**Seals and mutants.** `tests/socratic` has 171 passing at `LOCKED_SDK=sdk_0912`, and the gov ratchet
24. All 19 mutants of the new behaviour went red. Three survived the first pass:

- Removing the reason line from the grammar survived, and now has a seal.
- Confirming a `disposes` on any kind of step survived, and now has a seal.
- Removing `_slot_target` from the scripted user's rejection survived because it decided nothing.
  The target always comes from the expected bundle, so the check always holds. That call is removed,
  and its mutant is replaced by one on the reason form of a step slot.

One red is a `KeyError`, not an assertion: treating a null as held, where the test indexes the slot
that should be open. The slot's absence is the failure the test exists to catch.

#### 2026-11-02: run 34 crashed, and a value of the wrong shape is now refused

The first run after rulings 2, 3 and 4 did not finish. The model wrote a row's `when` as a string, and
`decide` raised `AttributeError` from inside `problems`, `required_slots` and `runnable`. No output was
written, so what else run 34 held is lost, and it counts as none of the three runs. Rulings 2 to 4 did
not introduce this. `_apply_or_charge` already promised that a run never crashes on model output, and
the promise covered only a `PatchError`.

**The census.** One row is a sample, so I put eight wrong-typed values at every node of the PCN bundle
and called each reader: 3264 calls, 20 distinct crash sites, across the tables, the kinds, the steps and
the trigger.

**The refusal.** This defends the class rather than the 20 sites. A patch is already tried on a copy, so
`_refuse_unreadable` reads that copy with `_all_gaps` and `runnable`. If either raises anything, the
patch is refused and the model restates it with the refusal in hand, under the existing restate limit.
This goes beyond the rulings' words: it is my call, for review. `decision_table.py`, the production
evaluator, is deliberately unchanged, so a broken row reaching it directly still raises.

The instrument needed its own guards. Values the loop tolerates still reach the measure, so
`semantic_diffs` records a draft with no canonical form as a difference, and `_steps_of` reads a `steps`
that isn't a list as empty. The first pass of the census found 7 such sites in the instrument.

| fixture | wrong-typed values refused | passed the refusal | crash sites in later readers |
| --- | --- | --- | --- |
| `pcn_review` | 135 | 681 | 0 |
| `maint_case_release`, `training_course_approval` | 334 | 1322 | 0 |

The later readers are `finalize`, `semantic_diffs`, the reachability walk and the scripted user on each
open gap. This census covers one wrong value at one node of a complete bundle. It does not cover a
wrong value in a partial draft, or two at once. A reader the refusal does not call, reached only from a
partial draft, could still raise.

**The cost.** `runnable` now runs on every patch, so `tests/socratic` takes about 40 to 47 seconds, up
from about 9.5. In a model run this is small beside the model's own time. I have not measured it there.

**Seals and mutants.** `tests/socratic` has 189 passing at `LOCKED_SDK=sdk_0912`, and the gov ratchet
24. All six mutants of the refusal and the guards went red: not reading the draft at all, catching only
`AttributeError`, not calling `_all_gaps`, not calling `runnable`, and removing each instrument guard.
Removing `runnable` from the refusal is held by one seal only.

**A correction to the runs through 33.** They ran under `-I`, which ignores `PYTHONPATH`, so they
imported the venv's `iagent_mesh` 0.9.5 and not the 0.9.12 overlay. The loop imports only `task_kinds`
from the SDK, and that file is byte-identical in the two versions, so their results stand. The runs below
use the 0.9.12 overlay.

#### 2026-11-02: runs 35 to 37, and the bar is not met

Three complete PCN runs at `6122cf6f`, one at a time, with the same model and harness, on the 0.9.12
overlay. Run 34 is not one of them: it crashed, as the section above says.

| run | questions / bank | runnable errors | unreachable | semantic diffs | open | answered by path | model errors | confirms | rejected | contradiction | deferral | reasons | status | seconds |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 35 | 27/18 | 0 | 0 of 4 | 3 | 1 | 4 | 0 | 12 | 1 | 1/1 | 1/1 | held | cannot_run | 569 |
| 36 | 26/18 | 2 | 2 of 4 | 6 | 3 | 8 | 0 | 11 | 1 | 1/1 | 1/1 | lost on one kind | cannot_run | 645 |
| 37 | 30/18 | 1 | 0 of 4 | 3 | 0 | 6 | 0 | 11 | 0 | 1/1 | 1/1 | held | cannot_run | 563 |

**The bar is not met: no run is runnable.** Two of the three have all four stages reachable. Runs 31
to 33 had the planted contradiction in two of three and lost the reasons in all three. These three
report it every time and hold the reasons in two.

**Why each stopped:**

- **Runs 35 and 36: the loop charged the model's correct answer as a contradiction.** The opening
  guessed the acknowledgement as an emit that settles itself. The loop then asked, correctly, "the
  draft says sending it settles the stage, but you were never asked. Is that right?" The person said a
  component engineer answers it. The model rewrote the stage as a `human_await` with both outcomes,
  which is what the fixture expects. The loop charged that as "Earlier you said {emit}; now
  {human_await}. Which holds?". The person never said emit, and the question before it had just said
  so. The scripted user could not answer, the contradiction was deferred, and the guess stayed. This
  is the mechanism that lost the reasons in runs 31 to 33, at a wider site: ruling 3 cured it for
  `reason_required` alone. Its last effect is the open slot: the confirm on the guessed table is one
  the scripted user cannot answer, and it may not be deferred.
- **Run 36 also: the refusal is true and the model could not act on it.** The model listed
  `program_approval` as a terminal of the table whose row routes to it, so a case stops there and the
  stage and the one after it are unreachable. The routed question says "no stage leads to program
  approval", which names no cause. The model rewrote the same table with the same terminal, and the
  slot stalled.
- **Run 37: an error no question reaches.** The selection table carries `after` naming the trigger,
  and `runnable` refuses it. The grammar says what `after` means on a chaining table and is silent on
  a selection. No slot asks about it, so with nothing open the run ended `cannot_run`. Nothing is wrong
  with that ending, but one line of the draft decided it, and neither the person nor the model was told.

**Run 37 shows the bar is not the workflow either.** With `after` removed from the stored draft,
`runnable` reports nothing and all four stages are reachable, so it would clear the bar as worded. Its
record stage is still wrong: the person says the disposition is sent and then filed, and the draft has
one emit that settles itself as `recorded`, with no step that waits for the filing. Asked whether sending
settles it, the person said "then the records group files it and says so", and the model changed only the
emit's template. I have not examined the other semantic differences in these runs.

**Most contradictions the loop asks are not contradictions.** The planted one was reported in every
run. Besides it, the scripted user could not answer 7, 4 and 8 contradictions, all raised by the loop,
and each became a deferral. Run 37 opens with three of the form "you said what happens when review ends
'approved', but review's answers are empty. Can it end 'approved'?", asked before the task kind exists.
A person could answer these, and the scripted user answers only what its transcript holds, so these
figures understate what a person would get done. They also mean a person would be asked a false "earlier
you said" several times per run.

**What did not show up.** The shape refusal never fired in these three: no refused patches and no model
errors. It is held by its seals and the census, not by a live run. Run time is within the 562 to 705
seconds of runs 31 to 33, so the per-patch read adds nothing visible beside the model's own time.

**Asked of the architect.** Each is a change beyond the rulings, so none is built. I recommend yes to all
three:

1. A value nobody stated, corrected in the answer to its own confirm, is not a contradiction: the answer
   may replace what was guessed, including the step and its table. A contradiction needs something the
   person said. This also removes the false "earlier you said" and the empty-answers form.
2. A structural error the person can't answer goes back to the model as a refused patch, naming the
   cause: a terminal that is also a stage, or an `after` on a selection. The grammar gains both lines.
3. The scripted user answers a contradiction the loop raised, from the expected bundle, as it already
   rejects a routing row for an outcome a stage lacks. This follows (1) and does not replace it: on its
   own it would raise the score and leave the person being told what they never said.

The fourth is a question, not a recommendation: should the bar also ask that a run's stages have the steps
the person described? As worded, run 37 clears it with one line changed.

#### 2026-11-02: the architect's rulings on runs 35 to 37

1. Yes: a value nobody stated, corrected at its own confirm, is a correction, not a contradiction. The
   answer replaces the guess and its table.
2. Yes: a structural error the person can't answer goes back to the model as a refused patch naming the
   cause. Both cases go into the grammar.
3. Yes, after (1).
4. Yes: the bar requires each stage to have the steps the person described. A runnable spec that drops a
   step is not the workflow.

The refusal of a value of the wrong shape, which I had marked as my call, is accepted. So is the suite's
time of about 45 seconds.

#### 2026-11-02: the four rulings, built

**Ruling 1, the correction.** A confirm now carries what was built on the guess, and its answer may
replace those values without pending a contradiction. For a step's slot that is the answers and reasons
of the task kind the step names, and the routing table after its definition. Each is listed with the
slots that would have asked it. If one of those slots was answered, the person stated the value, and a
different answer still pends as a contradiction. "Stated" is the turn check this ADR already uses for
confirms. So a value that arrived inside a stage answer, or in the opening, counts as unstated unless a
question covered it. That reading is mine, for review: it is the existing standard, not a new one.

A workflow's `steps` is one list and so one leaf. A patch that rewrites the whole list lands only if every
other step comes through unchanged and in order, so correcting a guessed step cannot change one the
person described.

The empty-answers form is gone: a kind with no answers yet raises no "can it end" contradiction, and
`contradiction:task_kind` still asks for the answers. **What remains:** the ruling covers a confirm, so a
false "earlier you said" outside one still happens. Runs 35 and 37 raised `#accepts` after
`steps.<id>.routed`, run 35 raised `chaining.<t>.needs_info` with non-empty answers, and run 37 raised
`steps[id=ack].excludes`. Ruling 3 answers these; it does not stop them being asked.

**Ruling 2, the refusal.** A patch that lists a stage in a table's `terminals`, or puts `after` on the
table the trigger names in `selection`, is refused with the cause named, and the model restates it. The
grammar has both lines. "A stage" is a definition or a name in the trigger's `stages`, so a terminal is
refused even before that stage's definition is drafted. Two things beyond the ruling's words, for review:

- Only an error the patch introduces is refused. An error the draft already held does not block every
  later patch.
- The restatement may rewrite the leaf the refusal named, even one the person stated, because the error
  may come from a later patch: a new stage that an old terminal already names. Without this the restated
  patch would pend the terminal, keep the error and be refused again.

**Ruling 3, the scripted user.** It now answers a contradiction the loop raised, from the expected bundle,
and each is recorded in the row's `answered_contradictions`. Its answers are words only, with no facts
shown to the model, so the model is measured on the words as it is for any other answer. That is my
reading of "as it already rejects a routing row", which does carry facts; tell me if you meant the same
here. A single value is said as "It is a, b." or "It is none." A value with a structure, such as steps or
rows, is said in the person's own words from the entry that asks for it. An outcome the expected table
routes gets "Yes, it can end x. It can end: a, b." The trigger's form, a selection table's rows and a
value the bundle does not hold stay unanswered, and count as they did. A planted contradiction is banked
and never reaches this code, so detection is unchanged.

**Ruling 4, the bar.** The row gains `dropped_steps` and `bar_met`. An expected stage has dropped a step
if its step kinds are not an in-order subsequence of the paired draft stage's. Steps compare by kind, so
a step of the right kind with the wrong content is not counted, and `semantic_diffs` carries it. An added
step is not a dropped one. The pairing walk stops at a terminal, so a stage it can't pair counts as having
dropped all its steps, and such a stage is usually counted as unreachable too. The two columns can
therefore overlap on one stage.

**Checks.** `tests/socratic` 234 passed and the gov ratchet 24 passed, both with
`LOCKED_SDK=sdk_0912`, so the ratchet counts no new refusal site. The shape
census is unchanged, with the new reader included: 469 refused, 2003 passed, 0 crash sites over the three
fixtures. All 33 mutants are red on a named test, each restored and checked byte for byte. One was
first written so that the file failed to import, which is not a kill; rewritten, it went red on the test it
was written for.

#### 2026-11-02: runs 38 to 40, and the bar is not met

Three complete PCN runs at `5f7628d6`, one at a time, with the same model and harness, on the 0.9.12
overlay.

| run | questions / bank | runnable errors | unreachable | stages that dropped a step | bar | semantic diffs | open | answered by path | refused patches | confirms | rejected | contradiction | deferral | reasons | contradictions answered | status | seconds |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 38 | 27/18 | 0 | 0 of 4 | 2 | no | 3 | 0 | 8 | 1 | 11 | 0 | 1/1 | 1/1 | held | 1 | runnable | 669 |
| 39 | 29/18 | 0 | 0 of 4 | 2 | no | 4 | 0 | 5 | 2 | 12 | 0 | 1/1 | 1/1 | held | 6 | runnable | 677 |
| 40 | 27/18 | 0 | 0 of 4 | 1 | no | 3 | 0 | 5 | 0 | 12 | 1 | 1/1 | 1/1 | held | 3 | runnable | 603 |

**The bar is not met: every run is runnable with all four stages reachable, and none has every step
the person described.** These are the first runnable runs since `runnable` began to refuse a stage
nothing reaches. Runs 35 to 37 were all `cannot_run`.

**What is missing:**

- **The impact review's `render` step, in all three runs.** The person says an engineer "looks at the
  part, the maker and the change class and gives a disposition". Each run wrote one `human_await`. The
  grammar names `render` in a list of step kinds and says nothing about when one applies, and no gap
  or refusal asks for it, so nothing in the loop can catch this.
- **The record's `signal_await`, in runs 38 and 39.** The person says "Then the records group files it
  and says so". Both runs wrote an emit with `disposes`, which the grammar says not to do when someone
  confirms afterwards. The loop then asked, correctly, whether sending settles the stage. The scripted
  user repeated the stage's description instead of saying no, because its confirm rejection covers
  only a step's slots and this key is `outputs.record.ends`. The model answered with an empty patch in
  run 38 and changed only the template in run 39, and the confirm closed.
- **Run 40 kept that step, and shows ruling 1 working.** Its first draft made filing a `human_await`.
  The confirm rejection at `actors.record.file.excludes` replaced it with the `signal_await` and raised
  no contradiction.

**What the rulings changed:**

- **Ruling 1.** Questions saying "Earlier you said" went from 7, 5 and 5 to 3, 6 and 3, each count
  including the planted contradiction. Most of those left are outside a confirm, as the section above
  said they would be: run 39's six include three on a chaining table the model rewrote while answering
  another stage. Two are not, and they are a defect, below.
- **Ruling 2.** The structural refusal did not fire in any run: all three refused patches are the
  `steps[0]` path form. Neither error from runs 36 and 37 came back. Three runs can't separate the
  grammar lines from chance.
- **Ruling 3.** Ten contradictions were answered and one row was denied, and no run ended with one
  open. The trigger's form in run 38 stayed unanswered, as designed, and each planted contradiction
  was answered from the bank.
- **Ruling 4.** The bar now reads `no` on specs that `runnable` accepts, which is what it was ruled to
  do.

**Two defects in my build.** Neither changes whether the bar is met. I have not fixed either, so the code
stays what these runs measured.

**The first breaks ruling 1 at a confirm.** Runs 39 and 40 asked "Earlier you said nobody (empty); now
rejected, needs_info" about the impact review's reasons, straight after that kind's confirm. Nobody said
that: the opening guessed `[]`. A "can it end" contradiction lists the kind's `accepts` and
`reason_required` as what it revises, and answering a contradiction marks those leaves as stated, so the
later confirm treats the guess as something the person said. Run 38 answered the same contradiction after
the confirm and did not ask. I read this from the code and the order of the turns in all three runs; I did
not replay it. Ruling 3 exposed it, since that contradiction used to go unanswered. The fix is to mark only
what the question asked about. It costs one question in each of those two runs, and the reasons still held
because ruling 3 answered it.

**The second is in the scripted user.** The scripted answer to run 39's `terminals` contradiction said
"It is pcn_rejected, pcn_program_overdue": the expected bundle's names, not the draft's. The model wrote
them, the rows still named `rejected` and `program_overdue`, and the loop asked what those two were.
Neither question could be answered. So run 39's 29 questions include 2 my instrument caused, and its
contradiction count includes that answer. The model restored its own names, so the final table is not
affected. The answer should use the draft's names, or stay unanswered when it has none to use.

**Also seen, none of it counted by the bar:**

- Run 39's opening wrote `requires: []`. The slot is asked only when the key is absent, so the empty
  list was never asked or confirmed. It is that run's fourth semantic diff.
- Run 40 wrote the acknowledgement's and the program approval's `audience` without the `:SUSTAINMENT`
  qualifier the expected bundle holds, which accounts for two of its semantic diffs.
- Run 40 also wrote a `completion` block nobody stated on its `human_await` steps. Removing it from the
  stored files leaves the semantic diffs unchanged, so the comparison does not read it.
- Run 40's deferrals still hold `approvals.record.file.deadline`, a slot of the `human_await` that the
  `signal_await` replaced.
- Run 40 has one answer that did not settle its question. The row counts it and does not name it.

**Questions for the architect:**

1. Does "looks at the part, the maker and the change class" describe a `render` step? The fixture says
   yes, and so the bar does. If so, I recommend a grammar line: what someone looks at before they answer
   is a `render` step holding those fields. The model would be measured on that line alone, because the
   loop inserts nothing. If not, the fixture is wrong, and changing it is your call, since it would
   lower what the bar requires.
2. Should the scripted user reject `outputs.<stage>.ends` when the expected emit holds no `disposes`, as
   it rejects a step's slot now? I recommend yes: a person asked whether sending settles the stage, when
   someone files afterwards, says no. It would answer with the same words and facts as that rejection,
   so it would measure the same thing.
3. Should an unstated `requires: []` be confirmed once, as an unstated `excludes` is? I recommend yes. An
   empty list reads as "nothing is required", and nobody said that.
4. Should a deferral be dropped when its slot no longer exists? I recommend yes, so that a ratifier isn't
   shown a slot the spec doesn't have.

I will fix the two defects with whatever you rule, seal both, and measure them in the same three runs.
They need no ruling unless you want the scripted `terminals` form left unanswered.

## Consequences

- **The process owner describes. A steward reviews a diff.** The steward reviews the same rows a
  hand author would have written, gated by the same seals.
- **The dialogue's questions are the runtime's refusals, asked early.** With §5 enforced, the loop
  can end only as `runnable` or as `cannot_run` with what is missing. A bundle that reaches the
  ratifier as `runnable` has passed the checks `runnable()` makes. Most of those are the runner's
  own loaders; three are restated (§8). It is not evidence that the bundle says what the person
  said. Run 7 in §10 is runnable with half the workflow missing.
- **The question list mostly cannot drift from the runtime.** Most runtime refusals come from the
  runner's own models, so a new loader refusal becomes a new question with no dialogue change. Two
  lists are kept by hand:
  - the five completeness questions in §3(b), and the required slots in §3(c);
  - the three restated checks named in §8. Each should become a call into the runner's code.

Proposed units of work. This document assigns nobody:

| unit | likely home |
| --- | --- |
| ~~enforce §5: an open runtime refusal ends the dialogue as not runnable, never deferred~~ done in the prototype, 2026-10-25 | the prototype, before any verb |
| ~~give the extractor each event field's value vocabulary, not only the field names~~ done for the fixtures, 2026-10-25; where a deployment declares it is open | the prototype, before any verb |
| ~~the next build item (§9): who is barred from an approval. (a) The scripted user answers from the bank entry that sets the path; (b) `excludes` is required on every approval step~~ done, 2026-10-27 (§10) | the prototype, before any verb |
| the next most common item (§10): a contradiction the scripted user could not answer. (a) It is answered by path too; (b) whether an overwrite contradiction may be deferred. Not started; it waits for the architect | the prototype, before any verb |
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
- **Vocabulary.** The agent offers:
  - the event's declared fields;
  - the deployment's declared audiences;
  - each field's declared values. §8 shows the values are needed: "fit, form or function" against
    `fff`;
  - each answer's recorded label, and the runner's own outcomes (`timed_out`). A user says "send it
    back for rework" and never "rework".

  The fixtures now carry the values in their context and speak the labels (§9). Where a deployment
  declares them is open. A workflow that needs an audience nobody has declared is
  a grant change (a human's act), not a dialogue answer.

## Indicators for revisiting

- Users describe processes the bundle cannot express often enough that the refusals in §1 are
  the dialogue's main output.
- The extraction arm's error rate makes the restatement, not the question, the user's main work.
- A new step kind or table kind lands. Its refusals must become questions (§3a) before the
  dialogue offers it.
