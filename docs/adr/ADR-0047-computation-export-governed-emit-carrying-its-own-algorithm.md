# ADR-0047 — Computation export: a package is a governed emit carrying its own algorithm, data, and proof of equivalence

**Status:** Proposed (2026-09-02). **Not started.** This ADR exists so the wrong build — a script
that zips up "the data" — is refusable by citation before anyone writes it. §2 refuses it by name.
**Date:** 2026-09-02
**Deciders:** Architect
**Related:**
  - [ADR-0024 Part B](ADR-0024-standards-composition-bpmn-calm-odps-odcs.md) — publish/promotion.
    **This ADR extends its vocabulary rather than restating it**: one-way emit, `PublishedArtifact`
    as a thin reference, frozen-at-promotion, the four rules. A package is a publish target whose
    target system is a *recipient* rather than a tool. **That ADR's sequencing STOP collided with
    this one and was RULED by its owner on 2026-09-02 — the STOP binds tool targets only; see §7
    here and the amendment there.**
  - [ADR-0023](ADR-0023-iagent-answer-artifact-graph-cqrs.md) — `AnswerArtifact`, `valid_as_of`,
    and the content-hash discipline a package's identity reuses.
  - [ADR-0034](ADR-0034-trust-lifecycle-admission-policy-decision-records-autonomous-path.md) —
    `ruleset_ref`: content hash as the identity of a ratified artifact. A package's locator is the
    same move applied to an emitted one.
  - [ADR-0046](ADR-0046-langgraph-graphs-as-registered-mesh-verbs.md) — the admission grammar. The
    packaging verb is admitted exactly as any other verb: declared slots, arity, output class,
    refusal contract. **A package is not a special kind of thing that gets a special door.**
  - [ADR-0048](ADR-0048-customer-validation-package-first-consumer-of-computation-export.md) — the
    first consumer. **Read that one for what gets built; read this one for what is allowed.**

---

## Context

A recipient outside the system needs to check a number the system produced — not to be shown it
again, but to **re-derive it themselves**, offline, on their own machine, without asking anyone.
The predecessor practice for this was to hand over the whole tool and let them run it.

The capability being exported: **a per-category cost-estimation tool with a deterministic pricing
engine and rate/escalation management.** What matters architecturally is only that the computation
is **deterministic** and **importable standalone in Python** — every ruling below turns on those two
properties and none turns on what it prices.

> **AMENDED 2026-09-02 — the second property is now DESIGNED IN rather than inherited.** This
> section first said the computation *"already exists in Python"*, written on the assumption that an
> existing external tool would be wrapped. **There is no such tool to wrap in this workspace**, so
> the capability is being **built to this specification** as a mesh engine
> ([`register-cost-tool-as-engine`](../plans/register-cost-tool-as-engine.md)), with *no config read
> at import, no module-level I/O, and the pricing composition a pure function of its inputs.*
>
> **This strengthens §3 rather than weakening it.** "The modules happen to be importable" was a
> property to be discovered and possibly refuted; "the modules are written to be importable" is a
> construction constraint that cannot come back false. The isolability risk that packet carried —
> and the fork it named between *refactor* and *revise §3's byte-identical claim* — **is retired,
> because neither branch can now be reached.**

**The shape of the thing is not "an export."** It is a **governed emit that carries its own
algorithm**, and that is why it needs its own discipline rather than inheriting a report-download's.
A CSV of results asks the recipient to trust the numbers. A package that carries the computation
asks them to *check* the numbers — which is a stronger offer and a much larger disclosure surface,
because the algorithm goes out of the building along with the data.

---

## §1 — A package is produced by a REGISTERED VERB

**The packaging action is a verb, admitted through the same door as every other verb**
([ADR-0046](ADR-0046-langgraph-graphs-as-registered-mesh-verbs.md) §1). Shape:

```
package_export(recipient_scope, scenario, as_of, format)
```

- **`recipient_scope`** — spoken-mandatory. There is no default recipient, and a defaulted one
  would be a disclosure decision made by omission.
- **`scenario`**, **`as_of`** — declared per the slot grammar; `as_of` fixes the vintage §4 freezes.
- **`format`** — a **declared enum slot** (§8.1, ruled 2026-09-02). The format is an **output
  target, not a second design**: everything this ADR governs — pinned modules, scoped data, the
  verification manifest, the audit line — is **packaging-format-independent**. One governed emit,
  rendered into one of the declared targets. **The guarantee the manifest provides is NOT identical
  across formats**; see §3's closing clause.
- **Output** — a declared `owl:Class` under `mesh:Response`, so the package's own descriptor is a
  first-class answer and inherits the grounding-pool exclusion.
- **Refusal contract** — declared: what packaging refuses, and on what grounds (§5's unentitled
  scope, §3's failed self-check).

**What this buys, and it is the entire point:** packaging is **entitlement-scoped at the moment of
packaging** and **audit-lined** — *what was disclosed, to whom, when, computed by which algorithm
version.* A disclosure that leaves no audit line is indistinguishable afterwards from one that never
happened.

---

## §2 — REFUSED BY NAME: the script that zips up the data

**The tempting build is a script someone runs against the database that gathers the relevant rows,
zips them with a copy of the tool, and emails the result.** It is an afternoon's work, it produces a
working package, and it is refused.

It is refused because **it is the ungated path, and the gate is the whole product**:

- **No entitlement evaluation.** The script's scope is whatever its query returns. The recipient
  gets what the query author believed they should get — a disclosure decision made in a WHERE
  clause, by someone who may not hold the authority to make it.
- **No audit line.** Nothing records that a disclosure occurred, to whom, of what. The first time
  anyone asks *"what did we send them in March"*, the answer is a search of somebody's sent mail.
- **No algorithm identity.** "A copy of the tool" is whatever was in the working directory. Six
  months later, *which* version they validated against is unanswerable — and that question is the
  one that matters when their number and yours disagree.
- **No refusal path.** A script cannot decline. Every invocation produces a package, including the
  invocations that should not have.

**The precedent is [ADR-0029](ADR-0029-process-workflow-model-spo-steps-restate.md)'s and this ADR
inherits its terms verbatim: the model must not contain a permanently-ungated path.** A packaging
script is a `direct_call` with no capability gate and no promotion condition. If an escape is ever
genuinely needed for a one-off, it takes `direct_call`'s full terms — capability-gated per
recipient, declared transitional, closed by promotion to the verb — and not a softer set.

**The tell that this is being rebuilt under another name:** anything that produces a recipient-ready
bundle without evaluating an entitlement and writing an audit line, whatever it is called.

---

## §3 — Same ALGORITHM, not same ANSWER — and the verification manifest that proves it

### The ruling

**The package carries the actual computation modules, at a pinned commit SHA.** Not a description of
the algorithm, not a specification, not a port.

### The rejected alternative, named with its reason

**A reimplementation of the pricing arithmetic in JavaScript, so it runs natively in the recipient's
browser, is REFUSED.** It is the obvious build — the bundle is smaller, the runtime is already
there, and it demos identically on day one.

It is refused because **a second implementation of the arithmetic is the renderer-never-sums
violation, shipped to the customer.** This project's standing rule is that the producer computes and
the renderer displays; a JS port makes the renderer compute, in a different language, on the
recipient's machine, outside every test the real engine has. And the two **will** diverge — not
maybe: rounding, escalation compounding order, and edge-case handling are exactly where independent
implementations of the same arithmetic part company, and each divergence is a number the customer
can prove wrong. **Shipping a second implementation converts every future engine fix into a
two-place fix, one of which is in the customer's hands and cannot be recalled.**

### The verification manifest — the refusal contract, shipped

**The package embeds inputs, intermediates, and expected outputs captured from the producing
engine.** On open, the package **recomputes them and compares**.

**On divergence it REFUSES TO RENDER.** Not a warning banner, not a highlighted cell — a refusal,
naming what diverged. This is the abstain contract crossing the building line: a package that
displayed a different number than the engine produced would be the confident-wrong answer with the
system's name on it, in a file the system no longer controls.

**What this construction buys is a narrowing, and the narrowing is the deliverable:** because the
algorithm is byte-identical and pinned, **a divergence can only mean data or runtime — never
algorithm.** That turns an unbounded argument ("your model is wrong") into a bounded diagnosis with
two candidates. A package carrying a *port* cannot make that claim at all, which is the second
reason the port is refused.

**The manifest must be proven to bite before any green counts** — corrupt one embedded intermediate,
confirm the package refuses. A self-check that has never failed is decoration.

**AND THE STRENGTH OF THIS GUARANTEE IS FORMAT-DEPENDENT, which must not be glossed.** In a format
where the manifest gates display, equivalence is asserted **on every view**. In a format where the
recipient can execute cells out of order, edit one, and see the result — which is a *feature* for
some recipients — the manifest asserts **as delivered**, and after that the recipient owns what they
see. Both are honest; **they are not the same claim**, and a format must not inherit the stronger
one by sharing this section. See
[ADR-0048](ADR-0048-customer-validation-package-first-consumer-of-computation-export.md) §2.1, where
the distinction is stated per format.

---

## §4 — Frozen, one-way, read-and-verify

**ADR-0024 Part B's four rules apply unchanged. They are not restated here; the deltas are:**

- **Rule 1 (reference only, no copies) inverts for this target, deliberately, and the inversion is
  the ADR's most load-bearing exception.** For a tool target, iagent holds a thin reference *because*
  the tool holds the content. For a recipient target, **the recipient holds the content and iagent
  holds the thin reference** — the `PublishedArtifact` records the locator and the hash, never a
  second copy of what was sent. Rule 1's *purpose* (iagent must not be able to present stale content
  as live) is preserved exactly; only the party holding the content changes.
- **Rule 3 (validity gates publish, not post-publish life) holds verbatim.** A package is stamped
  with `as_of` and with the **vintage of the rates and assumptions** it embedded. Post-emission, the
  package's freshness is not tracked, because it cannot be: it is a file in someone else's building.
- **Rule 4 (dangling renders honestly; status backfill yes, content backfill never) holds
  verbatim**, and applies to supersession: when a package is re-issued, the prior one is not
  reanimated or amended. It stands as what was sent.

**NON-GOAL, stated with its reason: there is no write-back path.** The package does not submit
corrections, annotations, or accepted/disputed flags back into the system. Not because the feature
is bad — *"recipients submit corrections"* is a genuinely valuable capability — but because it is a
**different decision** with its own identity, authorization, provenance and admission questions
(who is the external submitter, what authority do they carry, what does an accepted correction
change, and what happens to answers already derived from the disputed value). **It must arrive as
its own ruled decision, never as scope creep on an export.** A write-back bolted onto a read-only
package is an unauthenticated external write path into a governed store.

---

## §5 — Entitlement filtering happens at PACKAGING time, per recipient

**Everything embedded in the package is disclosed. There is no render-time filtering in a file the
recipient owns** — a package that embedded broader data and hid part of it in the UI has disclosed
all of it, and the hiding is theatre against anyone willing to open the file.

Therefore the entitlement evaluation runs **once, at packaging**, against `recipient_scope`, and
what survives it is what gets embedded. A packaging run for a scope the caller is not entitled to
disclose **refuses**, and refuses at packaging time rather than producing an empty package — an
empty package is indistinguishable from a scope with no data.

**THE EXISTENCE-ORACLE NOTE, and it is easy to miss: what the package OMITS is also a disclosure
decision.** A recipient who receives a package covering categories 1, 2 and 4 has learned that
category 3 exists and is being withheld. Structural absence is information. This ADR does not rule
the disposition — the choices are *omit silently*, *omit with a declared count*, or *omit with a
named-hole disclosure* — but it rules that **the disposition must be chosen deliberately per
recipient class and recorded**, rather than falling out of whatever the filter happens to do. The
same reasoning that makes a silently-narrowed answer dishonest inside the system applies with more
force to a file that leaves the building.

---

## §6 — The package is a `PublishedArtifact`

Per ADR-0024 Part B's node shape, with the recipient target:

- **`target_system`** = **`recipient-html` | `recipient-notebook`** — new values in the enum
  alongside `dbt | superset | grist | dagster`. The enum is extended, not bypassed. **Two rows, not
  two designs** (§8.1): the format is an output target of one governed emit, and the enum already
  anticipated extension. *A third row is what a future format costs.*
- **`locator`** = **the package's content hash**, per ADR-0034's `ruleset_ref` discipline. A
  content hash is the right locator here for the reason it is right everywhere: it is the only
  identifier that cannot drift from what it names. *"Which package did they get"* and *"is this the
  package they got"* become the same question.
- **`PROMOTED_TO`** → the frozen `AnswerArtifact` the package derives from, captured at emission —
  **capture-or-lose-forever**, exactly as Part B states.
- **`SUPERSEDES`** → the prior package for that recipient scope, so **"which version did they
  validate against"** is answerable forever. This is the chain's strongest use case yet: for a tool
  target, git holds the real history; for a recipient target, **nothing else holds it at all.**

---

## §7 — COLLISION WITH ADR-0024 PART B'S SEQUENCING STOP — raised here, RULED there

**Read 2026-09-02, and this ADR does not resolve it unilaterally.**

ADR-0024 Part B contains an explicit sequencing ruling: *"The publish backend does NOT start until
the projector lands"*, on the grounds that a publish backend built earlier would either create a
parallel non-graph storage path for `PublishedArtifact` (violating ADR-0023's graph-native
discipline) or land code that cannot project published artifacts to the canvas. Its STOP section
names the next thread's work and forbids sketching it early.

**The current state, verified rather than assumed:**

- **`PublishedArtifact` exists in documentation only — zero occurrences in `src/` or
  `agent_fleet/`.** The publish backend has never started.
- **The projector is partly built and deployed** — `helm/.../values.yaml` carries a Projector block
  labelled *Hop 2 of the projector build plan*, and `tests/test_hop1_*`, `tests/test_hop2_*` exist.
  The build plan's own header says *"build complete through Hop 3"*.

**RESOLVED 2026-09-02 by ADR-0024's owner, before this ADR was committed.** The collision was
drafted with three defensible readings and the ruling selected the second: **the STOP binds TOOL
targets only.** The ruling and its reasoning are recorded as an amendment in
[ADR-0024](ADR-0024-standards-composition-bpmn-calm-odps-odcs.md), immediately above its STOP-point
section — *there* rather than only here, because a STOP whose resolution lives downstream is one the
next reader re-litigates.

**The reasoning, in one line, is Part B's own stated harms applied to a target it did not
anticipate:** harm (b) — publish code that cannot project to the canvas — **does not apply**, since
a recipient package has no canvas projection requirement and no wrapper-layer read-back at all;
harm (a) — a parallel non-graph storage path for `PublishedArtifact` — **still binds**, because
nothing about the target changes where the node lives.

**Therefore the split, which is the operative result:**

- **§§1–5 proceed now.** The packaging verb, the entitlement filter at packaging time, the
  verification manifest and the seals touch nothing the projector gates.
- **§6 still waits**, and waits on harm (a) specifically: **the `PublishedArtifact` node for a
  recipient target must not be built as a side-store.** It lands graph-native, or it lands after the
  projector ruling. **The graph-node discipline is unchanged** — the amendment scopes the STOP; it
  does not relax Rule 1 or ADR-0023.

**`target_system` gains `recipient`** by that amendment, so §6's enum extension is now ratified
rather than proposed.

*Kept as a section rather than deleted now that it is answered, because the collision is the kind of
thing a later reader will rediscover from ADR-0024's side; this is where they find that it was seen
and ruled rather than missed.*

---

## §8 — Open questions, laid out with trades

**1. ~~The runtime the package executes in.~~ RULED 2026-09-02 — BOTH, because they answer
different recipient questions.** The determining constraint remains that §3 forbids a port, so the
recipient must run *Python*, offline. What changed is the framing: this was drafted as a choice
between runtimes and it is not one.

| option | what the recipient can do with it | status |
|---|---|---|
| **Browser-embedded Python (WASM), single HTML file** | ***"Can I CHECK this?"*** — double-click, zero ceremony, the manifest gates display, the computation is sealed | **RULED IN** |
| **A notebook + pinned environment** | ***"Can I SEE this?"*** — intermediates are cells, the analyst walks the arithmetic step by step. **The drafted cost line — *"it invites editing the computation"* — is a FEATURE here**, for a cost analyst who wants to poke at a rate assumption | **RULED IN** |
| **A container image** | faithful runtime, no packaging cleverness — but needs a container runtime and permission to run it, which in a closed network is the blocking constraint rather than a preference | **available, unchosen** — not refused; wakes if a recipient class cannot use either of the above |

**The reasoning the first draft contained but did not follow through:** these are not competing
runtimes, they are **different questions from different people**. A contracting officer wants to
check a number; that recipient's cost analyst wants to see how it was built. **A single customer
will routinely have both**, and forcing one format on both is choosing which of them is served.

**And supporting both is nearly free under this ADR as ruled** — the pinned modules, the scoped
data, the verification manifest and the audit line are all packaging-format-independent, so `format`
is a declared enum slot on one verb (§1) and two `target_system` rows (§6).

**What is still open:** which format a given recipient class receives by default — **and that is
answered by the recipient, on evidence, per
[ADR-0048](ADR-0048-customer-validation-package-first-consumer-of-computation-export.md) §6**, not
by us guessing their tooling.

**2. Size and offline-bundling discipline.** **Every asset must be embedded; the package may not
reach a CDN.** A recipient in a closed network gets a silent partial render — fonts, a chart
library, a runtime shard — and *the failure looks like a rendering quirk rather than a missing
dependency.* This is the reachable-call failure class exactly: **a declaration that looks satisfied
because nobody checked whether the call it depends on can actually be made.** What is open is the
*discipline* for enforcing it — a build-time assertion that the bundle contains no external
references, a test that opens the package with the network disabled, or both. **ADR-0048 §5 makes
the network-disabled open a seal**; whether a build-time check is also required is open.

**3. Are the manifest's expected outputs themselves entitlement-filtered?** Genuinely open, and
sharper than it looks. The manifest embeds intermediates so the recipient can verify — but an
intermediate can carry more than the filtered output it feeds (an aggregate's components, a rate
that applies across recipients). **Filtering the manifest weakens the verification** (fewer
checkpoints, and a divergence localises less precisely); **not filtering it leaks through the
verification layer** while the output layer is scoped, which would make §5 a front door with an open
back one. Options: filter intermediates identically to outputs and accept coarser verification;
carry only *hashes* of sensitive intermediates so equivalence is checkable without disclosure; or
define a per-recipient intermediate scope. **The hash option looks strongest and is not ruled** —
it needs a check that hashing does not defeat the localisation §3 promises.

---

## Consequences

- **The zip-script is refusable by section number**, which is this ADR's main near-term value.
- **"Which version did they validate against" is permanently answerable** — content-hash locator
  plus `SUPERSEDES` chain, for a target where nothing else records history.
- **A divergence is a bounded diagnosis rather than an argument.** Same algorithm, pinned; so data
  or runtime, never algorithm.
- **Every disclosure carries an audit line**, because packaging is a verb and verbs are audited.
- **The equivalence claim is load-bearing and must be maintained.** Pinning a SHA means a package's
  algorithm is frozen at emission; a fix landing later does not reach packages already sent. That is
  correct — they must keep matching what they were verified against — and it means **re-issuance is
  the mechanism for propagating fixes**, which is what the `SUPERSEDES` chain is for.

## Indicators we got this wrong

- **A recipient asks for a format the package cannot produce** and the pressure is to add a
  render-time filter or a lighter "summary" package. Both re-open §5; the answer is a second
  packaging run at a different scope, with its own audit line.
- **The manifest never fires in a year of use.** Either the check is decoration (prove it bites) or
  it is checking something that cannot vary — and a check that cannot fail is measuring the
  neighbour of the claim.
- **Someone proposes "just a small JS helper" for one derived figure.** That is §3's refusal
  arriving in miniature; the arithmetic belongs in the pinned modules or nowhere.

## The one-sentence model

**A package is a verb's output that happens to leave the building: entitlement-scoped when it is
made, carrying the real algorithm at a pinned SHA and the proof that it still computes what the
engine computed — and refusing to render rather than showing a number the system did not produce.**
