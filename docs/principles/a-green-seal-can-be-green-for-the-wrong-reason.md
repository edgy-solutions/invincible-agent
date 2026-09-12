# Principle: a green seal can be green for the wrong reason

**Status:** Governing testing principle, and the companion to
[[seals-must-be-proven-to-bite]]. That one says a seal you have not
seen fail is a claim rather than a control. This one is about the
seals that *do* bite, that you *have* mutated, and that are still
answering a different question from the one in their docstring.

Assembled 2026-09-08 across two lanes — the direct-path work in
`invincible-agent` and the Electric/stage work in `cortex-ui` — from
fourteen instances found in five days. Every one was green, most had
survived mutation, and two of them shipped defects a person found by
clicking.

## The tenet

**A check can pass, or fail, for a reason other than the one in its
comment.** The comment describes the property; the code describes an
observation that *co-occurs* with the property today. When they drift,
the test keeps reporting on the observation and everyone reads it as
the property.

This is not carelessness. Every instance below was written
deliberately, by someone who could state the property correctly, and
the substitution was invisible at the moment it was made.

## The shapes, and how each one hides

**1. A string that co-occurs.** A lint matched source text where the
defect is a behaviour — and flagged the comment that explained the
fix. *Tell:* the check reads source rather than an artifact the code
produced.

*And the checker's own file is in scope.* Fixing the citation scrape
(2026-09-09), a citation-shaped literal written to DEMONSTRATE the
scrape became one — three times in ten minutes: in the explanatory
comment, then in the control's own fixture list, each reported as this
file citing a document that never existed. The fixtures are now
assembled at runtime (`_D = "do" + "cs/"`). **A fixture that is
indistinguishable from its subject is not a fixture** — and for a
checker that matches on text, that is the normal case rather than the
exotic one. The instrument and the subject shared a surface, which is
also what the underlying bug was: a bare `<docs-dir>/name.md` and the
tail of `sibling-repo/<docs-dir>/name.md` are the same literal, and
only the character before it decides which repo is being cited.

**FOURTH INSTANCE, AND IT CAUGHT THE PARAGRAPH ABOVE.** Writing this
entry tripped the seal — a literal example, spelled out, was scraped as
a citation of a file that does not exist (`…:43`). Note what the
defence had to be: not an allowlist, but REFUSING TO WRITE THE STRING,
the same disposal as [[escapes-collapse-in-a-template-of-a-template]]'s
*name the character, never write it*. A rule about a text-matching
checker cannot be documented in the text it matches.

**2. A guard that returns first.** `observe` checked health before
consulting the missing-menu reader, so two mutants survived and a test
named "the cost-bindings trap" was passing for a reason other than the
one in its comment. *Tell:* the predicate is only ever reached through
a caller that can short-circuit. **Assume any predicate reached only
through a guarded caller is untested until asserted at its own
surface.**

**3. A fixture that stands in for the subject.** A projector-coverage
test built a materialization from a hand-written kwarg list and
asserted *that* covered the projector, so deleting a field from the
real producer left it green. Independently, the same day, a stage test
built its fixtures from a hand-written copy of the store's own
constant. *Tell:* the test constructs the thing it claims to be
checking.

**4. A checker weaker than its subject.** `ast.parse` accepts `return`
outside a function — that is a *compile*-time check, not a parse-time
one — so a syntax gate reported green on a file the service could not
import. `ts.createSourceFile` is error-tolerant by design: it returns
a degraded tree and files the problem on `parseDiagnostics`, which
nothing read, so negative controls asserting `toEqual([])` went green
on source that had not parsed at all. **A parser is not a compiler.**
Validate by importing, compiling, or reading the diagnostics.

**5. A check pinned to a name, not a behaviour.** A seal matched the
literal `derived_from_artifact_id=_artifact_bundle[`. Renaming that
local broke it with the data flow untouched. The inverse failure and
just as corrosive: **a check that fires on a change that does not
matter teaches everyone to edit the check.**

**6. A guard whose failure mode is silence.** A stage-balance check
computed faults from a list of emitted events, so an empty list
returned no faults — a path reporting *nothing* was indistinguishable
from one reporting a perfectly balanced pair. Seventeen mutations had
not found it, because every plausible single edit removes one event
and orphans its partner, which the check *does* catch. The
undetectable case needs a mutation nobody thinks to write.

**7. A control that neutralises the condition under test.** The most
dangerous, because the seal *actively defends the defect* and the
neighbouring tests make it look corroborated. `test_a_multi_arity_verb_does_not_ask`
passed `arity="set", bound={}` and required ROUTED — demanding that a
verb with a required, unfilled slot be dispatched with empty params,
which is exactly what failed live. Written as a control to prove the
arity flag was not stuck on, it removed the mandatory slot to isolate
the flag and pinned the wrong answer as expected. **Where a control
isolates one variable by neutralising another, check that the
neutralised one was not carrying the assertion.**

**8. A fixture that is uniformly empty.** `spoken_answer` was a
parameter `dispatch_pre_resolved` accepted and never read — one
occurrence in the file, in the signature. All thirty-four tests passed
`spoken_answer=""`. Not an odd-one-out to notice: *every* fixture
agreed with the bug. An unused parameter whose fixture is always empty
is invisible to any number of green tests.

**9. An assertion on a neighbour.** Tightening (7) to
`accepted_params == {}` *still* survived, because the ASK return never
populated that field — it was `{}` on every ask regardless. **Asserting
on a field the path does not fill is asserting on a neighbour.** See
[[assert-on-the-claim-not-its-neighbour]].

*And the reason the AUTHOR is worst placed to catch it (01, 2026-09-11).* A seal written for an
import fix asserted `defs is not None`. The fix had silently changed a public export — `from
iagent import defs` returned a **module** where it had returned a `Definitions` object — and a
module is not None, so the seal passed through the regression. It was written **twenty minutes
after its author recorded neighbour-assertion as their own most frequent defect**.

**The asymmetry is the finding: the author knows what they MEANT, so a green reads as
confirmation of the intent rather than of the assertion.** A reviewer has only the assertion, and
is therefore the better instrument for exactly this class. It is the strongest argument in this
file for source-of-truth review by someone who did not write the fix. *(Repaired by asserting the
TYPE, which goes red under the old code.)*

**AND THE PRACTICE THAT FOLLOWS, taken by the lane that reads every other lane's greens:
ASK FOR THE ASSERTION, NOT THE COLOUR.** A green confirms that *the assertion its author chose*
passed — not that the thing was done. To the reader the author's intent is invisible, which is
precisely what makes them the right instrument, and asking *"did your seal pass?"* throws that
advantage away. Ask what it asserts. 01's own framing, and a role change rather than a
resolution.

**10. A fixture that agrees with the bug.** `/artifacts/{id}` read `current_user.authz_id`
while the writer stamped `current_user.id`; **285 of one user's 286 artifacts were
permanently unreadable by their own producer.** Nine tests passed over it, because the test
fixture set `authz_id` and `id` to the SAME string. Not an empty fixture (shape 8) and not a
fixture standing in for the subject (shape 3) — a fixture that made two DIFFERENT things
indistinguishable, so the wrong one could not look wrong. *Tell:* two fields your code
chooses between are equal in the fixture. **Where the code picks between identifiers, the
fixture must make them differ.**

**11. A guard that exempts a case inherits that case's failure mode.** *(invincible-agent-5f,
2026-09-09.)* Their seal voided when a panel that SEEDED recorded no verb, and exempted
panels the seeder reported as failed — correct, because a failure in run A and a success in
run B is a genuine difference. It holds only while SOMETHING succeeded. Two total failures
became two empty sets scored as agreement, and the seal reported PASS in 2.48 seconds against
a fifty-minute run. The identical shape was one layer down in `/canvas/seed`, whose
partial-seed refusal returned 200 and therefore covered the zero-seed case too. *Tell:* an
exemption written to keep one case informative, with no assertion about the case where the
exemption is all that is left.

**12. A uniform extreme from a query whose population may not exist.** Five-of-five verbs
absent and sixteen-of-sixteen services unknown are the same reading. 5f's verb check queried
`(:Predicate)` NODES when verbs in that graph are RELATIONSHIP TYPES, and returned a
confident uniform NOT FOUND — one commit from filing "the template names five unregistered
verbs". *Defence:* put a FABRICATED member through the same code path and require it absent.
A uniform answer is only evidence once the instrument has been shown able to give a mixed one.

**13. A control that does not share its subject's gate.** *(invincible-agent-5f, 2026-09-09.)*
The control and the thing it controls must be reachable under the SAME conditions, or partial
availability silently buys back the vacuous pass. Two instances, one day, and they are different
mechanisms:

* *A skip.* 5f's verb check had ONE `can-say-no` control gated on Neo4j **and** Weaviate, while
  each assertion was gated on one store. Worker6 took Weaviate down — so the control SKIPPED and
  the Neo4j assertion PASSED. A green with no control behind it, in exactly the degraded state a
  control exists for. *Defence:* split the control per store so each shares its subject's gate.
* *A threshold.* 01's `test_the_fleet_can_be_pinned_to_one_commit` floored `len(out) >= 14` over
  a whole render where our images are 14 of 30 — so a render producing ours and ZERO foreign
  images cleared it, and the excluded-half test then passed over an empty set. A floor that
  cannot distinguish "all present" from "half missing" is not gating its own subject.
  *Defence:* each half floors itself.

The skip version hides when infrastructure is partly down, which is now the normal condition
rather than the exception. The threshold version hides always.


**14. An ABSENCE concluded from a search whose terms were guesses.** *(invincible-agent-5f,
2026-09-10.)* A grep that returns nothing has established that THE PATTERN DID NOT MATCH. Reading
it as "the thing is not there" is the same substitution as every entry above, with the instrument
reduced to one regex.

5f reported that 01's recorded reasoning was "genuinely NOT in the script, in HEAD or in
bf17651", twice, in writing, and a second lane acted on it. It was in `bf17651` at line 212. The
search used three terms and every one was a near-miss: `cannot execute` against *"cannot be
executed"*, `verify` against *"verified"*, and `derive` — case-sensitively — against *"DERIVING"*.
Three hits came back, all irrelevant, which read as a thorough search that found nothing rather
than as a wrong one.

**The conclusion was still half-right, and that is what made it dangerous:** the file genuinely
did lack the reasoning at that moment, because a `--theirs` merge had removed it. Right symptom,
wrong cause, and the wrong cause travelled further because the symptom checked out.

*Defence:* **before believing a negative search, make the same search find something you know is
there.** A positive control for a grep, exactly as `assert_checkers_can_say_no` is for a store —
and for the same reason: a query that has only ever returned nothing has not been shown able to
return anything. Cheaper still, search for a rare literal you can see with your own eyes in a
neighbouring line.

*And the companion, from the merge that caused it:* **additions are visible, removals are
invisible by construction.** Verifying a merge resolution by counting what the result ADDED — one
row, one map entry, the right totals — cannot see what it dropped, because nothing in the merged
file points at absent text. Diff against BOTH parents, not against expectations.

**AND THE GENERAL FORM, which took a second instance from a different mechanism to see: A CHECK
THAT LOOKS AT THE ENDPOINT CANNOT SEE WHAT HAPPENED IN BETWEEN.** *(01 + 5f, 2026-09-11.)*

| the check | endpoint it compares | what it cannot see |
|---|---|---|
| verifying a merge by counting what the result ADDED | the merged file | what the resolution DROPPED |
| `git status --porcelain` before and after a suite run | the working tree | a file mutated and then **restored exactly** |

The second is the one that shows it is not about diffs. A clean before/after supports *"the tree
ended where it started"* — **never** *"the run did not touch the tree."* Harmless for the run's
own result; **not harmless in a shared checkout**, where the restore may have written over a
neighbour's in-flight edit and left no evidence anything was overwritten. That is lane-to-lane
data loss a green gate reports nothing about.

*Disposal:* where the trajectory matters, **instrument the act, not the outcome** — or record the
bound and stop the claim at what the endpoint supports. Both instances above were caught by
someone saying out loud what their green did **not** cover.


## The one sentence that covers all fourteen

**"Whatever you mock, you have stopped testing."** — cortex-ui-60, 2026-09-09, after a
mutation survey found four mutations alive in a classifier whose test mocked the fetch
wholesale: it checked the LABELS and could not see the function with the defect in it.

It generalises past mocks, and that is why it belongs at the top of this list rather than in
it. **A mock, a fixture, a stub, a mirror of a helper, a hand-written kwarg list and a
scrape are all the same act: a decision about where the subject ends.** Every shape above is
that boundary landing on the wrong side of the defect —

  * shape 3 put a fixture where the subject was;
  * shape 4 put a permissive parser where a compiler was needed;
  * shape 7 put the isolation on the condition under test;
  * shape 8 put an empty value where the feature lived;
  * shape 9 put the assertion on a neighbouring field.

**THE MOCK BOUNDARY AND THE DEFECT BOUNDARY MUST BE ON THE SAME SIDE OF EACH OTHER, and
nothing tells you when they are not except a mutation that will not die.** The repair is
always the same direction: move the fake DOWN, toward the transport, and let the code you
are actually testing run. Faking `httpx.AsyncClient` instead of a `fetch_version` helper
turned four surviving mutations into five dead ones on the same classifier.

**And a collapse is a property about a SET, so it needs an assertion about the set.** Six
single-case tests can each pass against a classifier that returns one constant, if each case
happens to expect that constant. When the defect is "these two states became one", something
must require them to be DIFFERENT FROM ONE ANOTHER.

## The defences that actually worked

**Put a floor on anything whose empty case is silent** — a scrape, an
assertion, or a guard. A reader that reads too little fails OPEN, and
the empty case is the one no mutation covers. A run-producer scrape
read 4 labels instead of 19 because `routing_meta` is an *annotated*
assignment and the walk only handled `ast.Assign`; a `>= 15` floor
caught it. **Condition, from cortex-ui-60:** a floor is load-bearing
only where nothing else in the file already depends on the population
being non-empty — verify with one compound mutation (empty the walk
*and* delete the floor) rather than assuming it transfers.

**Compare at the last point where the defect can still exist.** The
lossy step must not be the comparison. Comparing *projected* records
could never see `classify_called` going int-instead-of-bool because
the projector does not surface it; comparing an offline transport
model could not see it either, because the model reproduced the
wrapper choice and not the wire encoding. (Corollary: **a bool IS an
int in Python** — any type-dispatch chain must test `bool` first.)

**Delete the copy instead of sealing the agreement.** An AST diff
asserting two producers emit the same labels is a copy with a seal on
it. It found three real dropped fields, and then one shared builder
made it unnecessary. Where a copy is genuinely irreducible, assert
ONE-WAY and classify the exceptions: every field is covered or
explicitly excluded *with a reason*, so a new one belongs to neither
set and fails.

**A guard may degrade quietly in production; its test may not.** A
check that cannot fail is no check. Do not write a seal that goes
inert when an internal name changes and call that honest degradation.

**TEST THE EDGE, NOT THE NODES** — cortex-ui-60, 2026-09-09, and it is the sharpest of these
because it explains why a WELL-tested codebase is the one it happens to. Their store and their
badge were each clean against ten mutations. Two further mutations deleted the CALLS
CONNECTING them — the publish on success and the publish on failure — and both survived. The
badge would have sat at "…" for the life of every session with the whole suite green and every
component individually correct.

Third instance in that repo alone: three of five interpreter call sites unthreaded, a section
mounted on the one branch that never renders, and a signal published by nobody. **Both
endpoints being individually verified is exactly the state in which a missing edge is
invisible, and it is the state good code is usually in.** When two units are each sealed, the
untested thing left is the wire between them.

**RUN THE MUTATION HARNESS ON A SCRATCH COPY, NEVER THE SHARED TREE.** Two ways it bites in a
multi-lane checkout: a peer staging during a run commits the mutant, and `Path.write_text` on
Windows re-emits CRLF for text read with universal newlines — so a "restored" file shows as
MODIFIED with a zero-line diff and no content change. Read and write BYTES, and build anchors
with the file's own line ending: an anchor that matches zero times prints identically to a
mutation that was killed, so a non-unique match must be fatal rather than reported.

**NAME WHAT THE NUMBER COUNTS — ITS UNIT AND ITS SCOPE — OR RECORD THE COMMAND INSTEAD.**
*(invincible-agent-5f + 01, 2026-09-11.)* A bare integer LOOKS like a measurement and carries no
way to check what it measured. That is what makes it dangerous rather than merely vague: it reads
as evidence and cannot be reproduced.

Both lanes quoted `program_id` counts at each other for three messages and agreed loudly about
different quantities. 5f said "26 occurrences" — it was 26 LINES in ONE FILE, because `grep -c`
counts matching lines. 01 said "53" — neither lines-clean nor occurrences, but lines summed across
a DIRECTORY with `.venv/` and `__pycache__` in it. Corrected and stated properly the two still
disagree (51/57 against 48/54), and **that disagreement only became visible once someone named the
unit and the scope.** Nobody was careless; the word "occurrences" was doing work neither number
supported.

*Defence:* state unit and scope at the point of quoting, or — better — **record the re-runnable
command rather than its answer**. A number is true at one commit and rots silently; a command
carries the population and moves with the tree.

**And the part worth more than the rule: THE RULE WAS ALREADY WRITTEN DOWN AND DID NOT HOLD.** 5f
had this in personal notes from 2026-08-28, including the exact mechanism — *"`grep -c` counts
FILES with matches when you count its rows, and MATCHES when you sum its values"* — and broke it
three times in one arc anyway. **A rule kept where only one agent reads it is a rule that binds
nobody at the moment of use.** That is why it is here, in the repo, beside the work — the same
argument this file makes for a comment that must be read to be obeyed.

*What survived the confusion, and why:* the ZERO. `program_id` is absent from the planning engine,
and zero has no unit problem — no lines, no occurrences, no scope, nothing vendored. The refusal
that rested on it was never at risk. **Prefer a claim that survives every way of counting.**

**A SUITE RUN MEASURES THE TREE AS IT STOOD FOR THE WHOLE RUN — SO DO NOT EDIT DURING ONE.**
*(01, 2026-09-11; not previously named here.)* A seal that spawns a subprocess importing a module
**from disk** reads whatever is on disk at the moment the subprocess starts, not what was there
when the run began. Break-on-purpose mutations applied to that file while the full suite ran in
the background were read by the suite's copy of the seal, and **the run reported a failure that
belonged to the editing rather than to the code. The run was invalid and it looked like a
result.**

Any seal that reads the tree rather than the imported module has this property. The disposal is
not cleverness, it is sequencing: **let a run finish, or start it again afterwards.** And when it
happens, **re-run clean rather than reasoning about which failures were yours** — reasoning about
it is supplying an explanation, which is the thing
[`a reason invented for a conclusion`](a-reason-invented-for-a-conclusion-fits-it-by-construction.md)
warns is free and fits.

**It has a sibling pointing the other way, and the pair is the general form.** Running a suite
here can *mutate* tracked files (a generator invoked by a positive control, a break-on-purpose
whose restore is byte-inexact). So: a run can change the tree, and changing the tree can invalidate
a run. **A measurement and its subject must not both be moving**, and in a shared checkout the
default is that both are.

**A GREEN BELONGS TO A SHA, NOT TO A DIRECTORY.** *(invincible-agent-5f + 01, 2026-09-09 — a
defect in how results are READ rather than how seals are written, and in a shared tree it is the
default rather than the exception.)* Before believing a local pass, `git status`; when reporting
one, name the commit it belongs to.

Both ends of it happened within one hour, on one file: 01 had a citation fix and its diagnosis
sitting UNCOMMITTED while running a seven-minute suite, and 5f ran the same seal in isolation,
saw it pass over 01's dirty tree, and was one sentence from reporting the seal clear on master.
The suite at `bf17651` said 2 failed. **The difference between your green and master's is
someone else's uncommitted work, and it reads exactly like your own.**

**And its companion, learned from getting it wrong in the same message: UNCOMMITTED WORK CARRIES
NO AUTHORSHIP.** 5f's warning named the wrong lane as the owner of those dirty files — not
carelessly, but by repeating an attribution received earlier, when the tree itself could not
have confirmed it. Git can tell you who wrote a *commit*; nothing in the tree tells you who
wrote an *edit*. So the honest report is *"there is an uncommitted change in these paths"*, with
no owner named unless someone claims it.


**Derive the population, never name it.** The one-line defence for
shapes 12 and 14 together, because they are the same reading: a
confident negative about a population you never established. Three
instances in one day, two of them mine and inside twenty minutes of
each other.

    MATCH (n:Predicate) RETURN count(n)   -> 0    no such LABEL exists in Neo4j
    grep 'cannot execute'                 -> 0    the text says "cannot be executed"
    GET /realms/iagent                    -> 404  the realm is called invincible-agent

Each looks exactly like the real negative it is not: an empty
registry, an absent rationale, a missing realm. **A zero from a label
that does not exist is indistinguishable from a zero from an empty
one**, and nothing in the result says which you got.

So the query is never the first step. `CALL db.labels()` before
`MATCH (n:X)`. `db.relationshipTypes()` before asserting a verb is
unregistered. And **before believing a negative search, make the same
search find something you know is there** — a positive control for a
grep, for the same reason `assert_checkers_can_say_no` is one for a
store.

**Scope the claim to what you measured.** Having established that
Neo4j holds verbs as relationship types, I wrote "never off a node
label" — and Weaviate *does* have a real `Predicate` class carrying
`verb_local` and `registration_complete`. Same word, two stores, two
kinds of object; a lane following the general form would have dropped
half of a conjunctive eligibility read. Asserting on the neighbour of
the thing you checked is the same defect one step out.

**Guarded by what the text CONTAINS, not by what the test NEEDS.**
invincible-agent-91, 2026-09-11, fixing six seals that failed rather
than voided on a missing optional dependency. Their first fix grepped
for `import duckdb` and guarded the three sites carrying that text.
**Three tests still failed** — they reach duckdb *through helpers*
(`datasets_agree` opens the database; `build_cost_dataset.build`
imports it inside the function) and never write the import.

**A grep is a sample of "files mentioning X". The population that
matters is "tests that NEED X", and the two differ by every level of
indirection.** Same law as deriving a population rather than naming
one, failing at the tool people reach for first because it is cheap.

**And only running the FAILING state reveals it.** In a clean checkout
the fixture voids before the import is reached — 97 passed, 59
skipped, nothing red, and the guard looks complete. The condition had
to be reproduced deliberately (dist file present, duckdb absent) to
see three seals still failing. **The state everyone runs by default is
the state that cannot discriminate.**

**And a derived population is only as complete as the thing it derives
FROM.** invincible-agent-5f's refinement, measured the same day the
rule was written. `_fleet_version_targets()` scans `ENGINE_*_PUBLIC_URL`
*precisely* so that nobody hand-maintains a fleet list — its own
docstring says a hardcoded list is "the shape this repo keeps paying
for". It is still incomplete: the chart sets no URL variable for
engine-lg at all, so the census printed a clean uniform table of
seventeen deployments with one service silently unaccounted for.

**An env var nobody set is invisible to a scan of env vars.** Deriving
moves the hole from the list to the SOURCE of the list; it does not
remove it. So the derivation needs its own floor — a count checked
against an independent enumeration (here: deployments in the
namespace, not variables in a ConfigMap) — for the same reason a
scrape does.

**A draft from outside the tree gets its NAMES wrong and its SHAPES
right — spend verification on identifiers, not arguments.** Measured on
the ADR-0051 draft: five names wrong, zero shapes wrong. The reasoning
a competent author brings from outside survives contact with the repo;
the file paths, symbol names, line numbers and IRIs do not, because
those are the part that cannot be derived from understanding. So the
review budget goes to the half that is cheap to check and likely
wrong, not to the half that is expensive to check and likely right.

Same family as the entries above, from the other side: a wrong
identifier produces a confident negative (a 404, a zero, an empty
grep) about a population that exists under another name.

**And weight it by who receives it.** The realm one went to the USER,
who has no instrument of their own to check it against. A fabricated
finding costs least when it lands on someone who can reproduce it, and
most when it lands on the one reader who cannot.

**A SEAL'S OBVIOUS REPAIR CAN BE THE HARMFUL ACT.** 2026-09-11, and it
is the only entry here where the green was not the danger — the FIX
was.

`test_citation_paths` went red on a dangling citation to
`docs/architecture/endpoint-gating-audit.md`. The obvious repair is
the only one the seal admits: make the cited file exist. I ran
`git add`, with the commit message already drafted asserting the file
belonged in the repo.

**Git refused.** `.gitignore:214` holds that path deliberately —
*"Held locally pending remediation (detailed findings) — publish as
record-of-fixes once the ungated endpoints are patched."* It is a
severity-ordered list of endpoints that are **ungated right now**,
with a CRITICAL secret-exposure section, in a **public** repo.
**Closing the seal would have published live vulnerabilities to fix a
documentation check.** An ignore rule written years earlier for an
unrelated purpose was the only thing in the path.

Three things make this its own shape rather than an instance of the
others:

* **The seal was RIGHT.** The citation really was dangling on master.
  No instrument failed, nothing was misread, and the red was earned.
* **The repair space had one obvious member and it was the wrong one.**
  A seal that admits only "make the file exist" cannot express "this
  file must never exist here", so the correct action was invisible
  from inside the check.
* **The guard that caught it was not the guard for this.** Nothing in
  the seal, the packet, or my own process knew the file was sensitive.
  Being saved by an unrelated rule is luck, and luck is not a control.

So: **before closing a red, ask what closing it costs.** A green is an
instrument reading, not a goal, and the cheapest way to make one
appear is frequently the most expensive thing you can do. Where a
seal's only expressible repair is the harmful one, the seal needs a
THIRD disposition — here, `WITHHELD_CITATIONS`, which says the file
exists, is deliberately out, and closing this is not your job.

Related and distinct: *a workaround erases its own question* is about
a fix that hides why the problem existed. This is about a fix that is
itself the damage, arrived at honestly, with the seal behaving
perfectly throughout.

## The rule that generalises past testing

**A substitute check that finds something is the most convincing wrong
check there is.** Asked for byte-equality of a direct-path artifact
against a run-produced one, this lane built an AST comparison of label
*names* instead, it found three real dropped fields, and the
substitution was never said out loud. A substitute that finds nothing
gets questioned; one that finds something reads as sufficient. When
the real seal was finally built it found two more defects the
substitute could not see.

**Name the substitution at the moment you make it, not when someone
asks again.** This is [[a-workaround-erases-its-own-question]] wearing
a green test: the document keeps reading as verified while its premise
was quietly swapped.

**And the same shape reaches PROVENANCE, not only checks: cite what the
trace actually IS rather than launder a relay into a source.**

A peer relayed a ruling — *"Engine B is retired, decided by the
architect"* — and this lane recorded it in ADR-0046 §8.4 as
`RULED … Decided by the architect`, with no source, then executed it.
The relay was faithful and the ruling was real. **The provenance was
unfindable**, and that cost a full stop-work: a later thread searched
git history, every ADR, every plan packet and every session log — the
right method — came back empty, correctly concluded nobody had ruled,
and challenged a retirement already carried out. Producing the source
took a scripted search across sixteen transcripts, and the search that
should have found it failed on a **date one day off**, because the
citation named the architect's "morning of 09-06" and not the
transcript's `2026-09-07T02:56Z` — the same moment, a timezone apart.

**A relay that turns out TRUE is the most convincing wrong provenance
there is**, exactly as a substitute check that finds something is the
most convincing wrong check. A relay that turns out false gets
challenged; one that is correct reads as sufficient, and nothing in the
document distinguishes it from a traced fact.

The fix is not to refuse relays — refusing would have stalled a lane
over a formality, and the ruling was genuine. It is to record the trace
as the kind of thing it is: **quote the sentence, name the transcript,
give the timestamp, and when two dates disagree cite both.** A citation
naming one of two disagreeing dates is what makes the next search come
back empty. A citation to a file that does not exist is worse than no
citation, because it looks checkable and fails silently — this lane
drafted one from a half-remembered filename and caught it before it
shipped.

**Corollary, one level up and earned the same week: a decision recorded
in a conversation does not correct a comment.** A row in a deploy
script carried a promise that the list was about to be derived; the
derivation was considered and declined, the reasoning existed only in
messages between sessions, and the file went on telling readers not to
maintain the thing in front of them. Sibling of
[[a-borrowed-name-is-a-claim]], and the special case
*uncommitted work carries no authorship* sits under it.

## And the thing none of it replaces

Over two days, seven instruments were green while something real was
broken. The two defects that reached a person — a pick dispatched with
no slot, and a typed answer silently dropped — were both found by
somebody clicking, against 478 passing tests.

That is not an argument against the tests. It is the argument for
**keeping the walk in the loop**, and for treating the first live
exercise of a path as part of shipping it rather than as confirmation
of something already shipped.

Related: [[seals-must-be-proven-to-bite]],
[[a-borrowed-name-is-a-claim]],
[[a-green-check-proves-only-its-scope]],
[[a-surviving-mutation-means-you-cannot-tell-yet]],
[[a-stub-that-needs-another-test-is-not-a-stub]],
[[check-from-the-consumers-side]].
