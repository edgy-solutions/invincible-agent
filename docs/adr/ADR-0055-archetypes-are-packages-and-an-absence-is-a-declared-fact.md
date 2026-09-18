# ADR-0055 — Archetypes are packages, and an absence is a declared fact

> **An absence is rendered as a declared fact and is assertable from outside.**

That sentence is the contract, and it was **found by measuring the four existing cards rather than
proposed** — see §1, which is also this ADR's most useful section, because the list it replaces was
wrong.

**Status:** **ACCEPTED 2026-09-18**, after review against the code by `cortex-ui-60` — reviewer
assigned by the architect, not by this document. They supplied §1's measurement, refused one claim
of the original packet (which is §4's boundary), and their review produced four findings folded
before ratification, **one of which made the ADR true rather than merely better**: §5's parity seal
pointed at fixtures that do not exist. **Extraction and registration only — no card changes
appearance, and the parity seal is what makes that checkable rather than promised, once step 1 has
produced fixtures for it to run.**
**Date:** 2026-09-18
**Deciders:** Architect (the fork in §4, the reviewer assignment, the OpenUI reading), Platform team
**Related — cited `repo:ADR-NNNN`, per the 2026-09-16 convention:**
  - [`docs/runbooks/adding-an-archetype.md`](../runbooks/adding-an-archetype.md) — the six sites
    this ADR turns into one package plus one row.
  - [`iagent:ADR-0054`](ADR-0054-data-classes-every-write-declares-what-it-is.md) §2 — declaration
    per store, and the shapes-are-not-the-schema rule. §3's row is that pattern at the presentation
    layer.
  - [`docs/rulings/README.md`](../rulings/README.md) — **R-075** (*if a message string enumerates
    anything, the enumeration is a field*) and **R-076** (*a producer can do the right thing,
    document it, and the consumer is never written*). §2's contract is R-075 generalised from a
    message to a card, and §5's mirror is what keeps R-076 from happening to a contributed package.
  - [`principles/a-search-by-name-finds-prose-about-the-name.md`](../principles/a-search-by-name-finds-prose-about-the-name.md)
    — §1's inversion is that law's sibling: a list checked against the names you expect returns your
    expectation.

---

## Context — the funnel is a person, and the sites are why

`adding-an-archetype.md` names six sites for one archetype, spread across two repos. Every one is
an edit, none is an addition, and the result is that **a contribution cannot be made by anyone who
does not already know all six.** The bottleneck is not review capacity; it is that the work has no
shape a contributor can hand over.

The backend half shows it plainly. `agent_fleet/presentation_agent/main.py:474`:

```python
#: output_uri -> (archetype, payload key, extra passthrough fields)
```

**A tuple table, hand-kept**, and the defect it has already produced is on the record: four
passthrough tuples predating the verdict field, each correct when written. That is
`iagent:ADR-0054`'s subject at the presentation layer — **a population maintained rather than
derived** — and the fix is the same one: a declared row per archetype, read rather than edited.

## 1. THE CONTRACT WAS MEASURED, AND THE MEASUREMENT INVERTED THE PROPOSAL

**This section is first because it is the finding.** The packet that opened this work named four
shared "honesty primitives" to lift into a library: a three-state verdict, `UnreadFields`, a *no
direction stated* legend, a disclosure strip. `cortex-ui-60` counted them in the code:

| proposed primitive | present in |
|---|---|
| three-state verdict (favourable/adverse) | **1 of 4** — `ContributionRanking` only |
| "no direction stated" legend | **2 of 4** |
| disclosure strip | **1 of 4** — `AttemptFailed`, added 2026-09-15 |
| `UnreadFields` | **0 of 4** |

**On that list this was an INVENTION dressed as an extraction**, and the ADR would have imposed a
shared contract on cards that never had one while citing four instances it did not have.

**`UnreadFields` was a category error and is worth naming separately.** It is not a card feature
and no card implements it: it is a single HUD panel, mounted once in detailed mode, that reads
**every** component on an artifact and reports keys no archetype declared. **A library cannot lift
from the cards what was never in them.** It is an artifact-level instrument that sits *beside* the
library — see §4.

### What the four actually share, derived rather than checked

Every one of the four emits **named, machine-readable attributes for what it could not say**:

    ContributionRanking   data-no-verdict · data-legend-unjudged · data-legend-partial
    AskCard               data-free-text-reason · data-pick-refused · data-ask-abstained
    CompetingMeasures     data-refused · data-unavailable · data-incomplete · data-spread-unreported
    AttemptFailed         data-failure-untraced · data-flag-standing · data-route-status

> **AN ABSENCE IS RENDERED AS A DECLARED FACT AND IS ASSERTABLE FROM OUTSIDE.** Each card names the
> specific thing it could not do, **in its own vocabulary**, on a surface a test can read.

**AND THE PRIMITIVE IS ALREADY MORE GENERAL THAN THE FOUR, WHICH IS BETTER EVIDENCE THAN THE FOUR
WERE.** `InterpretationStrip` — **not an archetype card** — emits `data-slot-refused`,
`data-refused-reason` and `data-slot-outcome`. So "every one of the four" *understates* the
population: the primitive is present on a surface outside the set, which is what a thing **found**
looks like rather than a thing **imposed**.

It also forecloses a reading a later maintainer would otherwise reach: **the primitive does not
originate with archetype cards.** §4 scopes where the LIBRARY applies; it does not scope where the
primitive lives, and those are different claims.

**That is an extraction with four instances, and it is a stronger contract than the list it
replaces** — because it constrains what a contributor must **declare** rather than what they must
**render**. A card that invents its own absence vocabulary still satisfies it; a card that draws a
confident thing over a missing input does not, whatever primitives it composed.

**The three-state verdict is a SPECIALISATION of it that one card needed.** So the packet's four
primitives are not discarded: they become **optional specialisations a package composes when its
archetype needs them**, and only the declared-absence mechanism is mandatory.

### The method note — why a COUNT could not have caught the worst item

`UnreadFields` scored **0 of 4**, and a zero in that table reads as **"rare"**. The truth was
**"not that kind of thing"** — a HUD panel over the whole artifact, which no card could implement
and therefore no card was ever going to score on.

> **A COUNT CANNOT DISTINGUISH *RARE* FROM *NOT THAT KIND OF THING*.** Only asking what the thing
> IS can, and that requires the code open.

**That is the whole argument for gating this draft on a measurement rather than on a review
afterwards.** A reviewer scoring the drafted list would have produced the same `0 of 4` and the
same wrong reading — the item would have survived review by being *counted*. The reviewer's own
framing, and it is the sharpest thing to come out of this exchange.

**AND THE INVERSION IS ITSELF THE FINDING, WHICH IS WHY IT IS RECORDED RATHER THAN QUIETLY
CORRECTED.** The list came from a packet's expectation; the code said otherwise; and a list checked
against the names you expect returns your expectation. This ADR would have shipped four citations
that did not exist had the measurement been skipped — and the measurement was made a precondition
of drafting precisely because the packet could not know its own answer.

## 2. Decision — an archetype is a package

One directory per archetype, both halves in it:

| file | what it is |
|---|---|
| `contract.ts` | the typed payload the card reads, and its validator — `ok` or `refused` |
| `Card.tsx` | the component |
| `fixtures/` | **at least one DISCRIMINATING fixture** — see §5, and **see the measurement below: these do not exist yet** |
| a row in `policy/archetypes/<id>.yaml` | the backend half, declared rather than edited |

**The library provides the declared-absence mechanism** — the way a card names what it could not
say, and the way a test reads it. **It does not provide the vocabulary**: `data-spread-unreported`
is `CompetingMeasures`' word for its own gap and no library could have guessed it. The mechanism is
shared; the words are the package's.

> ⛔ **"THE WORDS ARE THE PACKAGE'S" IS AN ASPIRATION UNTIL A COLLISION RULE MAKES IT TRUE.**
> `data-refused` is emitted by **both** `CompetingMeasures.tsx` and `InterpretationStrip.tsx`
> today. Nothing prevents two packages choosing one word, and **a seal asserting `data-refused`
> matches either surface** — so the declared-absence seal would be satisfiable by somebody else's
> absence, which is a green that means nothing.
>
> **The contract carries a collision rule: the assertion is SCOPED TO THE CARD's subtree**, not to
> the document. Namespacing the attribute per archetype is the alternative and is worse — it makes
> the vocabulary the library's after all, which is the thing §2 just said it is not.

### `fixtures/` DOES NOT EXIST TODAY, and the sequence has to build it

**Measured 2026-09-18: there is not one `fixtures/` directory anywhere in cortex-ui.** Payloads
live as **inline literals inside test files**.

**This is the same category as §3's row and it gets the same sentence, because the consequence here
is larger.** §5's parity seal is written as though it *"runs the EXISTING fixtures through the new
card"*, and §6 lists *"the fixture discriminates"* as a seal — **both read as pointing at an
artifact, and the artifact has to be extracted from inline literals first.** A safety argument
resting on something that does not exist is not a weaker argument; it is not yet an argument.

**So the extraction of fixtures is a step in §8's sequence rather than an assumption of §5**, and
until it lands `replaces` has no parity seal to run. Said here rather than left for whoever
discovers it while writing the first replacement.

**Registration is one call and the registry is DERIVED.** `defineArchetype({ id, contract, Card })`
in the package; the registry is the list of packages, **never a hand-kept array**.
`DERIVED_BINDINGS` and `PRESENTATION_CAPABILITIES` are read from the rows, so **the mirror seal
covers a contributed archetype the day it lands** rather than the day someone remembers to add it.

An engine author writes exactly one thing: **a `rendersAs` row binding an output class to an
archetype id.** If the id is not registered, Contract D's unrenderable check refuses **at
registration**, not at the card.

## 3. `policy/archetypes/<id>.yaml` — the row, and it is new

**Measured 2026-09-18: `policy/archetypes/` does not exist.** This is an addition, not a move, and
saying so matters because "make it a row" reads as relocation.

The row carries what the tuple at `main.py:474` carries — archetype, payload key, passthrough
fields — as **data the presentation agent reads**. That is `iagent:ADR-0054` §2's declaration-per
-store at this layer.

**"BY CONSTRUCTION" MEANS THE TUPLE TABLE IS REPLACED, NOT PARALLELED, and the distinction is the
whole of it.** A row per archetype *beside* a surviving tuple table closes nothing: the next
archetype is added with a tuple and no row, exactly as the last four were, and the ADR would have
bought a second place to maintain the same fact. So:

* the passthrough is **read from the rows**, and there is **no tuple to add**;
* a field a card reads that no row declares is a **red**, not a review comment;
* **and a seal asserts the tuple table is gone** rather than assuming it — because "we removed it"
  is a claim about a moment and the seal is a claim about every commit after it.

Without that third point the first two are a convention, and this ADR exists because a convention
is what the six sites already were.

## 4. THE BOUNDARY — this library is for PAYLOAD-BOUND components only

**Ruled 2026-09-18, on `cortex-ui-60`'s refusal of the original claim.** The packet wanted the ADR
to say `replaces` is safe *because the contract makes it safe* — same typed payload, same
primitives, existing fixtures through the new card.

**That holds for three of the four. It does not hold for `AttemptFailed`**, which has **no contract
file, no validator, and no payload at all**: it reads `artifact.status`, `artifact.routing` and
`artifact.resolved_intent` through `lib/routing.ts`. Its fixtures are **artifacts**, not payloads.
It is not a payload renderer; it is an **artifact-level surface** that happened to be in the set of
four.

> **So the library is scoped to payload-bound components, and `AttemptFailed` is NOT an instance of
> it.** The first extraction is **three** packages, not four.

`UnreadFields` is the same category — an artifact-level instrument — and sits beside the library
for the same reason.

**WHY NOT A SECOND SAFETY ARGUMENT NOW.** Covering both kinds would be **one sentence doing two
jobs**, which is exactly what was refused. If a second artifact-level surface ever appears, that is
the day a second and smaller class gets written — **with a case, not in advance**. Both worked cases
in `iagent:ADR-0054` were found by a case rather than by reading the rules, and this ADR declines to
invent the rule before the second instance exists.

## 5. Augment, replace, and select — the three things a contributor does

**AUGMENT is the default and needs no extra declaration.** A new id, a new contract, a new card. An
engine binds to it with a `rendersAs` row and it draws. Nothing existing changes; the mirror seal
gains one row on each side.

**REPLACE is the same package with `replaces: <id>`** — a second implementation of an existing
contract. **The contract is what makes replacement safe**, and now that is a scoped claim: the
contributed card satisfies the same typed payload and the same declared-absence mechanism, and
**the parity seal runs the archetype's fixtures through the new card.**

> **AND `replaces` IS NOT AVAILABLE UNTIL THOSE FIXTURES EXIST** (§2). The mechanism is specified
> here; the artifact it depends on is step 1 of §8. A replacement accepted before then would be
> accepted on a reading rather than on a parity run. Pass, and the registry resolves
the id to the replacement — every `rendersAs` row naming that archetype draws the new card and **no
engine knows**. Fail, and the replacement is refused by name while the original keeps drawing.

Two things a replacement cannot do, and the library refuses both:

* **Change the contract.** A card needing a field the contract does not carry is a **new archetype,
  not a replacement** — the payload would not have it.
* **Skip the mechanism.** A card that draws over a missing input without declaring the absence
  fails the contract's own seal. That is the rule enforced rather than reviewed.

**SELECTION IS A RAIL ROW, NOT LOAD ORDER.** When two packages satisfy one contract, a row in
`policy/archetypes/` names the active implementation **per deployment** — seed plus overlay, like
everything else. Last-registered-wins is `latest` again, and this fleet has already paid for that.

`cortex-ui-60` confirmed from the component side that **nothing in the four resolves a renderer by
load order** — selection reaches a card already made, as an archetype string. So the rail row
changes **who decides**, not how the card is reached, which is what makes it a small change rather
than a rewiring.

## 6. The seals are the funnel

A contribution that passes these does not need the maintainer to look at it; one that does not gets
**a named refusal instead of a review comment.**

| seal | what it refuses |
|---|---|
| contract validates against the row | a card reading a field the row does not declare |
| **no passthrough tuple survives** | an archetype added the old way — the row is the only door, asserted rather than assumed |
| **the fixture discriminates** | a fixture that cannot fail — the decorative-seal problem, and the reason "at least one" is not enough on its own |
| the mirror holds both directions | R-076: a producer doing the right thing with no consumer written |
| declared-absence assertable | a card that draws over a gap without naming it |
| parity, for a `replaces` | a replacement that changes behaviour while claiming not to |

### TWO OF THESE SEALS SPAN TWO REPOSITORIES, and that is a different kind of seal

**"Contract validates against the row" and the mirror both cross a repo boundary** — the contract
is in cortex-ui, the row is in `policy/archetypes/` here. **A cross-repo seal specified without the
following will be written, pass, and mean nothing**, and each item below was found by a failure
rather than by design:

* **It cannot run inside `docker build`.** A seal needing a second repository has to move to the
  job, not the image build.
* **The producer is checked out at a PINNED sha**, or a red is **unattributable** — nobody can tell
  whether the consumer moved or the producer did.
* **There is a no-skip floor**, or a missing checkout reports as a **PASS**. This is the
  skipping-reads-as-passing shape at a repo boundary.
* **The resolved sha is ASSERTED**, not merely available. A baseline that appears only in a failure
  message means a green run says nothing about which producer it measured.

**Where these run and what they pin is part of the sequence, not an implementation detail** — and
the four are carried here because they were paid for, twice by the reviewer's own hand.

**The first three packages are the proof, and the parity seal is what makes "no visual change" a
measurement rather than a promise — once §8 step 1 has produced fixtures for it to run.**

## 7. Rejected alternative — OpenUI, cited with its reader

**Read by the architect, README at `github.com/thesysdev/openui`, 2026-09-18.** A component library
generates a **system prompt**; the model emits **OpenUI Lang as a stream**; a React renderer draws
it. **Its extension point is what the MODEL MAY EMIT** — not what a declared payload may bind to.

Adopting its registry would couple this system to their runtime **and to their reason**, which is a
different problem from the one here: this fleet's cards are drawn by deterministic passthrough from
a declared payload, and the thing being extended is the payload contract.

**It stays a candidate RENDERER for the prose-shaped archetypes, later** — once the library exists,
adopting it is one `Card.tsx` behind a contract, which is the only way to take someone's runtime
without taking their reasons.

> **THE READER IS NAMED BECAUSE A REJECTED ALTERNATIVE DESCRIBED WRONGLY IS WORSE THAN ONE NOT
> NAMED.** The reviewer declined to endorse this characterisation on the grounds that they had not
> read it — *"saying 'that sounds right' about a rejected alternative I have not examined is how a
> citation acquires a confidence nobody earned."* They were right, and the citation carries the
> reader and the date instead.

## 8. Sequence — proposed here, ASSIGNED ELSEWHERE

**This ADR proposes an order. It assigns nobody**, and the first draft did — it named its own
reviewer as the owner of step 1. **A document cannot assign work to its own reviewer**, and who
does each step is the architect's to say, the same way the reviewer role was.

> **ASSIGNED 2026-09-18 BY THE ARCHITECT, recorded here because the assignment is theirs and the
> record is this document's:** `cortex-ui-60` owns **step 1**, the fixtures extraction, and the
> sequence after it as proposed below. **That sentence is a record of a decision made elsewhere,
> not the document making one** — and the distinction is the reason the first draft's version of
> it was wrong.

1. **Extract the fixtures** from the inline literals in the test files, per §2's measurement. This
   is step one because §5's parity seal and §6's discrimination check both depend on it, and
   neither is available until it lands.
2. **Extract the library** from `CONTRIBUTION_RANKING`, `ELICITATION` and `COMPETING_MEASURES` —
   **three packages, not four** (§4). **Zero visual change, with the parity seal as the proof.**
3. **Stand up the cross-repo seals** with their pin, their floor and their asserted sha (§6),
   because a contributed package's gate is a cross-repo gate from its first day.
4. **Build `BRIEF` as the first NEW package through the extension point** — the first evidence the
   extension point is usable by someone who did not build it.
5. **Write the contributor runbook FROM that build**, the way `adding-an-engine.md` was written
   from engine-docs and then used to build the next one.
6. **The first team outside this one ships the next package.** That is the measurement that
   matters, and until it happens the funnel has moved rather than opened.

## Non-goals

- **Not an artifact-level surface class** (§4) — that wakes on a second instance.
- **Not a change to how a card is reached.** Selection already arrives as an archetype string.
- **Not a renderer choice** (§7).
- **Not a re-layout.** Zero visual change is the seal, not an aspiration.

## Indicators we got this wrong

- **A contributed package needs a maintainer edit outside its own directory.** §2 failed; the six
  sites became five and a package.
- **A `replaces` lands and a card's behaviour changed.** The parity seal was not discriminating —
  which is the fixture problem, not the seal's.
- **Two packages satisfy one contract and the active one depends on import order.** §5's rail row
  is not being read.
- **An archetype declares an absence nobody asserts.** The mechanism became decoration, which is
  R-076 arriving inside the library this ADR wrote to prevent it.
