# ADR-0049 — Cross-engine composition: how a verb answers a question that needs another engine's data

**Status:** Proposed (2026-09-02). **The gating ruling for every capability that spans engines.**
Written as a platform decision; affordability is the worked example, not the scope. **No domain
vocabulary is minted here.**
**Date:** 2026-09-02
**Deciders:** Architect
**Related:**
  - [ADR-0029](ADR-0029-process-workflow-model-spo-steps-restate.md) **Decision 5** — the
    load-bearing precedent: a declared step invokes the stage-2 eligibility gate **as a verifier**
    then dispatches; *"a workflow CANNOT be used to launder access"*; bounded by its initiator's
    grants **at every step**; delegated authority deferred, and shaped as grant-issuance rather than
    impersonation. **§1 states whether composition inherits or contradicts this. It inherits.**
  - [ADR-0045](ADR-0045-engine-f-finance-verbs-over-standard-ontologies.md) amendment — the
    variance-tree ruling: *one verb, not a chain* means **one invocation, not one step**; the
    recursion is the verb's implementation; what is refused is a **conversational** chain. **§2 is
    the question that ruling leaves open.**
  - [ADR-0044](ADR-0044-routing-ticket-credentials-minted-per-request.md) — per-request minted
    tickets; how identity threads through an inner call without over-broad credentials.
  - [ADR-0039](ADR-0039-workflow-definition-authoring-schema-and-bpmn-export.md) — `dispatch_fanout`
    as a declared step kind; prior art for one-to-many at the definition layer.
  - [ADR-0046](ADR-0046-langgraph-graphs-as-registered-mesh-verbs.md) — the admission grammar a
    composing verb passes through unchanged.
  - [ADR-0047](ADR-0047-computation-export-governed-emit-carrying-its-own-algorithm.md) /
    [ADR-0048](ADR-0048-customer-validation-package-first-consumer-of-computation-export.md) — the
    export pair. **A composed answer that gets packaged carries its composition provenance with it
    (§5), which is the seam between these decisions.**

---

## Context

### The question, stated so it cannot drift

**When a registered verb's answer requires data another engine owns, by what path does it get that
data — and under whose identity, against whose entitlements, with what provenance, and what happens
when the sibling is down?**

### The worked example, used throughout

**Affordability** is the first real consumer, and it joins three sources that live in three places:
portfolio curves owned by the planning engine, program estimates-at-completion owned by the finance
engine, and a cost stack that **is not registered as an engine at all yet**. Every ruling below is
checked against that case, in the ADR-0029 manner of proving a model on a named instance rather than
in the abstract. **Affordability's own verbs, ontology and cards are a separate decision and are not
scoped here** — this ADR must land first because building the engine before it would decide the
composition question by accident.

### A premise correction from the read

The dispatch for this ADR states *"no verb today reads another engine's data."* **That is true, and
a stronger nearby claim would be false: cross-engine calling already exists on the wire, and has for
some time.** The instance-resolution pre-step in the ontology service fans out to registered
providers — Engine D and Engine F among them — discovered from the registry rather than named in
code, each with a declared budget, each returning a typed outcome.

So the correct framing is narrower and more useful: **the mesh already crosses engines at the
ROUTER layer, as a pre-step. What does not exist is one registered VERB whose implementation
consults another engine's verb.** That distinction is exactly the subject of §2, and the existing
fan-out is the best prior art this decision has — including its hard-won failure semantics, which
§6 adopts rather than reinvents.

---

## §1 — Composition INHERITS ADR-0029 Decision 5; it does not contradict it

Decision 5 established, for workflow steps, that dispatch **invokes the stage-2 structural
eligibility gate as a verifier** — the full intersection of *domain ∩ arity ∩ argument-fit ∩
permission* — against **the caller's** identity, and that a workflow is *"bounded by its initiator's
grants, by construction, at every step."* Its load-bearing consequence: **a workflow cannot be used
to launder access.**

**Composition inherits that property verbatim, and this ADR adds no exception to it.** A composing
verb is a second way to reach the same gate, not a way around it. Stated as the governing sentence:

> **A composed answer must never contain anything its caller could not have obtained by asking the
> inner questions directly, one at a time.**

If that sentence is ever false for a composition, the composition is a laundering path regardless of
how it is implemented, and the correct response is to change the composition rather than to amend
this ADR.

---

## §2 — Is a sibling call "the verb's implementation"? — Yes at the conversational layer, NO at the enforcement layer

ADR-0045's variance-tree ruling settled that *one verb, not a chain* means **one invocation, not one
step** — a verb may recurse internally, and *"the recursion is the verb's implementation"*; what is
refused is a **conversational** chain, where the user is walked through several asks.

**The open question this ADR must answer: does calling a SIBLING verb also count as "the verb's
implementation", or is it categorically different because it crosses an enforcement boundary?**

**The ruling: it is both, and the two answers apply to different layers, which is why they do not
conflict.**

- **At the conversational layer it IS the implementation.** The user asks once and gets one answer.
  The composing verb does not return a partial result and invite a follow-up; it does not surface
  its inner calls as steps. `one verb, not a chain` is preserved exactly.
- **At the enforcement layer it is NOT.** Internal recursion over an engine's own data is **one
  authorization decision** — the engine was entitled to its own store when the call was admitted,
  and descending a tree inside it does not create a new disclosure. **A sibling call crosses an
  enforcement boundary, and every boundary crossing is a new authorization event.** The variance
  tree's recursion never leaves the engine that was already gated; a sibling call reaches data
  governed by a different entitlement, and treating it as "just implementation" would make the
  composing engine a proxy that launders its caller's scope.

**The distinguishing test, stated so it can be applied to the next case:** *does the operation reach
data the calling engine was not already entitled to serve?* If no, it is implementation and needs no
gate. If yes, it is a boundary crossing and takes the full gate, every time — however deep in the
call stack it appears, and even when it is invisible to the user.

---

## §3 — The options, with trades

### Option A — Mesh-mediated composition **← RULED (§4)**

The composing verb calls sibling verbs **through the mesh, as a caller**, under the initiator's
identity.

- **Enforcement is inherited by construction.** Every inner call passes the same stage-2 gate as any
  other call. There is no second authz surface to build, review, or forget.
- **Provenance is native.** The composed answer carries `DERIVED_FROM` edges to the inner answers —
  a real lineage rather than a reconstruction.
- **Latency stacks**, and partial failure becomes a genuine design surface rather than an
  afterthought (§6 rules it).
- **The sharp question is identity**, ruled in §4.

### Option B — Seeded duplication

The composing engine carries its own copy of the joined data, landed at prime time.

- **Deterministic and fast**; no runtime coupling; a sibling being down does not affect it.
- **But it is a second implementation of sibling data, with a staleness vintage** — the
  two-implementations-disagree hazard at data scale rather than code scale. When the copy and the
  source disagree, both are "the system's" answer and nothing adjudicates.
- **And the entitlement story breaks.** The copy is filtered by whatever the seeding process
  believed; per-caller scoping over a pre-joined copy is a second filter implementation, in the
  engine least likely to be audited for it.
- **If admitted at all, it is admitted the way `direct_call` was** — transitional, declared as such
  at registration, with a stated promotion condition. §7.3 leaves that open rather than pre-blessing
  it.

### Option C — Supervisor-level composition

The join lives above the engines: a plan of verb calls assembled and fanned out by the supervisor,
composed there.

- **Prior art exists and works** — the instance-resolution fan-out and `dispatch_fanout`.
- **The cost is where the domain arithmetic ends up.** For affordability the composition *is* real
  arithmetic — reconciling curves against EACs against a cost stack. Moving it into orchestration
  puts it somewhere with **no verb contract, no declared output class, no slots, and nothing for a
  card to bind to.**
- **So the answer to "routing pattern or laundering?" is: both, depending on what is composed.**
  Assembling and dispatching calls, then handing back typed results, is a **routing pattern** and is
  legitimate — that is what the fan-out does today. **Computing a domain answer from those results
  is laundering computation past the contract**, because the resulting number has no verb that owns
  it and no output class that describes it. **The line is arithmetic:** the supervisor may route,
  order, budget and collect; the moment it *derives a value the user reads as an answer*, that value
  needed a verb.

### Option D — Direct substrate reads **← REFUSED BY NAME**

One engine querying another engine's database.

**Refused, and refused here so it is refusable by section number**, because it is the
one-afternoon build that demos perfectly: a connection string, a join, a working number.

- **No gate.** The entitlement walk never runs; the reading engine's database credentials become the
  effective authorization for every caller it serves.
- **No identity.** The row-level question *"was this caller allowed to see this"* cannot even be
  asked — the caller is not present at the read.
- **No provenance.** The composed answer cannot cite what it derived from, because it derived from a
  table, not an answer.
- **Invisible coupling.** The consuming engine now depends on the producing engine's *schema*, which
  no contract governs and no test protects. A migration in one engine breaks another silently, and
  the breakage surfaces as a wrong number rather than an error.

**This is the bypass class.** It is the same refusal ADR-0046 §2 makes for `run_any_graph` and
ADR-0047 §2 makes for the packaging script: **an ungated path that produces a correct-looking result
on the first day.** The tell is always the same shape — a working answer with no authorization event
behind it.

---

## §4 — The four rulings

### Ruling 1 — IDENTITY: inner calls run as the INITIATOR

Per ADR-0029 Decision 5, and by construction rather than by convention: **the inner call carries the
initiator's identity**, threaded per ADR-0044's per-request minted ticket — a credential minted for
*that inner call*, not the composing engine's service credential and not a broad ticket reused
across the composition.

**The composing engine does not act as itself.** An engine that called siblings under its own
service identity would see everything it is entitled to and hand the result to a caller entitled to
less — the exact laundering Decision 5 forbids, arriving through a door Decision 5 did not name.

**Delegated authority remains deferred**, with ADR-0029's shape unchanged: if a composition ever
needs to see more than its caller, the answer is *a grant is issued*, never *the inner call
impersonates someone else*.

### Ruling 2 — ENTITLEMENT: intersection, and a NAMED HOLE rather than a silent narrowing

**Semantics are intersection.** The caller sees the composed answer only over data they could have
obtained from each inner verb directly. The composition cannot widen; it can only join what the
caller already had access to.

**The disposition when the caller is entitled to the composed verb but NOT to an inner one — this is
the ruling that actually matters, because it is where a system quietly starts lying:**

- **NEVER silently narrow.** A composed answer computed over two of three sources, presented in the
  shape of a three-source answer, is a confident-wrong answer with the system's full authority
  behind it. This is the same prohibition the entitlement-disclosure discipline already makes
  elsewhere: a narrowed result must say it was narrowed.
- **The default is REFUSE**, naming the inner capability that was unavailable and why (*not
  entitled*, distinctly from *unavailable* — see Ruling 4).
- **A NAMED HOLE is permitted only where the composed verb DECLARES the source optional at
  registration**, and the answer then carries an explicit disclosure of what is missing and what
  that does to the number. A verb that has not declared a source optional cannot decide at runtime
  that it was.
- **THE EXISTENCE-ORACLE CAVEAT, and it must be weighed per capability:** *"you are not entitled to
  the program-cost source"* discloses that the source exists and that this caller lacks it. In a
  classified or compartmented context that emission may itself be the thing being protected. Where
  that applies, the refusal must be indistinguishable from the capability simply not being
  available — which is a **per-classification policy decision**, not a per-verb implementation
  choice, and it is flagged here rather than ruled because it belongs to the enforcement overlay.

### Ruling 3 — PROVENANCE: `DERIVED_FROM` with each input's own `valid_as_of`

**A composed answer carries `DERIVED_FROM` edges to every inner answer it consumed**, and each edge
carries that input's own `valid_as_of`.

**The composed answer is only as fresh as its STALEST source, and the disclosure says so.** Not the
composition's own timestamp — which would be the freshest thing in the answer and the least
informative. If portfolio curves are current to this morning and the cost stack to last quarter, the
composed affordability answer is current to **last quarter**, and it says that on its face.

This is the `valid_as_of` discipline of ADR-0023 applied to a join, and the reason it must be
explicit is that composition is precisely where freshness silently degrades: each source is
individually fresh enough, and nobody computes the minimum.

**Consequence for the export pair:** a composed answer that gets packaged (ADR-0047) carries this
lineage into the package, and the package's stamp inherits the same minimum. A package claiming a
freshness its stalest input does not support would be the same defect, exported.

### Ruling 4 — FAILURE: an honest refusal naming the missing source, never a partial number

**A sibling that is down produces a refusal that NAMES the missing source. It never produces a
number computed over what was reachable.**

The failure mode being forbidden is concrete and this project has already paid for its shape: a
funding-status answer computed over two of three cost sources, rendered in a full grid, is
**indistinguishable from a complete answer** — and it is worse than an error, because it is
actionable and wrong.

**And the taxonomy must distinguish three states that a naive implementation collapses into one:**

| state | meaning | must not be reported as |
|---|---|---|
| **empty** | the sibling answered, and legitimately has nothing | unavailable |
| **unavailable** | the sibling did not answer — down, timed out, budget exceeded | empty |
| **unentitled** | the caller may not see it (Ruling 2) | either of the above |

**This is adopted from measured prior art rather than invented:** the instance-resolution fan-out
carries a per-provider outcome precisely so the router can distinguish *"provider declined"* from
*"provider exceeded its budget"* — a distinction added because collapsing them **hid a real
timeout bug behind an abstention contract.** Composition inherits that outcome discipline in full,
including **per-sibling declared budgets**, whose absence in that system left a floor doing
load-bearing work it was never meant to do.

---

## §5 — What a composing verb looks like at registration

Nothing new is invented; the ADR-0046 admission grammar applies unchanged. A composing verb declares
its slots, arity, subject, output class under `mesh:Response`, and refusal contract — **plus its
inner dependencies (§7.2, leaning yes)**.

**It is one verb.** It appears in a caller's eligible set as one capability, produces one declared
output type, and binds to one card. The composition is invisible to the conversation and fully
visible in the provenance — which is the correct division and the one §2 rules.

---

## §6 — Open questions, with trades

**1. Caching an inner answer within one composition.** *Probably yes within the request, never
across it* — but stated as open because the boundary needs care. Within a single composition, the
same inner verb may be consulted more than once (three affordability sub-computations may each want
the same program EAC), and re-asking is pure latency for an answer that must be identical anyway —
worse, if it is *not* identical, the composed answer is internally inconsistent, which is an
argument for a request-scoped cache being a **correctness** mechanism rather than a performance one.
**Across requests it is refused**: a cached inner answer is a copy with a staleness vintage
(option B in miniature) and, critically, **a cache keyed without identity would serve one caller's
entitled answer to another.** Open: whether the request-scoped cache is keyed by
`(verb, args, identity)` — which it must be if it exists at all.

**2. Does a composing verb declare its inner dependencies at registration?** **Leaning yes**, and
the precedent is strong: ADR-0029 rules that a workflow whose steps are **statically declared** can
be checked at *start* — the pre-flight permission check — and must fail there rather than partway
through, because a doomed run consumes an approver's attention and, at classification, *creating*
the task is itself an existence-oracle emission. **Declared inner dependencies make a composing verb
checkable the same way**: eligibility for the whole composition is computable before any inner call
fires, which makes Ruling 2's refuse-or-named-hole a **start-time** decision instead of a
partway-through one. The cost is rigidity — a composition that chooses its sources dynamically
cannot declare them — and whether any real composition needs that is the open half. **Note the
same-shape argument this document must not commit itself:** an undeclared dependency set makes the
entitlement story dynamic, and a dynamic entitlement story cannot be reviewed as policy.

**3. Is option B's transitional form ever worth admitting?** Open. The case for it is a sibling that
is genuinely unavailable at the needed cadence, or a join too expensive to compute per request. The
case against is that a transitional mechanism with no forcing function becomes permanent — and
unlike `direct_call`, which promotes to a real verb, seeded duplication has **no natural promotion
target**: it is retired by option A becoming fast enough, which nobody schedules. **If admitted, it
needs a promotion condition that is an observable event rather than a good intention.**

---

## §7 — Consequences

- **The affordability engine's author can start without asking**: identity is the initiator's,
  entitlement is intersection with refuse-by-default, provenance is `DERIVED_FROM` with a stalest-
  source stamp, and a down sibling refuses by name.
- **An engine that reads a sibling's Postgres is refused by section number** (§3, option D).
- **Composition costs latency and gains enforcement for free.** That trade is deliberate: the
  alternative buys speed with an ungated path, which is the thing this platform exists not to have.
- **The unregistered third source is now a prerequisite, not a detail.** Affordability cannot
  compose a cost stack that is not a registered engine — under option A there is nothing to call.
  **Registering it is on the critical path**, and it is also the computation ADR-0047's package
  carries, which is where these three decisions meet.
- **A composed answer's freshness will surprise people**, because it will often be older than any
  of its parts appear to be. That is the disclosure working.

## Indicators we got this wrong

- **Every composed verb declares every source optional**, so nothing ever refuses. Ruling 2's
  named-hole path has become the default and the refusal is decorative.
- **A composition's latency drives someone to seed a copy** without a promotion condition. That is
  option B arriving as an optimisation.
- **`DERIVED_FROM` edges exist but nothing reads them.** Provenance that no surface consumes is
  write-only, and this project has one of those already.

## The one-sentence model

**A composing verb is one invocation to the user and a sequence of separately-gated calls to the
mesh — carried out under its caller's identity, over the intersection of what its caller could have
asked for one question at a time, stamped with the age of its stalest input, and refusing by name
rather than answering around a source it could not reach.**
