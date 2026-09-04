# The a-green-check-proves-only-its-scope law

> **The question to ask of a new guard is not "does it pass?" but "what is outside its scope,
> and how would I know?"**

A check reports green over everything it does not look at, and it reports it *in the voice of a
passing test* — which is worse than no check, because the output is evidence-shaped. The first
question has an answer everyone collects; the second is the one that decides whether the answer
means anything.

## Two sub-species, and the remedies diverge

Distinguishing them matters, because the fix for one makes the other worse.

**EXCLUDED POPULATION** — the check never looks at where the failure lives. Widening the scope is
the repair.

**INCLUDED NON-POPULATION** — the check looks at something that is not the thing: it cannot tell
a *use* from a *mention*. Widening makes this worse; the repair is a way to mark the mention.

**DERIVED SCAN, REMEMBERED POPULATION** — the check walks everything (its scope is genuinely
derived) and still misses members, because its EXTRACTOR only understands some of the forms the
subject is written in. Widening the scan does nothing; the scan was already total. The repair is
to derive the *population* from the authoritative enumeration and to check non-vacuity **per
member**.

> **DERIVING THE SCAN IS NOT DERIVING THE POPULATION.** (Lane 1's formulation, 2026-09-03,
> after hitting it three times in one night in three unrelated enforcement mechanisms.)

**AND THE PART THAT MAKES THIS SPECIES HARD: AN AGGREGATE NON-VACUITY CHECK CANNOT SEE IT.**
The response-shape seal below carried exactly the guard this document asks for — *"a seal that
measures nothing passes trivially"*, asserting `len(inputs) >= 10` — and it passed while
harvesting **zero** URIs from three engines, because the engines it *did* understand cleared the
floor on their own. A population floor proves the scan is not dead. It says nothing about who is
missing. **Assert per member, against a list derived from somewhere else** — the fleet's own
enumeration, not the scanner's output.

## The instances


Nine, from one project. Three arrived on a single day, authored by the agent that had just
written the rule about the others; four more arrived on one night, across three unrelated
enforcement mechanisms and two lanes, and **not one of them shared any code with another** —
which is the argument for this being a law rather than a bug that keeps recurring in one file.

| the guard | what its scope excluded — or wrongly included | how it surfaced |
|---|---|---|
| `legacy-dns-guard-phantom-scope` | `SCANNED_DIRS` named a **sibling repo, not a subdirectory**, so the walker skipped it silently | the forbidden pattern was live in the unscanned tree the whole time the guard was green |
| *"the citation baseline is clean"* (`0d1dae7`) | verified over `docs/plans/` paths; the phantoms lived elsewhere under `docs/` | the claim was published in a commit message, then falsified minutes later by a broader check |
| the first citation seal (`db4eed4`) | matched **absolute** `docs/…` strings; the breakage was in **relative** link targets | four links broke in the same commit and the seal stayed green through all of them |
| the second citation seal, immediately | included prose **quoting** a link shape as though it were a link — *mention read as use* | it flagged its own documentation |
| the dagster stub (`tests/routing/test_adr0019_contracts.py`, fixed `2da0d76`) | hand-wrote ~18 attributes; `src/iagent` imports **30** distinct dagster names. **REMEMBERED POPULATION** | green proved the stub had been **SKIPPED**, not that it was complete — `_install_stubs` no-ops when real dagster is already in `sys.modules`, so which name bit depended on collection order |
| the same stub's `MetadataValue`, one level down | the NAMES had just been derived; the ATTRIBUTES inside them were still remembered (`text`, `json`, no `.md()`) | **the first defect masked the second**, so closing it looked like a regression for a minute |
| the response-shape seal (`d9d584c`) | walked every file — scan fully derived — but the resolver understood only two construction forms, so **engine-cost, engine-fin and engine-p contributed ZERO URIs** to a seal asserting over "every registered output" | its own non-vacuity floor (`>= 10`) passed, because the two understood engines cleared it alone |
| the reregister seal's `_KEY_TO_AGENT_DIR` (fixed `81cd4f4`) | a hand-kept dict that **stopped at Engine P**, so engine-fin went five days unexamined; and the seal enumerated CALLERS, so an engine calling the helper **zero** times was not in the population at all | engine-cost shipped for a commit deployed, health-green and registering nothing — Engine B's shape — while this seal was green throughout |
| the definition guard (`a0fb983`, fixed in `434bf08`) | `_definitions()` collected only `rdfs:comment`; the embedder reads `{skos:definition}` **UNION** `{rdfs:comment}`, so half the population was never in scope | **the fix it was measuring removed the predicate it read** — de-clobbering moved build notes to `#` comments, the four files it had just certified went to *zero definitions visible*, and every debt entry read "CLEANED" |

**The fifth is the cleanest specimen of the excluded-population species, because the exclusion
was CREATED BY THE REPAIR THE GUARD WAS WATCHING.** The guard was written when every class
carried an `rdfs:comment`, so reading that one predicate covered the whole population and the
scope gap was invisible. Then the subject changed shape — the correct fix moved build notes out
of `rdfs:comment` — and the guard's population silently emptied. It did not report zero; it
reported *clean*.

That is the failure this law exists for, with an extra turn: **the scope was correct when written
and became wrong without the guard being touched.** A guard's scope is not a property of the
guard alone; it is a relationship between the guard and a subject that moves. Which means
"proven to bite" and "scope stated" are both insufficient on their own — this guard had a stated
scope and was later given a break-on-purpose, and neither would have caught a population that
drained away underneath it. The only thing that did was counting what it inspected:

    before   44 texts across 5 files   (4 extension files invisible)
    after    56 texts across 9 files

**Corollary worth its own line: a guard should report its population size, not just its verdict.**
A green with `n` visible is falsifiable at a glance; a bare green is not. Every instance in this
table would have been caught in seconds by a number next to the checkmark.

## The sharpest fact, because it retires the obvious objection

**The third instance had been proven to bite.** Break-on-purpose was performed exactly as
[[seals-must-be-proven-to-bite]] requires: a cited file was renamed, the seal went red, and it
named `ADR-0029:157` as the citing site. That is a correct, diagnostic, non-ceremonial failure.

**And at that same moment the seal was blind to four other broken citations in the same commit** —
because `docs/plans/archive/` sits one level deeper than `docs/plans/`, so every `](../adr/…)`
target out of a moved file needed re-basing, and a check matching absolute paths structurally
cannot see a relative one.

So *proven-to-bite* is necessary and **not** sufficient. Mutation testing verifies the guard fires
when the property is false **inside its scope**; it says nothing whatever about the property being
false outside it. A seal can be simultaneously well-built, correctly diagnostic, demonstrably
non-ceremonial, and blind.

**And the near-miss is the part to keep.** `docs/reference/` sits at the *same* depth as
`docs/plans/`, so its 16 moves broke nothing. Spot-checking that tranche would have found nothing
wrong and read as confirmation — a sample drawn entirely from outside the failing population,
returning a clean result that means nothing. The reassurance would have been real and worthless.

## Where this sits among its siblings

- [[naming-a-class-is-not-a-guard]] — *a written **rule** does not protect you; only a guard does.*
- [[seals-must-be-proven-to-bite]] — *a guard that has only ever passed is a claim; make the
  property false and watch it go red.*
- **This law** — *a guard that has been proven to bite still only covers its scope.*

Three steps of the same staircase, and the third is the one with no natural stopping signal: a
missing guard is visible, an unproven guard is a to-do, but a **passing** guard actively
discourages the question. Nobody interrogates a green check.

## What follows

When adding or reviewing a guard, answer both halves in writing:

1. **What population does this walk?** Name it as a set — directories, file extensions, path
   shapes, call sites — not as an intention. `legacy-dns-guard-phantom-scope` failed because
   `SCANNED_DIRS` *read* like it covered doc-tools.
2. **What is adjacent to that set and excluded?** The near-neighbours are where the failure goes.
   For a path check: the other path shape. For a directory walk: the sibling tree. For a code
   scan: the generated mirror — `baml_client/inlinedbaml.py` nearly carried a dead citation
   through because "it's generated" felt like a reason to skip it.
3. **How would I learn the excluded part broke?** If the answer is *"someone would notice"*, the
   scope is the guard's real specification and it is undocumented.
4. **Can it tell a use from a mention?** Only for guards that scan prose, code comments, or
   anything quoting its own subject matter. If not, define the escape mark *before* the first
   false positive, or the guard will be weakened under pressure rather than fixed.

**Corollary — a passing sample from outside the failing population is not evidence.** Before
citing a spot-check as confirmation, state which population it was drawn from and whether that
population could have exhibited the defect.

## What this does not license

**Not "every guard must be total."** Total scope is usually unavailable and often not worth
buying; the four instances above are not arguments for one enormous check. Two of these guards are
correct as scoped, and the honest form of the second citation seal is *two* checks with stated,
complementary scopes rather than one that claims everything.

**The rule is: state the scope where the guard lives, and state what is outside it.** An exclusion
that is written down is a known property of the design. An exclusion that is merely true is the
next instance, already scheduled — which is exactly what
[[naming-a-class-is-not-a-guard]] says about unguarded classes, one level up.
