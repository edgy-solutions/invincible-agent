# ADR-0048 — The customer-validation package: first consumer of computation export

**Status:** Proposed (2026-09-02). **Not started.** Slice 1 is a notional-data proof (§6); no real
recipient data enters this path until it passes.
**Date:** 2026-09-02
**Deciders:** Architect
**Related:**
  - [ADR-0047](ADR-0047-computation-export-governed-emit-carrying-its-own-algorithm.md) — **the
    platform rule this instantiates.** Every constraint below that begins *"per §n"* is that
    document's, not this one's. **Where the line falls:** ADR-0047 rules what any computation export
    is allowed to be; this ADR rules what *this recipient's* package is. If a ruling here would
    apply equally to a second, unrelated recipient, it is in the wrong document.
  - [ADR-0024 Part B](ADR-0024-standards-composition-bpmn-calm-odps-odcs.md) — publish discipline,
    and the sequencing STOP raised at ADR-0047 §7 and **ruled 2026-09-02: it binds tool targets
    only.** What survives of it gates §6's graph-node work — which must land graph-native rather
    than as a side-store — **and nothing else here.**
  - [ADR-0046](ADR-0046-langgraph-graphs-as-registered-mesh-verbs.md) — the admission grammar the
    packaging verb passes through.

**The exported capability** is **a per-category cost-estimation tool with a deterministic pricing
engine and rate/escalation management**. Nothing architectural depends on what it prices — every
ruling turns on the computation being *deterministic* and *importable standalone*.

> **AMENDED 2026-09-02.** This originally read *"already Python"* and carried a naming fence,
> because the plan was to wrap an existing external tool. **There is no such tool in this workspace**,
> so the capability is **built to specification** as `engine-cost`
> ([`register-cost-tool-as-engine`](../plans/register-cost-tool-as-engine.md)) with exportability as
> a construction constraint. **The measurements in §3 are unaffected** — bundle size, boot time and
> numeric-stack fidelity are properties of the runtime and the data, not of the module's origin.

---

## §1 — The requirement, stated honestly

**The predecessor practice was to ship the tool itself.** The customer received it whole, ran it in
their own building, and validated the claims independently — no call, no login, no request. That
property is what made the numbers credible to them, and it is the requirement being preserved.

**What the customer is buying is not a report. It is the ability to disagree with one, in detail,
without asking.** A number they can only see is a number they must trust; a number they can
re-derive is a number they can check. The offer is stronger and so is the disclosure — the algorithm
leaves the building with the data, which is why ADR-0047 exists.

### The portal alternative: recorded and DEFERRED, not refused

A hosted portal — the customer logs in, sees current figures, drills down — is the obvious modern
alternative and it is **deferred rather than rejected**, because it answers a *different question*:

| | the package answers | the portal answers |
|---|---|---|
| question | *can I verify this without you?* | *is this current?* |
| network | none | required |
| identity surface | none — a file | **external identity: accounts, sessions, credential lifecycle, an internet-facing authenticated surface** |
| what the customer holds | the computation | a view of yours |

**Sequencing: export first, portal as the later upgrade, and the reason is not preference.** The
package has *no external identity surface at all* — the disclosure decision is made once, at
packaging, by an entitled caller (ADR-0047 §5), and the artifact is inert thereafter. A portal
requires standing up external authentication, session management and per-request authorization for
users outside the organisation — a substantial and permanently-live security surface. **Building the
inert artifact first also produces the thing the portal would need anyway** (recipient scoping, the
audit line, the pinned computation), so the order is cheapest-first *and* it defers the largest
security commitment until something is proven valuable enough to justify it.

**The portal is not refused**, and this ADR should not be cited to refuse it. When "is this current"
becomes the customer's actual question, it is the right build.

---

## §2 — The concrete shape — TWO formats, one emit

**RULED 2026-09-02: both the HTML package and the notebook are built** (ADR-0047 §8.1), because they
answer different recipient questions and a single customer routinely has both people:

| | **HTML package** | **notebook** |
|---|---|---|
| the question it answers | ***"can I CHECK this?"*** | ***"can I SEE this?"*** |
| typical recipient | a contracting officer | that recipient's cost analyst |
| intermediates | verified, not displayed | **cells** — the arithmetic walked step by step |
| editing the computation | not possible | **possible, and it is the point** |
| `target_system` | `recipient-html` | `recipient-notebook` |

**One governed emit, two output targets.** The pinned modules, the recipient-scoped data, the
verification manifest and the audit line are format-independent; `format` is a declared enum slot on
the one packaging verb (ADR-0047 §1). **Two rows, not two designs.**

### The HTML package

- **A single self-contained HTML file.** One artifact, opens by double-click, survives being emailed
  and copied to a share. No installer, no environment, no instructions beyond "open it".
- **A Python-in-browser runtime**, because ADR-0047 §3 forbids a port. The real modules run.
- **The real computation modules, pinned by commit SHA** — the pricing engine and its rate and
  escalation handling, exactly as the engine runs them.
- **Recipient-scoped data, embedded, PRE-CLEANED AT PACKAGING TIME.** The bundle carries the
  computation's *inputs*, not the pipeline that produced them. **No spreadsheet parsing, no source
  ingestion, no cleaning code in the bundle** — that machinery is fragile, is not what the recipient
  is verifying, and would put a second data-preparation implementation in their hands, which is
  ADR-0047 §3's refusal wearing a different hat.
- **Thin JavaScript, for UI only.** Tabs, tables, expand/collapse. **No JS arithmetic**, and no JS
  that transforms a computed value before display beyond formatting it. The renderer never sums.
- **The verification manifest asserts on open**, before anything renders (ADR-0047 §3).

### The notebook

Same pinned modules, same scoped data, same manifest, same audit line. The differences are what the
recipient can do:

- **Intermediates are cells.** The value is watching the arithmetic happen, not being told its
  result — which is what a cost analyst actually wants when they disagree with a number.
- **The manifest is the FIRST cell, and it asserts.** Not a comment, not an appendix — the
  equivalence check runs before anything else and fails loudly.
- **Editing is possible and expected.** ADR-0047 §8.1's drafted cost line — *"it invites editing the
  computation"* — is a **feature** in this format. An analyst poking at a rate assumption is the
  use case, not the abuse of it.

### §2.1 — THE TWO FORMATS DO NOT CARRY THE SAME GUARANTEE, and neither may claim the other's

**This is the one place the formats genuinely diverge, and it must be stated rather than inherited
from ADR-0047 §3's shared text.**

| format | the equivalence claim | why |
|---|---|---|
| **HTML** | **verified on every view** | the manifest gates display; a divergence blocks rendering, so nothing is ever shown that the engine did not produce |
| **notebook** | **verified AS DELIVERED** | the manifest cell runs first and asserts — but the recipient can then run cells out of order, edit one, and obtain a divergent number **with no refusal firing**, because they broke the seal deliberately |

**The notebook's weaker claim is not a defect; it is the cost of the thing that makes it valuable.**
An analyst who cannot change an assumption cannot explore, and exploration is why they wanted this
format. **After the manifest cell passes, the customer owns what they see** — and that sentence
belongs in the notebook's own header text, not only in this ADR.

**What must never happen:** the notebook being described, in a proposal or a cover note, with the
HTML's guarantee. *"The package refuses to show you a number we didn't produce"* is true of one
format and false of the other, and it is precisely the kind of claim that gets copied between
documents because it is the better sentence.

---

## §3 — What must be MEASURED, not guessed

Stated as measurements to take, because each is a number nobody has and every estimate would be a
guess wearing a decimal point:

1. **Bundle size**, with the runtime, the modules, and one recipient's data. This is the number that
   decides §5's runtime question and whether the artifact is emailable at all.
2. **Boot time to first render**, on a cold open, on hardware the recipient plausibly has — not on a
   developer laptop.
3. **Numeric-stack fidelity in the browser runtime.** Whether the pricing modules' dependencies run
   unmodified is a *risk to measure first*, not a property to assume; if they do not, the runtime
   question re-opens before anything else is built.
4. **The offline-verification step, and who owns it.** Someone must open the produced package on a
   disconnected machine and confirm it renders — every time, as part of producing it. **This is a
   human step with an owner, not a CI job**, until §5's seal makes it automatable. An unowned
   verification step is one that stops happening in month two.

---

## §4 — What this ADR does not decide

- **~~The runtime~~ — RULED 2026-09-02: both formats are built** (ADR-0047 §8.1, §2 above). What
  remains open is narrower and belongs to the recipient rather than to us: **which format a given
  recipient class receives by default**, answered by §6's prototype exercise on evidence. **If
  measurement 3 fails**, the HTML format's runtime changes and this section is where to record it —
  the notebook is unaffected, which is a second reason not to have picked one.
- **Manifest intermediate filtering** — ADR-0047 §8.3, open there, inherited open here.
- **Whether the graph-node half proceeds now** — no longer a collision question: ADR-0024's
  amendment leaves only its harm (a), so the open part is *how* the `PublishedArtifact` node lands
  graph-native, not *whether* the export proceeds.

---

## §5 — Acceptance seals, each proven-to-bite before green counts

1. **THE MANIFEST BITES.** Corrupt one embedded intermediate in a produced package; the package
   **refuses to render** and names what diverged. *Bite check:* the uncorrupted package renders
   fully — so the seal is shown to discriminate rather than to refuse everything.
2. **ENTITLEMENT DISCRIMINATES, three recipients.** Package the same scenario for two recipients
   with different scopes: **the embedded data differs, and differs in the direction the scopes
   predict.** A third packaging run, for a scope the caller is not entitled to disclose,
   **refuses at packaging time** — and refuses rather than emitting an empty package, since an
   empty package and an out-of-scope one must not look alike (ADR-0047 §5).
3. **THE NO-CDN SEAL.** Open a produced package **with the network disabled**; it renders fully,
   computes, and passes its own manifest. *Bite check:* this seal only means something if it has
   been seen to fail — introduce one external reference deliberately and confirm the
   network-disabled open degrades, because **a partial render from a missing remote asset looks like
   a styling quirk, not a failure.** That is the reachable-call failure class, and it is why the
   seal exists.
4. **THE ALGORITHM IS THE PINNED ONE.** The package's declared SHA resolves to the modules it
   actually carries — asserted by comparing the embedded modules' hash against the pin, not by
   trusting the pin's presence. *A version string is a claim; the hash is the check.*
5. **THE NOTEBOOK'S MANIFEST CELL RUNS FIRST AND ASSERTS.** Executing the notebook top-to-bottom on
   a corrupted intermediate **fails at the first cell**, before any figure is produced. *Bite check:*
   the same notebook uncorrupted runs clean. **This seal is deliberately weaker than seal 1 and that
   is the ruled position** (§2.1) — it asserts *as delivered*, not on every view, and a seal claiming
   otherwise for this format would be asserting something the format cannot deliver.
6. **THE AUDIT LINE EXISTS AND IS COMPLETE.** After a packaging run, the record answers **what was
   disclosed, to whom, when, by which algorithm version** — asserted by reading the record back, not
   by observing that packaging succeeded.

**Seal 3 and seal 1 must both be run against a package produced by the real verb**, not a
hand-assembled fixture. A fixture that a developer built is a test of the fixture.

---

## §6 — Slice 1: prove the model on notional data, for a notional recipient

**Package the existing cost-estimation path for ONE notional recipient, with notional data, and
nothing else.** No real customer data enters this path until slice 1 passes its seals.

That ordering is not caution for its own sake — it is the same discipline ADR-0045 applied to a
domain engine and ADR-0046 applied to slice 1 of graph registration: **prove the mechanism where a
mistake costs nothing, because this mechanism's mistakes are the kind that cannot be recalled.** A
package is a file in someone else's building; there is no unsend. A wrongly-scoped package is a
disclosure that has already happened by the time it is noticed.

**Notional data must be obviously notional** (ADR-0045 Decision 4's discipline), and must still
**exercise the discriminating behaviour** — two notional recipients whose scopes genuinely differ,
so seal 2 has something real to discriminate. Notional data that produces identical packages for
both recipients would make seal 2 vacuous while appearing to pass, which is the shape of an
instrument measuring its neighbour.

### Slice 1 does DOUBLE DUTY — it is also the format decision, made by the recipient

**Build BOTH formats in slice 1, with the notional data, and put them in front of a real customer as
prototypes with obviously-fake numbers.** Ask which they would actually open. Three things that
buys, none of which an internal decision can:

1. **The §3 measurements come from BUILDING the mock, not from estimating it.** Bundle size, cold
   boot and numeric-stack fidelity in WASM are all outputs of the exercise. A measurement taken from
   a thing that exists beats a number argued about.
2. **The customer picks the format BEFORE real data enters the path.** The disclosure surface is
   then chosen by **the person receiving it, on evidence**, rather than by us guessing their
   tooling — and getting that wrong is expensive precisely because a package cannot be unsent.
3. **It tests the refusal beat in front of a customer.** Hand them the HTML with one intermediate
   deliberately corrupted and let them watch it refuse to render. **That demonstration IS the trust
   argument** — more persuasive than any description of the manifest, and it costs one corrupted
   byte.

**THE MOCK MUST BE PRODUCED BY THE REAL PACKAGING VERB against the registered engine — not
hand-assembled.** This is §5's own rule turned on the prototype: *a fixture a developer built is a
test of the fixture*, and a hand-made prototype would demonstrate a packaging path that does not
exist while looking exactly like one that does.

**Which makes the dependency explicit, and it is already on the board:** slice 1 waits on
[`register-cost-tool-as-engine`](../plans/register-cost-tool-as-engine.md). There is no real
packaging verb to produce a mock with until the computation is a registered engine. **That is the
right dependency rather than an obstacle** — it is the same one ADR-0047's package has, arriving one
step earlier than expected.

**Slice 1 was never gated by ADR-0047 §7, and now the collision is ruled it is doubly clear.** The packaging verb, the
manifest, the entitlement filter and all five seals are exercisable without the `PublishedArtifact`
node existing. **The graph-node half (ADR-0047 §6) is the part that waits**, and separating them is
what lets this start.

---

## §7 — A note on what the package is NOT, kept here because it will be asked for

- **Not a write-back channel.** ADR-0047 §4's non-goal, with its reason. When the customer disputes
  a number, that conversation happens where such conversations happen now — and *"customers submit
  corrections"* gets its own decision if it is wanted.
- **Not live.** It is stamped `as_of` with its rate and assumption vintage. A customer asking *"is
  this still current"* is asking §1's portal question, and the honest answer is the stamp.
- **Not the whole tool.** The predecessor shipped a tool the customer could point at their own
  inputs. This ships a *computation with its inputs fixed* — verification, not re-use. **If the
  customer wants to run their own scenarios, that is a different product and a much larger
  disclosure**, and it should be recognised as such rather than arrived at by adding one input box.

---

## Consequences

- **The customer keeps the property that made the predecessor credible** — independent verification,
  offline, in their building — while the disclosure becomes governed, scoped and audited.
- **Divergences become bounded diagnoses**, per ADR-0047 §3: same pinned algorithm, so data or
  runtime.
- **The portal's cost is deferred, not avoided**, and the package builds most of what it would need.
- **Re-issuance is the fix-propagation mechanism.** A pinned package does not improve; a superseding
  package does, and the chain records which one they checked against.

## Indicators we got this wrong

- **The bundle is too large to send** and the pressure is to drop the runtime for a JS port. That is
  ADR-0047 §3's refusal; the answer is a different runtime (§4), not a second implementation.
- **Someone adds an input box** so the customer can try their own numbers. That is §7's different
  product, arriving one control at a time.
- **Seal 3 has never been run on a machine that was actually offline.** A network-disabled seal run
  on a developer machine with a warm cache proves nothing — the cache is the thing the recipient
  does not have.

## The one-sentence model

**One file the customer opens with no network, no login and no instructions, carrying the real
pricing computation at a pinned SHA and their scoped inputs — and refusing to show them a number
unless it can first reproduce the one we produced.**
