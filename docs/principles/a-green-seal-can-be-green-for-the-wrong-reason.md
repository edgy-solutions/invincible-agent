# Principle: a green seal can be green for the wrong reason

**Status:** Governing testing principle, and the companion to
[[seals-must-be-proven-to-bite]]. That one says a seal you have not
seen fail is a claim rather than a control. This one is about the
seals that *do* bite, that you *have* mutated, and that are still
answering a different question from the one in their docstring.

Assembled 2026-09-08 across two lanes — the direct-path work in
`invincible-agent` and the Electric/stage work in `cortex-ui` — from
nine instances found in two days. Every one was green, most had
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

## The one sentence that covers all nine

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
[[a-green-check-proves-only-its-scope]],
[[a-surviving-mutation-means-you-cannot-tell-yet]],
[[a-stub-that-needs-another-test-is-not-a-stub]],
[[check-from-the-consumers-side]].
