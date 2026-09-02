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

**Naming fence, stated because it is load-bearing:** the exported capability is described here only
as **a per-category cost-estimation tool with a deterministic pricing engine and rate/escalation
management**. No internal module, page, or file names appear in this ADR. Nothing architectural
depends on them — every ruling turns on the computation being *deterministic* and *already Python*.

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

## §2 — The concrete shape

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

- **The runtime** — ADR-0047 §8.1's trade table, resolved by §3's measurements. §2 above states the
  *intended* shape (browser-embedded Python) because it is the one that satisfies the requirement
  with the least ceremony; **if measurement 3 fails, the shape changes and this section is where to
  record it.** That is a stated intent contingent on evidence, not a decision.
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
5. **THE AUDIT LINE EXISTS AND IS COMPLETE.** After a packaging run, the record answers **what was
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
