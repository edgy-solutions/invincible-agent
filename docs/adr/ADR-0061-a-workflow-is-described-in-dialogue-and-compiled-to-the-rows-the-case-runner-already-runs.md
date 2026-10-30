# ADR-0061 — A workflow is described in dialogue and compiled to the rows the case runner already runs

**Status:** Proposed, draft. A prototype of the elicitation loop and three synthetic fixtures are
built and measured (§8). No route, no verb, no canvas. The architect ruled on the first measurement
on 2026-10-25 (§9). By that ruling, this stays a draft until the model arm produces one runnable
spec. None of the nine model fixture-runs after the rulings produced one (§9). On 2026-10-27, one
of three PCN runs was runnable, but it is not the workflow the transcript describes (§10). The
architect decides whether that meets the ruling.
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
