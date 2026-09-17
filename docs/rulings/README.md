# Rulings register

**A `RULED` line cites an entry here, or it is not a ruling.** That rule has been in force in
the lane charter for some time and until 2026-09-11 it cited a file that did not exist —
`invincible-agent-5f` found it by searching with a positive control, and correctly refused a
dispatch item on the grounds that "per the ruling" named no register. Every ruling made in
conversation was unshipped until this file existed.

**What belongs here:** a decision that constrains future work and was not obvious from the code.
**What does not:** anything derivable from the repo, and anything still under discussion — a
proposal is not a ruling, and relaying one does not promote it.

**How to cite:** `RULED <date> — see [rulings#r-00N](../rulings/README.md#r-00n-slug)`, placed
**at the section it governs**, not collected at the top of a document. ADR-0047 established that
house style and ADR-0051 follows it.

**Status vocabulary.** `RULED` — decided, in force. `PROPOSED` — stated but not decided; must not
be implemented. `SUPERSEDED` — struck at its first hit with a pointer to what replaced it, never
deleted, because a stale statement left beside a live one reads as policy rather than history.

---

## R-001 — EAC: all three methods on one panel

**RULED 2026-09-09.** Source: architect, on `program_finance`'s `finEacCalculation` panel.

> *"my recommendation is all three methods on one panel; pinning hides the divergence that is
> the finding."*

EAC is spoken-mandatory **because** the three methods disagree materially — **$13.13M /
$14.15M / $14.79M against a $12.00M budget**, on the engine's own seed. A template that
silently picks one is **choosing the answer**, and the reader cannot tell a choice was made:
the panel renders, the number is real, and the divergence that IS the finding is invisible.

**Scope, so this does not over-reach:** it governs a **required slot whose value changes the
answer materially**. `plan_schedule`'s optional `scope_initiative_id` filters a portfolio-wide
answer and declaring it changes nothing about what the panel means; `portfolio.yaml` declaring
its verbs' own defaults remains correct. The discriminator is whether a reader shown the panel
would want to know a choice was made.

**Not yet satisfiable.** `fin_eac_calculation` takes `method: EACMethod` — one Literal — and
raises `MethodRequired` otherwise. One panel is one invocation is one method. **Honouring this
needs an engine change** (the verb returning all three rows, or a sibling comparison verb).
Until then `method: CPI` stands as a placeholder **and is explicitly NOT a considered choice**.
5f verified this at `5a9def7` and stopped rather than shipping a placeholder that reads as
settled — correct.

**Related:** this is the template-level form of three rules the repo already enforces — a
declared default that changes the card is a claim; an optimistic default is dishonest; a
plausible value where an absence belongs is worse than the absence.

---

## R-002 — `lens` on the template schema

**RULED 2026-09-11.** Source: architect, this thread. **Promoted from PROPOSED on this date** —
until this entry existed it was a relay, and 5f was right to refuse it.

`lens` is a field on the template schema. `program_finance` declares the **finance** lens.
**Absent means portfolio.**

**Consumers, and the ordering between them:**

* **cortex-ui** reads the lens **from the board record**, never inferred. Until this entry
  existed, cortex-60 was correct to leave it untouched.
* **The template schema change is an ADR-0050 amendment** and wants that amendment written, not
  a silent field addition.

**Blocked behind [R-005](#r-005--shared_slots-are-template-scoped).** `lens` lands with the
Phase 2 template work, which does not move until the seeder is scoped.

---

## R-003 — `template_id` is the field; `canvas_type` is read-only legacy

**RULED 2026-09-10.** Source: architect. **Shipped** — cortex-ui `6168a39`.

`template_id` is the field. `canvas_type` is honoured as read-only legacy **with a log line
naming field, value and replacement**, fired **only when the legacy value was actually
honoured** — when `template_id` is also present and wins, reporting that `canvas_type` "was
honoured" would report an honouring that did not happen.

**A silently-ignored field is indistinguishable from a field that still works**, which is why
the notice is part of the ruling rather than an implementation detail.

---

## R-004 — ADR-0051 sustainment safety: four rulings

**RULED 2026-09-10.** Source: architect. Recorded in place at the sections they govern
(ADR-0051 §5:290, §5:312, §3:242, §9:435), per ADR-0047's house style.

| # | ruling | where |
|---|---|---|
| a | **The author sees what they can act on, and nothing more.** ⟺ **AMENDED 2026-09-12.** `see ⟺ can_act` is **the substrate's shape**, not a gap in an implementation — the projection materialises one row per authorized ACTOR, so viewability and act-ability derive from one Topaz answer and cannot diverge. The earlier reading described a view-only author audience as though it were available; it is not, and saying so plainly is the honest version. **The inert grant is withdrawn** — see the note below. | §5:290 |
| b | **`rejected` is reason-required too**, not only `accepted` — both verbs. Seal 6 mutates them **separately**, because one mutation covering both passes with one still wired. *(Kill counts prove guard-is-right, never guard-is-reachable — R-056.)* | §5:312 |
| c | **`trendMishaps` → slice 3.** | §3:242 |
| d | **SAFETY compartment deferred.** | §9:435 |
| e | **The acceptance verb is `accepted`, NOT the seed's `approved`.** RULED 2026-09-11, architect. A risk is *accepted* by an authority — MIL-STD-882's word, and the ADR's whole claim. `approved` is the generic seed's verb for generic things. A queue showing both side by side is showing **two different acts, correctly**; the declaration row's label makes it explicit. The SDK constrains verb strings nowhere, deliberately, so this is expressible without asking anyone's permission. | §5 |
| f | **Belt and braces until the cutover.** RULED 2026-09-11, architect. The safety kinds declare `reason_required` on the row **and** the verbs go into the global `_REASON_REQUIRED`, because a declared `reason_required` does **nothing at runtime today** — `validate_decision` consults a kind-blind global set and declarations are not wired into `human_tasks` at all. Declared-and-unenforced is the `isRegisteredKind` shape. The global entry is the enforcement until the declaration is read, and the cutover's parity arm asserts the row property when the global goes away. | §5 |

**§10.3 is struck through rather than deleted**, so a reader can tell *answered* from *never
asked*. Neither remaining §10 question blocks increments 0–4; **§10.2 gates a claim, not a
build**.

**ON (f), WHAT LANDED AND WHAT DID NOT, because the ruling says "both verbs" and only one is in:**
`accepted` is in the global set as of `lane/74`. **`rejected` is not, and the reason is measured
rather than stylistic.** That set is kind-blind, and `rejected` is in `accepts` for
`access_request`, `grouped_review` and `workflow_ack` — so a global entry makes **every rejection in
the fleet** reason-required, changing three other species' behaviour from the safety lane, to
enforce a property for a kind that does not exist yet. `accepted` has the opposite profile: no
existing species accepts it, so the entry is **inert until the safety kinds land**, which is exactly
what makes it safe to add ahead of them.

**RESOLVED 2026-09-11, architect — `rejected` is NOT added globally, and that is the ruling rather
than a deferral.** It becomes reason-required **on the safety declaration row**, enforced when
M3.3's cutover reads rows. R-004(f) therefore stays half-landed **on purpose**, and the register
records the kind-blindness as the reason.

**This is now an argument FOR the cutover rather than a consequence of it.** The global set cannot
express a per-kind property, and this is the first time that limit cost anything real: a verb that
must carry a reason for a risk acceptance and must not for an access request is **not expressible**
until the declaration is what `validate_decision` reads.

**These rulings must travel with the declaration, not with the code table.** `_VERBS_BY_KIND`
and cortex-ui's `taskKindRegistry` are **interim by construction and retire together**. The SDK
`TaskKind` row already carries `reason_required` as a field, validated as a subset of `accepts`
— so R-004b is a property **of the declaration** from the first schema, and the cutover seal
compares it row for row. Otherwise the bad half survives: a served declaration saying how a task
renders while a code table still decides what it can do.


### On (a): what was filed, and what the withdrawn grant teaches

**OPTION (b) IS REAL PLATFORM WORK AND IS FILED WITH ITS USE CASE** — a `viewer` relation with
`can_view`, and rows materialised with the act gate closed. **A safety officer who must see every
open acceptance and dispose none is a standard role**, so this will be needed; it is simply not
increment 3's to build.

**Option (c) — a blind author — is refused.** It is a design nobody would choose on purpose.

**THE WITHDRAWN GRANT IS THE ✅ REGISTERED SHAPE, IN POLICY.** It read as protection and protected
nothing: same defect as a registration that reports success and routes nowhere, moved from the
mesh into the authorization rail. It belongs in this register rather than only in a commit,
because **the next person to read that grant would have read it as coverage.**

**AND SEAL 7 KEEPS THREE LEGS WITHOUT A PERMISSION THE MODEL DOES NOT HAVE**, by running **two
assessments instead of one**:

    a HIGH   — alice disposes; bob and carol see nothing
    a MEDIUM — bob disposes;   alice and carol see nothing

That discriminates *"cannot see"* from *"not on this tier"*, which the middle-leg version could
not. **It is the stronger seal rather than merely the available one: it proves the ladder ROUTES**,
where a single assessment with one disposer is equally consistent with a ladder that always routes
to alice.

---

## R-005 — `shared_slots` are template-scoped

**RULED 2026-09-11.** Source: architect, this thread. **Lane 1 owns the implementation.**

Declaring `program` globally regresses `portfolio` to 409, because the seeder demands a value
for **every declared slot**. The fix is **scope**:

* `shared_slots` are **template-scoped**.
* The seeder binds **only what the seeding template declares**.
* **`portfolio` declares none**, so it is unaffected.

**This is the critical path.** Nothing in Phase 2 moves until it lands, and Phase 2 gates slice 2
and every safety template. It is `gateway.py` — Lane 1's file.

**Prior refusals were correct and are now resolved by this entry.** 5f refused twice with code
evidence (`gateway.py:1949/1954` 409 on unbound shared slots, `:1963` 501 on anything but
`portfolio`) and named the ordering: (1) the seeder dispatches each panel's declared verb,
(2) something binds a shared slot into panels, (3) then declare. This ruling is (2).

---

## R-006 — Engine B retirement

**RULED 2026-09-06.** Source: ADR-0046 §8.4 / §8.5, route C.

Engine B (LangGraph support) is retired. Its waiver in `_NOT_A_REGISTERING_AGENT` now reads *by
design* rather than *by omission*: it registers nothing because there was nothing honest to
register, its intended use case's principal input being read by no node. **Still waived, for the
opposite reason**, until the chart block is removed and the key stops existing.

---

## R-007 — §9.2 — OPEN

**Not yet ruled.** The architect decides §9.2; **slice 1 closes on that decision**. Recorded here
as an open slot so that a `RULED` line citing it cannot be written before the decision exists.

---

## R-008 — Lane branches push on every commit; MERGING to master is the gated action

**RULED 2026-09-11.** Source: architect, this thread. Also stated in `AGENTS.md` beside the
worktree charter; **this entry is the citable form**, and the difference between the two is the
point of the entry.

    git push origin lane/<lane>      # after every commit. Always. Not a gated action.

**"Push only when asked" was written for one shared checkout on master**, where a push
published every lane's work at once. On a worktree, `git push origin lane/<x>` publishes **only
that lane's commits and merges nothing**. The reason for the permission is gone; the permission
outlived it. **Merging to master stays gated.**

**It has cost real time twice.** A worktree rebases onto ORIGIN, so a lane's local commits are
invisible to every other lane **by construction** — worse than the shared tree, where an
uncommitted file was at least readable. `tests/_mesh_verbs.py` sat committed-and-unpushed for
fifteen hours while the lane that asked for it waited. Seal 3's result then sat on an unpushed
branch under a phase gate reading *"do not start 1.1 until the run B result is written down"* —
**it WAS written down and nobody could read it.**

### Why this one needed a register entry more than any other ruling here

**A RELAYED PERMISSION-WIDENING MUST NEVER BE TAKEN ON A PEER'S WORD.** This ruling reached
invincible-agent-5f through Lane 1. They did not act on the relay. They verified the commit,
read the clause in `AGENTS.md`, adopted it because the licensed act is genuinely narrow — only
their own commits, merging nothing — **and disclosed it to their own user as reversible rather
than treating it as settled between peers.** That was correct, and it is the behaviour this
register has to make unnecessary rather than merely praise.

**The fix for a ruling a lane cannot trust is not to state it more loudly. It is for the ruling
to exist somewhere citable**, so a lane can check it instead of being told it. Note what "push
only when the user asks" is: an instruction each lane holds **from its own user**, not from this
repo. A rule written into a shared file by a peer — however well argued, however
architect-ruled — is exactly the shape that must not silently widen another agent's
permissions.

So: **this entry licenses nothing on its own.** It records what the architect decided, in a
place a lane can read and cite. A lane adopting it should do what 5f did — verify, adopt on its
own judgement, and disclose to its user — and the register exists so that the verifying step
has something to land on.

---

## R-009 — cortex-ui stays on its deploy branch; the worktree rule is for MULTI-LANE checkouts

**RULED 2026-09-11.** Source: architect thread, reported by cortex-ui-60.

The worktree convention (`ia-<NN>` ↔ `lane/<NN>`) exists to stop lanes colliding in a shared
checkout. **cortex-ui has one lane and one deploy branch**, so moving that lane off the branch it
deploys from would *create* the hazard the rule prevents. cortex-60 remains on `master` and
everything continues to land there.

**This is an exception with a stated reason, not a refusal, and the reason is what makes it
citable.** The gate cortex-60 was held against was sound: a docs commit from another lane did land
on top of their work mid-session (`cbf0846`). Collisions in that checkout are real. They are
simply **cheaper than deploying from the wrong branch** — and naming that trade is the ruling.

---

## R-010 — Canvas-template CI on `pull_request` is a blessed exemption

**RULED 2026-09-08.** Source: architect thread. Governs
[`.github/workflows/validate-canvas-templates.yml`](../../.github/workflows/validate-canvas-templates.yml);
the job and its reasoning are in [`canvas-templates-slice-1`](../plans/canvas-templates-slice-1.md).

**It overrides [`no-ci-gate-on-the-suite`](../plans/no-ci-gate-on-the-suite.md)**, which makes CI
jobs `workflow_dispatch`-only because a never-executed job wired to `push` burns minutes, goes red
for environment reasons, and trains people to ignore it. That reasoning is unchanged and still
governs everything else.

**Why this job is the exception:** ADR-0050 §1.3 requires an invalid template to fail **at merge**.
A `workflow_dispatch`-only job does not deliver merge-time failure, so shipping one and calling
§1.3 satisfied would be precisely the decorative seal ADR-0050 is written against — a check whose
green means only that nobody ran it.

**Why the convention's cost does not apply here:** the job is seconds of hermetic pure Python over
~200 lines of YAML — **no cluster, no database, no network**. The failure mode the convention
protects against (environment-caused reds that train people to ignore a gate) has no purchase on a
job with no environment.

**The demotion is pre-committed, not promised.** One environment-caused red and it goes to
`workflow_dispatch`. The standing rule loses to an argument only until it wins on evidence.

**Scope — this is an exemption, not a new convention.** It licenses this one job. A second
`pull_request` job cites its own argument or does not ship; "R-010 did it" is not that argument.
The discriminator is the pair: **a decision-bearing gate whose whole value is merge-time refusal,
AND a check with no environment to be flaky about.** A job missing either half is governed by
`no-ci-gate-on-the-suite` as before.

> **HOW THIS ENTRY WAS MISSING FOR THREE DAYS, recorded because the mechanism outlives it.** It
> was written on 2026-09-08 into the **shared master tree's working copy and never committed** —
> the session that drafted it restarted first. It was therefore invisible to `git log`, to every
> lane branch, and to the architect, who correctly remembered ruling it and reported it as sent.
> The register carried `R-010 — NOT RECORDED` for a day while the text sat forty lines above that
> placeholder in a different tree. **An uncommitted file in a shared checkout is not a draft in
> progress; it is a ruling that does not exist yet**, and nothing in the tree distinguishes the
> two. Found independently by five lanes within ten minutes of being asked to identify themselves.

---

## R-011 — Readiness fails on GAVE-UP, never on STILL-TRYING; nothing registered is not ready

**RULED 2026-09-09.** Source: architect thread.

A probe that cannot distinguish *"still trying"* from *"gave up"* has two failure modes and will
hit one of them: it **crash-loops a healthy pod** that is mid-retry, or it **admits a permanently
unregistered one**. Both come from the same missing distinction.

**A host serving zero registered capabilities is not ready**, whatever else it can answer.

First live instance: **engine-lg under the Keycloak restart at rev 107** — `ready=false` while
`status: ok`, because a graph had been admitted. The graph being admitted is not the question
readiness asks.

---

## R-012 — `getenv` DEFAULTS for service URLs are refused

**RULED 2026-09-11.** Source: architect thread. Implemented `acc6a2c`.

A missing declaration **fails readiness, naming the variable**. A default silently supplies a
plausible value and converts a configuration error into a wrong answer delivered confidently.

**Two reads answer two different questions, and one read cannot answer both:**

| read | question |
|---|---|
| readiness | *was this declared at startup?* |
| aggregation | *where is it now?* |

Collapsing them is what a default does.

---

## R-013 — Seal 3 is a REGRESSION seal; ADR-0050's empirical claim is struck

**RULED 2026-09-11.** Source: architect thread.

Seal 3 passed four times across a prime, correctly scoped. So **ADR-0050 strikes the phrase
*"the one seal phrase-based seeding cannot pass"***, records the four runs by id, and rests the
decision on **the structural argument alone**: a phrase seed has no panel set until after it runs.

Seal 3 **stays**, as a regression seal over the curated five. Its positive control is a
documented-unstable phrase, run only when a future run differs.

**Law recorded by this ruling:** *a population hardened against the failure cannot measure the
failure.* The seal was not lying — the population it ran against could no longer express the
defect it was written to catch, which is indistinguishable from the defect being absent.

---

## R-014 — ADR-0037 is NEXT after the harvest; its deferral reason is dissolved; `explains` edges are IRIs that resolve

**RULED 2026-09-11.** Source: architect, this thread, relayed by `invincible-agent-91`.

> **Numbering note — SUPERSEDED 2026-09-11, and left rather than deleted.** This read: *"R-009 –
> R-013 were not present in this register when this entry was written, and nothing in the tree
> claimed them."* **True when written; false within the hour.** All five are on `lane/01` at
> `c78a240` — R-009 cortex-ui's deploy branch, **R-010 an explicit hole** (allocated, content not
> in hand, entered so a jump from 009 to 011 does not read as complete), R-011 readiness fails on
> GAVE-UP, R-012 no `getenv` defaults for service URLs, R-013 seal 3 as a regression seal.
>
> **Kept as history because striking it is the entry's own subject.** A note saying five rulings
> are missing, read a day later, sends someone hunting for nothing — which is
> [`a-figure-outlives-the-measurement-that-produced-it`](../principles/a-figure-outlives-the-measurement-that-produced-it.md)
> committed inside a register whose job is to stop exactly that. **The gap was real for one hour
> and is not a gap now.**

### 1. ADR-0037 is next after the harvest, not deferred past it

ADR-0037 has read **"NOT started, and deliberately not next"** since 2026-08-15. **That call is
the architect's and it changes.** The deferral's stated reason was that its first build task
lands in `doc-tools`, whose CI is silent on push — *"a first task that lands in a repo whose CI
is silent is not packet-sized."*

**That is a CI fix, not an architecture problem**, and it is step 0 (`doc-tools-7f`). The fact
the deferral was made against has also changed: **there is now a customer producing leaves.**
Their runbooks are the same shape — frontmatter, `explains` edges, ingested as an overlay corpus
beside the platform's.

**Sequence:** harvest + frontmatter backfill this week · doc-tools CI in parallel · ADR-0037
slice 1 dispatched the moment both are true.

### 2. `explains` edges are IRIs THAT RESOLVE. Nothing is minted.

The drafted step 2 read *"every IRI the page names — a class, a verb, a seal, a registry site —
becomes an `explains` edge."* **Struck.** A seal is a test function name; a registry site is a
Python frozenset or a dict. **Neither has a graph identity**, and a rule requiring every named
thing to carry an edge would manufacture exactly the IRIs ADR-0037 §1's invented-IRI rule
refuses.

The refusal is already recorded in the corpus by the two pages that got it right:
`adding-an-engine.md` states there is no `mesh:registerEngine` and that minting one *"to make
the edge look tidy is precisely what the gate exists to refuse"*; `adding-an-archetype.md` names
**six sites and twelve seals** and honestly explains **one** IRI, `mesh:Archetype`.

> **Edge count is not a quality signal. One page explaining one IRI is the rule working.**

**The surviving seal is one-directional:** an `explains` edge to an IRI that does not resolve
goes **red**. The reverse — *every named thing must have an edge* — is **struck**, and the reason
belongs in the ADR rather than only here, because a future reader will propose it again.

**Note this is a `resolve` check, not a `declared` check** — the two came apart three times in
eight days. The instrument is a SPARQL `ASK` against the deployed graph, not a grep of a TTL.

### 3. OPEN, for the ADR's author — a literal is not an IRI

May a `DocPage` carry a seal name or site name as a **literal property** — searchable text, not
a graph identity — so *"which runbook names `test_every_bound_archetype…`"* is answerable
without minting a node for a test?

**Permitted-in-principle, and the ADR's author may refuse it.** The architect's position: *"I'd
rather it be refused on the page than assumed."* If it reads as the same temptation wearing a
literal's clothes, **the refusal goes in the ADR with its reason** — which is the outcome either
way, since an unrecorded refusal is indistinguishable from an oversight.

### 4. Prerequisite, and it is not optional

**Backfill the frontmatter on the existing corpus before any page is ingested.** Verified
2026-09-11: of three real runbook pages, **one** carried the doc model.
`adding-an-archetype.md` carried an invented shape (`title`/`status`/`date`/`adr`) and
`rolling-a-service.md` carried none. Priming that corpus would produce **no `DocPage` for a
third of it, silently** — the invisible-absence failure the whole doc model exists to prevent.

*(`adding-an-archetype.md` fixed in `3c9582a`. `rolling-a-service.md` still open.)*

---

## R-015 — An edgeless runbook IS admitted; a page with no honest target carries `explains: none`

**RULED 2026-09-11.** Source: architect thread, raised by `rolling-a-service.md`.

A runbook with no honest graph target **is still a corpus page** — reachable by audience and by
text, just not by an `explains` edge. **Requiring at least one target would refuse every
operational runbook**, and `rolling-a-service.md` is the proof: the mesh declares four lowercase
verbs and 72 classes and not one concerns deployment, rolling, images, versions or health.

So the rule is **zero or more edges**, and a page with none says so with an explicit sentinel:

    explains: none

**The sentinel is the ruling, not the emptiness.** `none` is distinguishable from a *missing key*
(the author forgot) and from an empty list (the author was unsure). It records a decision that
someone made and can be held to, which neither of the other two states can.

**This supersedes nothing and narrows one thing:** it does not license an absent target where an
honest one exists. The invented-IRI rule (ADR-0037 §1) is untouched — the only reason to write
`none` is that the graph genuinely has nothing to point at, derived from the ontology rather than
from not having looked. Feeds ADR-0037 slice 1; see [[R-014]] on `explains` edges resolving.

---

## R-016 — One frontmatter shape for runbooks; the archetype page is SWEPT, not exempted

**RULED 2026-09-11.** Source: architect thread.

One shape, and it is `_TEMPLATE.md`'s: `iri` / `explains` / `doc_kind` / `audience_hint`.

`adding-an-archetype.md` carried `title` / `status` / `date` / `adr` — **a third shape, with no
`iri` and no `explains`, so doc ingest could not admit it.** The page the index names as *the one
that got it right* was the page invisible to the corpus it belongs to. It now declares
`explains: [mesh:Archetype]`, the single IRI it honestly explains, verified present at
`setup/ontologies/mesh_system.ttl:252` rather than read out of the ADR. Its four old fields moved
into the body rather than being deleted.

**Why a sweep and not an exemption, which is the whole ruling:** *an exemption for the page that
got the CONTENT right teaches the next author that the SHAPE is optional.* The page's authority is
exactly what makes exempting it expensive — it is the one people copy.

Found independently by two lanes an hour apart (invincible-agent-5f and iagent-mesh-sdk-ca), each
following the template as dispatched and each correctly reporting the conflict rather than
resolving it locally. **A conflict two lanes hit separately is a defect in the instruction, not a
judgement either of them got wrong.**

---

## R-017 — ADR-0053 RATIFIED; registry per-deployment, selection per-program; external modules under sha-pinned resolution

**RULED 2026-09-11.** Source: architect thread, after a full read of the text as
`invincible-agent-91` reviewed it (`lane/5f` at `effc365`).

**ADR-0053 is ratified**, and its two deliberately-open questions are decided.

### 1. Ratification is PER-DEPLOYMENT; selection is PER-PROGRAM

The registry — *which methods exist, at which version, derived from what* — is a **property of
the install**, ratified once, reviewed like a grant. Which method a given program *uses* is a
**per-program overlay row selecting among those**.

Same split as the risk matrix (ratified per deployment) and the SSPP (which method this program
applies). **It does not multiply provenance:** the figure carries method name and version
regardless of who selected it. Two programs on different EAC methods is **two overlay rows, not
two registries**.

### 2. A customer module MAY live outside the platform repo — on the condition that makes it a ruling

The row carries **the module's sha**, the way the export manifest already carries
`modules (name → sha)`. The **purity and resolution seals run against the customer package at
registration**, and the boot check refuses a module that fails them — exactly as it refuses a
graph without a row.

**That is what "the platform can verify what it executes" means concretely:** it verifies *the
sha it resolved and the properties it sealed*, and **nothing else about the package**. Same as a
graph — stated rather than assumed.

### Consequences recorded

- **91 is unblocked on `fin_variance_drivers`** — extraction first, against the seal **as it
  stands**, with its age recorded via §7's three fields (`seal_path`, `seal_last_commit`,
  `seal_age_days`) as commands rather than as typed numbers.
- §4's correction stands: **the envelope generalises, the domain section does not**, and *"one
  export class"* means the envelope. `{case_id, inputs, expected, intermediates}` with a
  domain-opaque algorithm description is the design.
- §6's Decimal retraction is **kept verbatim** — an ADR recording that one of its own claims was
  false until review is the thing this register exists to make ordinary.

### And two corpus rules ruled alongside it

**PERSONA CASE.** `policy/personas.yaml` is canonical — **`ARCHITECT`, not `architect`.** The
corpus normalises **to** the policy file, **never the reverse**; the frontmatter validator matches
**case-insensitively** and **lints to canonical case**. ***A ratified config outranks prose.***
The index sentence had said *"lowercased"*, and three pages carried the wrong case because of it
— **the index taught the defect**, which is why the sweep was three files rather than one.

**THE READ HALF OF THE PUSH RULE.** R-008 made a lane's fixes *publishable*; nothing made them
*discoverable*. Before editing a shared file:

    git fetch
    git log origin/master..origin/lane/* --name-only -- <path>

Recorded in `AGENTS.md` beside the push rule. The gap is measured, not theoretical: 91 and Lane 1
fixed one page's frontmatter independently, hours apart, on different branches, and **91's pushed
fix was still invisible** because Lane 1 read master. It cost an hour *only because the two
answers agreed* — had they differed, **the merge would have decided it silently, by whoever went
second**. Worktrees hide master; they also hide each other, and the second has no symptom.

---

## R-018 — ~~The `pcn_disposition` overlay row is WORK-SIDE~~ — SUPERSEDED BY R-020

**STRUCK 2026-09-11, same day it was written.** The architecture seat had already recorded this
subject more fully, on master, as the entry now numbered [R-020](#r-020--task-kinds-two-after-cutover-items-on-two-lanes-and-a-row-that-was-never-created).
Both were written from the same architect correction, an hour apart, by two seats that could not
see each other's register.

**Struck rather than deleted, per R-019: a ruling is retired by a ruling, with its replacement
named.** Deleting it would leave the duplication invisible, and the duplication is the evidence —
**two seats independently wrote the same ruling because the register was forked.** R-020 is the
one to cite; it carries the three-namespace `grant_to` detail this entry did not.

---

## R-019 — `invincible-agent-ad` is the ARCHITECTURE SEAT, lane-less by ruling

**RULED 2026-09-11.** Source: architect thread.

The architecture seat **routes and rules; it does not commit shared docs.** It holds no lane
branch and no worktree, and that is a ruling rather than an accident of where a session happened
to start — a seat that commits into shared files is a lane wearing a seat's name.

**TWO SEATS, ONE REGISTER.** The orchestrator (Lane 1) and the architecture seat both write
rulings *into this file*. They do not maintain parallel registers, because two registers is
precisely the state that cost a day: a citation resolving differently depending on who you asked.

**AN EARLIER ENTRY STANDS UNTIL EXPLICITLY SUPERSEDED.** Not until it looks stale, not until a
later conversation seems to assume otherwise. A ruling is retired by a ruling — struck in place,
with its replacement named — which is why R-014's numbering note is *struck and kept* rather than
deleted.

---

## R-020 — Task kinds: two after-cutover items on two lanes, and a row that was never created

> **RENUMBERED FROM R-011 ON MERGE, 2026-09-11, and the collision is the point.** The
> architecture seat allocated `R-011` against **master's copy, which held eight entries**;
> Lane 1 had allocated the same number against the fuller register on `lane/01`. Neither seat
> was careless — **the register was forked five ways and each picked the next free number it
> could see.** The number allocated with less information yields. Nothing cited either one
> outside this file, checked before renumbering. The RULING is unchanged; only its label moved.

**RULED 2026-09-11.** Source: architect, correcting their own M3.3 dispatch. Governs the
task-kind declaration layer ([`policy/task_kinds/`](../../policy/task_kinds/) and
[`adding-a-task-kind.md`](../runbooks/adding-a-task-kind.md)) and the register's lane assignment.

Recorded here rather than relayed, because the lane it was addressed to (`invincible-agent-01`)
had ended by the time the correction was ready to send. That is this file's own thesis arriving
on schedule: **a decision recorded in a conversation does not constrain anything — and a decision
addressed to a session address does not survive the session.**

**(a) The two after-cutover items belong to DIFFERENT lanes.** The dispatch put both on the
task-kinds lane.

| item | lane | why |
|---|---|---|
| the **groups ruling** — `grant_to` is users-only | whoever owns `task_grants.yaml` | a grant-rail decision, not a declaration one |
| the **`pcn_disposition` string rename** | the task-kinds lane | expand/contract with a dual-read interval |

The groups constraint is declared **verbatim in three namespaces** —
[`capability_grants.yaml`](../../policy/capability_grants.yaml),
[`ontology_compartments.yaml`](../../policy/ontology_compartments.yaml),
[`task_grants.yaml`](../../policy/task_grants.yaml) — each deferring group audiences for the same
reason; two state outright that `validate_policy` REFUSES a `grant_to` absent from `users.yaml`.
**ADR-0051 §5's one-audience-per-authority-level is the workaround that constraint forces**, not a
design preference. It was scheduled after the M3.3 cutover because the declaration is what groups
would attach to — a real dependency, which is what made the misattribution plausible.

The rename is the task-kinds lane's, because the kind string is simultaneously a live value in
`human_task_projection` rows and a UI render contract: it moves with a dual-read interval or it
strands rows. **It is deliberately NOT bundled into M3.3** — one migration at a time.

**(b) The overlay `pcn_disposition` row was never created HERE, by design — and the ruling is the
deliverable, not the row.** The dispatch listed the row as an artifact. It cannot exist in this
repo: `test_no_domain_name_entered_the_platform_seed` fails the build on a domain token in
`policy/task_kinds/`, which holds exactly four structural rows. What was delivered is the RULING
that the row lives work-side carrying its own `accepts`. The architect's framing: *a name for
something that cannot exist where it was put* — the same shape as the Engine S draft.

Record the ruling as delivered and the row as work-side, never created here. **A register carrying
a phantom deliverable is worse than one admitting a gap** — the same principle that had the
task-kind runbook's index row marked ROW ADDED rather than quietly filled.

**(c) Roster consequence, because this ruling was nearly lost to it.** `iagent-mesh-sdk-ca` is the
M3.3 / task-kinds lane, working in `iagent-mesh-sdk` **with commits in `invincible-agent`**. An
engine-repo search never finds it; `doc-tools-7f` and the cortex session are the same shape.
**The role-to-address map in `AGENTS.md` must carry the REPO beside the address** — and an address
alone is insufficient regardless, since session addresses churn hourly and `invincible-agent-01`
is already gone. A roster keyed only on them reproduces the failure it exists to prevent.

---

## R-021 — ONLY `lane/01` ALLOCATES RULING NUMBERS. Authors route text and get a number back

**RULED 2026-09-11.** Source: architect thread, closing the class that R-020's renumbering
opened.

**Nobody allocates against the copy of the register they happen to have.** An author with a
ruling to record — the architecture seat, a lane, anyone — **routes the text to Lane 1 and
receives a number.** Lane 1 writes the entry.

### Why this is the rule that makes two seats and one register work

R-019 established two seats writing into one file. **That is only coherent if exactly one of them
allocates**, and the failure it prevents was measured the same day rather than imagined:

| seat | allocated against | took |
|---|---|---|
| architecture seat | `origin/master` — **8 entries** | R-011 |
| Lane 1 | `lane/01` — **16 entries** | R-011 |

**Neither was careless. Each took the next free number it could see**, and the register was forked
five ways, so *"the next free number"* was a different number depending on which tree you were
standing in. See R-020, which is that collision resolved.

**A REGISTRY WHOSE ALLOCATION DEPENDS ON THE READER'S CHECKOUT CANNOT ALLOCATE.** That is the
whole of it. The fork is fixed today by a merge, and merges are not a mechanism — the register
will fork again the moment two lanes both hold unmerged work, which is its normal state.

### ALLOCATION AND PLACEMENT ARE TWO WAYS AN ENTRY LANDS WRONG

**Added 2026-09-12**, after the second one bit.

**Allocation** is which number an entry takes, and it is settled above: only `lane/01` allocates,
because a registry whose allocation depends on the reader's checkout cannot allocate.

**Placement is where the entry goes in the file, and it is a separate failure.** R-025 was
inserted by anchoring on the NEXT heading (`## R-005`) and landed between R-004 and R-005 — a
correctly-allocated number in the wrong place. The same move produced a **duplicate R-014** on an
earlier merge: one branch appended after *"Why this file exists at all"*, the other inserted in
numeric order, and git kept both because they were different regions of the file.

**ANCHOR ON THE END, NEVER ON THE NEXT HEADING.** The end is stable; the next heading is whatever
happens to follow today, so an anchor on it silently relocates the entry every time the
neighbourhood changes — and a register out of numeric order reads as *a gap where there is none*,
which is the one thing this file may not do.

### What this does NOT do

It does not make Lane 1 the author of anyone's ruling. **The text, the reasoning and the
authority stay with whoever ruled it** — R-020 is the architecture seat's entry in the seat's own
words, renumbered and nothing else. Allocation is a clerical monopoly, deliberately: the scarce
resource is the *number*, not the judgement.

Nor does it gate recording a decision. **A ruling with no number yet is still a ruling** — route
the text, act on it, and cite it once the number comes back. What it may not be is *numbered by
its author*.

---

## R-022 — The gateway-side projection ALREADY EXISTED; feed the accumulation into it

**RULED 2026-09-12.** Amends the author's own earlier ruling, which said the undeclared-param
filter *"lives in the gateway, once"*. **The "once" already existed.**

`accept_slots(spoken, declared)` filters supplied slots down to what the verb declares, returns
a `Refusal` per dropped slot rather than raising, and that result already reaches the routing
record through `direct_dispatch`. The accumulated chain slots are fed **into** it as a base
layer; no second projection is built.

**The rule this is an instance of:** *a second site for one rule is the defect, even when the
second site is the one you were told to build.* Same move that killed the parallel
materialisation emitter. Three engines with three behaviours for undeclared params — engine-cost
500, finance 400, planning 404 — was that defect one layer down; adding a fourth copy at the
gateway would have been it one layer up.

**What the ruling was right about stands:** engines keep their own guards as belt-and-braces, and
the gateway is the site that makes a multi-verb interview survivable, because it is the only one
holding both the accumulated set and the declaration.

---

## R-023 — The colon sweep is WITHDRAWN; the anchor lint handles what it was for

**RULED 2026-09-12**, withdrawing an earlier ruling of the architect's own. Recorded with its
reason **so nobody proposes the colon again.**

The withdrawn ruling: strip the em dash from register headings (`## R-0NN: title`) because two
slug rules disagree only on a space-surrounded em dash, so removing it would make eight
coin-flip citations correct *under either renderer without choosing one*.

**ITS PREMISE EXPIRED BETWEEN THE RULING AND ITS EXECUTION.** The rule was then settled by
measurement rather than argument — a POST to GitHub's own renderer returns
`r-005--shared_slots-are-template-scoped`, double hyphen — and the eight citations were rewritten
to it. **Applying the sweep now would break exactly what it was written to fix**: a colon heading
slugs to a SINGLE hyphen. The stated gain (eight become correct, none edited) was true against
the single-hyphen corpus and is false against this one.

`invincible-agent-f3` had the sweep built and verified — 20 headings, both rules agreeing on all
20, break-on-purpose run twice — and **did not apply it**, because the reasoning no longer held.
That is the behaviour this register exists to make possible: a ruling is citable, so its premise
is checkable.

**The residual is ergonomic and is already handled.** `--` looks like a typo and invites the
well-meant single-hyphen "fix" that broke eight citations in the first place — but
`tests/test_citation_anchors_resolve.py` reds any citation whose anchor does not match the slug
the measured rule generates from the heading. **The edit fails before it lands. No migration.**

---

## R-024 — `cost:LotCostingReview` rides the NEXT prime, not a prime of its own

**RULED 2026-09-12.** `invincible-agent-22`'s second graph (`972232a`) needs its output class in
the graph before the ratified row can register — Contract D refuses atomically, so the row cannot
land without the class.

**One prime, both declarations.** The next prime is already owed: safety's `main.py` registration
lands and seal 1 needs a fresh prime regardless. A separate prime for one class would be an
infra action bought with no information.

### And the census SNAPSHOTS the verb set, naming additions

Ruled this morning when `db.relationshipTypes()` moved 63 → 64 and **nobody could name the 64th**.
*A count that moved and cannot be attributed is the no-op-pin finding in a new costume.*

**22's finding sharpens why a derived answer will not do it: a graph-host verb comes from a
RATIFIED ROW, not from an engine's `CATALOGUE`.** Any declared-set derivation that reads engine
catalogues is blind to `finProgramBrief` **by construction**, and that blindness grows with every
graph engine-lg admits. So the census reads **the graph** and reports additions **by name** since
its last run — both sources or none, or engine-lg's verbs read as orphans forever.

## R-025 — A claim in a file's own prose is PRE-AUTHENTICATED

**RULED 2026-09-12.** From a false claim traced through three hops by `invincible-agent-28`:

    prose in a policy header  ->  repeated in a comment  ->  carried into a RULED line

**This is the stale-docstring family, worse-placed.** A docstring is read by whoever opens the
function. **A policy header is read by whoever is deciding what the policy MEANS** — so the claim
arrives already carrying the file's authority, and the next reader *cites* it rather than checking
it. That is one layer up from where this shape usually bites, and it is why it travelled as far as
a `RULED` line: every hop made it more official and none of them made it more true.

**The check is the same as for any inherited claim and it is cheap:** the artifact the code
PRODUCED outranks the file's description of itself. A grant's effect is a Topaz answer, not a
sentence above it.

Related: [[a-docstring-is-not-evidence]] — the reading half, and the instance where the author
wrote one into a seal's justification.

---

## R-026 — Three laws from the v0.8.0 pin, each about an instrument rather than a subject

**Ruled by the architect on the `frozenset`/tuple report, 2026-09-12.** All three are about the
thing doing the checking, which is why they sit together.

### (a) A wrapper that discards a fix while leaving the bump looking applied

`frozenset(...)` around a tuple is not a type annoyance. **It reverses the change the version bump
exists to deliver, and leaves every visible sign of the bump in place** — the pin moved, the lock
moved, the SDK ships the ordered field, and the value arriving at the card is unordered anyway.
Nothing is red, the release notes are true, and the defect is invisible at the only layer anyone
inspects.

**So a bump that changes a CONTRACT is not landed when the pin moves. It is landed when a seal
asserts the new contract's effect at the consuming surface**, and that seal has to be written
before the pin so it cannot be written to fit what the code already does.

### (b) Sorting an unordered source rather than passing it through

Where a source genuinely has no order, **impose one; never pass through.** Python randomises
string hashing per process, so a `frozenset`'s iteration order differs **in every pod** — measured
three times on identical input by `iagent-mesh-sdk-ca`, three different orders. Pass-through does
not produce "an arbitrary but stable order"; it produces **a fresh order on every restart**, with
nothing in the diff to explain why the buttons moved.

**Sorting is the only deterministic option available, not the tidier one.** The original docstring
here said *"arbitrary but not random"* — the decision was right and the mechanism was wrong, which
is the more durable error: **the code cannot fail, so the false premise survives to be reused
somewhere the code would.** Cf. [[a-justification-invented-downstream-fits-by-construction]] and
R-025; this is the same family with the sign flipped — a TRUE conclusion resting on a false
reason, which no test can ever catch.

### (c) The instrument and the subject share a surface — the container-type instance

**Nine seals asserted container TYPE when their claim was verb MEMBERSHIP.** `assert
isinstance(verbs, frozenset)` passes, reads as rigour, and says nothing whatever about whether the
species accepts the right words. The seal and the thing it checks touch at the same surface, so
the wrong one gets asserted and the result is indistinguishable from the right one.

**Ask what the claim is BEFORE choosing what to assert, and state the claim in the failure
message.** A seal whose message cannot say what went wrong in the subject's own vocabulary is
probably asserting its instrument.

### The corollary these three produced in practice, on the same day

**A SEAL THAT DEFENDS A CHOICE MUST ASSERT THAT ITS OWN FIXTURE DISTINGUISHES THE REJECTED RULE.**

The order seal written for this pin used `risk_acceptance_high`, whose row declares
`[accepted, rejected, returned_for_rework]` — **already alphabetical**. `sorted()` and
pass-through produce the identical tuple, so the assertion could not tell the rejected rule from
the intended one. It passed, and it measured nothing. Mutation testing cannot find this: the
mutant and the original agree on that fixture.

`hazard_link_review` declares `[linked, new_hazard, dismissed]`, and **in the whole sample overlay
it is the only row that discriminates.** Most natural verb lists are alphabetical by accident,
which is precisely why this hides. The seal now asserts the discrimination itself, so
alphabetising that row later goes red rather than quietly restoring the vacuum.



**AND THE GUARD MUST BE ASSERTED OVER THE SAMPLE, NOT OVER ONE ROW** — `invincible-agent-28`'s
refinement, and it is the difference between fixing an instance and closing the class. Their rows
are **seven of eight** non-discriminating:

    risk_acceptance_{high,serious,medium,low}    accepted, rejected, returned_for_rework   ALPHABETICAL
    risk_acceptance_concurrence_{high,serious}   concurred, not_concurred, returned...     ALPHABETICAL
    pcn_disposition                              approved, rejected                        ALPHABETICAL
    hazard_link_review                           linked, new_hazard, dismissed             <- the only one

So an ordered assertion across those rows would have been **7/8 decoration**, read as coverage. A
guard naming `hazard_link_review` specifically would break the moment that row is renamed — *the
hand-kept-list shape one level up* (R-027). The guard therefore **walks every declared row and
requires at least one to be non-alphabetical**, so it keeps working as rows are added and reds when
the last discriminating one is tidied away.

**One innocuous reordering silently converts every ordered assertion in a file into decoration, and
nothing says so.** Nobody chooses alphabetical here: `accept` precedes `reject` in both meaning and
spelling. That is why it is everywhere and why it hides.

### The corollary's own corollary, found by `iagent-mesh-sdk-ca` the same hour

**The SDK's order arm was vacuous from the identical cause** — `[accepted, rejected,
returned_for_rework]`, already alphabetical — so **the arm asserting that composition preserves
declared order shipped decorative in the same commit as the feature it guards.** Two lanes, one
fixture mistake, independently. That is not coincidence: it is what "most natural verb lists come
out alphabetical by accident" predicts.

**A FIXTURE THAT MUST PROVE IT CAN FAIL BEFORE IT IS ALLOWED TO PASS.** Both seals now assert
`declared_order != sorted(declared_order)` before using the fixture.

**And the check of the check needed its own control.** ca's first counterfactual used `sed` to
restore the old fixture and reported a **RED** — which would have concluded the seal was fine and
needed no change. The `sed` had mangled the test: the red was **the instrument breaking, not the
fixture discriminating.** The clean check ran the model directly against both orderings.

> **A red is as capable of being wrong as a green**, and it is easier to forget, because a red
> feels like evidence. An instrument built to test an instrument is not exempt from needing its
> own control.

Cf. [[a-mutation-that-wont-die]] — the same asymmetry from the other side: there the surprise was
green where red was expected; here it was red where the red meant nothing.

### Two sites the same class cost on this pin

| miss | why no rebuild would have caught it |
|---|---|
| `values.yaml` `meshSdkVersion` | the domain broker pip-installs the SDK **at pod start** on stock `python:3.12-slim`, not the iagent image |
| 14 per-engine `uv.lock` files | the image build runs `uv sync --locked`; relocking the root alone fails every engine build at **image** time |

**The pin was sixteen sites and fifteen were found by hand.** Both misses were caught by seals.
Cf. [[a-sample-is-not-the-population]] — and R-027 below, where the same shape appeared *inside*
the seal written about it.

---

## R-027 — A hand-written COUNT of a population is a sample too

**Seal 13's staleness guard was the defect it guards.** The seal checks that a new engine is
registered at every site the registry packet lists, and it carried:

    assert "9" not in rows, "...add it here rather than letting the seal quietly under-report"

**A hardcoded count, inside the seal written about hand-kept lists**, instructing the next author
to edit a literal. It fired correctly when the packet grew from eight sites to ten — and the
repair was **not** `9` → `11`. It now parses the packet's site numbers and asserts a
`test_site_<n>` exists for each, so packet and seal cannot drift **in either direction**, and a
new site is red until it is *checked* rather than until someone *notices*.

**The rule: where a seal is derived from a source, its COMPLETENESS CHECK must be derived from the
same source.** A derived population guarded by a hand-written count has simply moved the sample
one level up — which is exactly what *"a derived population is only as complete as the thing it
derives from"* said, applied to the instrument instead of the subject.

Related: [[a-filed-defect-is-a-sample-not-a-census]], [[an-absence-assertion-is-worth-its-control]].

---

## R-028 — A seal that ASSERTS a dependency constrains MERGE ORDER, not just correctness

**Raised by `invincible-agent-28`, 2026-09-12, before either merge moved.** `lane/01` added a guard
to seal 6 asserting that the SDK v0.8.0 pin is present, because the ordered `accepts` comparisons
are meaningless without it. `lane/74` is still at v0.7.1. So:

    lane/74 -> master, THEN lane/01 (pin + locks + comparisons + guard, one commit)   SAFE
    both in one window, lane/01 second                                                SAFE
    74 pre-merges 01's test-file changes to settle the conflict early                 BREAKS

**The broken ordering is the tempting one**, because it removes the conflict soonest. It takes the
guard without the pin, so `lane/74`'s suite goes red **by construction** — and red *for the correct
reason*, which makes it indistinguishable from a real defect to anyone reading the run.

**THE RULE. A guard that asserts a precondition is a claim about the tree it lands in.** Before
moving such a file between branches, ask whether the precondition travels with it. If it does not,
the file cannot go first — no matter how convenient the conflict resolution becomes.

**The corollary is about the conflict, not the guard:** resolve at the merge of the branch that
CARRIES the precondition, never before it. Here that means the conflict in
`test_seal6_safety_kinds_compose.py` and `test_seal13_all_eight_registry_sites.py` is resolved when
`lane/01` merges, taking BOTH sides — the ordered comparisons and coupling guard from one, the
engine-extra split and discrimination guard from the other. They are orthogonal; neither supersedes.

**And one marking rule falls out of it.** In the split file, the ordered comparisons go behind
`requires_rdflib` because they parse; **the coupling guard is never marked.** It reads a version and
a type and needs no graph, and marking it would take it dark in exactly the deployment it was
written for — a root-venv CI run without the engine extra, which is precisely where a pin/comparison
mismatch would otherwise surface three tests down from its cause. *Over-marking shrinks the
always-runs half, which is the thing the split exists to protect.*


### What had ALREADY happened when this was filed — verified, not inferred

**`lane/74` reached master VIA `lane/01`, not by merging first**, and this ruling was written
describing an ordering that was already overtaken. `invincible-agent-28` caught it and checked the
right thing: **master's copy of the file, not the branch name.**

    94efdf6  "Merge remote-tracking branch 'origin/lane/74' into lane/01"   ancestor of origin/master
    f703774  the v0.8.0 pin                                                 NOT on origin/master

    master's pyproject pin              v0.7.1
    master's seal 6: set comparisons    PRESENT
                     ordering tripwire  PRESENT
                     ordered comparisons / coupling guard   ABSENT

**The dangerous combination this ruling names — guard without pin — did not occur**, because what
merged was an older `lane/01` predating `f703774`. Master is internally consistent at v0.7.1.

**THE RULING IS UNCHANGED AND STILL BINDING FOR WHAT REMAINS**, with the roles as stated: 74's
remaining commits carry no precondition and go first; `lane/01`'s carry the pin and go second. The
merge that already happened is not a counter-example to it — **it is an instance of the safe case
reached by accident**, which is the more dangerous way to be right and exactly why the ordering is
now written down rather than reconstructed each time.

**The check that settled it is the transferable part:** *branch names describe intent; file contents
describe state.* "`lane/74` is 22 ahead" and "`lane/74` is 2 ahead" were both true an hour apart,
and neither answered whether the pin and the guard were in the same tree. Reading master's copy of
the file did.

Cf. [[regenerate-then-stage]] — *a green belongs to a SHA, not a directory* — and R-025.

Related: [[a-guard-that-cannot-fire]] (the marked-dark case), [[prime-then-roll-then-read-the-edges]].

---

## R-029 — A seal that EXERCISES a function is not a seal that PINS its algorithm

**Measured by `invincible-agent-81` on ADR-0053 §7 step 1, 2026-09-12, and it corrects §7's stated
argument before the remaining four extractions inherit it.**

§7 justifies extraction-before-change on the grounds that *"the existing seal — written before
either change, already battle-tested — is the check."* For this verb **it checked nothing about the
unit being moved.**

Five mutations of the extracted module — sort by raw value instead of absolute, keep zero
contributors, annotate only the last row with the withheld tail, return `0` instead of `None` for an
undefined share, rank from `0`:

    every one reddened exactly ONE test, and always a test written in the same commit
    the standing seal stayed GREEN through all five

> **READ EVERY KILL COUNT IN THIS REGISTER UNDER R-056.** A mutation run proves
> **guard-is-RIGHT**; it can never prove **guard-is-REACHABLE**, because *the fixture supplies
> the triggering input.* A full kill sheet is half the evidence, and the half it omits is
> whether the world can produce the row at all. Pair every count with a trace of each half of
> the comparison back to its source.

It exercises the verb at two call sites and asserts its contract **shape**. It never asserted the
ordering, the zero-drop, the rank numbering, or the withheld tail — *which is to say, none of the
algorithm being moved.* **The green before and after was real and weak:** it proved the verb still
runs and answers in the declared shape.

**THIS DOES NOT FLIP THE ORDER — extraction-first stands. It replaces the reason.** Inheriting §7's
coverage claim is the error. The next extraction must **check what its seal actually asserts about
the unit**, and that is one command: mutate the unit, see whether the standing seal notices. **A
required step, not advice.**

### The instrument that did establish preservation, and why it is better than a seal

A purpose-built equivalence run: the pre-extraction function loaded from `git show HEAD:...`
alongside the new one, both over the same seed across the full matrix — 2 variance kinds × 2 levels
× 5 `top_n` values. **20 cases, 42 rows, byte-identical JSON, 0 diffs.**

**Equivalence against the code itself rather than against an assertion about it — and unlike a
seal's age, it does not decay.** Required instrument for the remaining four extractions.

### The seal-age field bit on its own first use

    seal_last_commit  803071e      seal_last_date  2026-09-02
    run_date          2026-09-12   -> TEN DAYS, in a tree 81 commits had landed in

**The number is what prompted the mutation** — ten days in a moving tree was enough to ask whether
the seal still pinned anything, and the answer was that it never had. Recorded as commands rather
than as a figure, per the ADR.

> **READ EVERY KILL COUNT IN THIS REGISTER UNDER R-056.** A mutation run proves
> **guard-is-RIGHT**; it can never prove **guard-is-REACHABLE**, because *the fixture supplies
> the triggering input.* A full kill sheet is half the evidence, and the half it omits is
> whether the world can produce the row at all. Pair every count with a trace of each half of
> the comparison back to its source.

### Scope held where it was tempting to widen

**No registry row was added**, and the package docstring says so rather than leaving it assumed.
§2 makes a module with no row *invisible*; that is true of this one. **Adding the row here would
make the green cover the conjunction — the error §7 exists to prevent, committed while following
§7.** The module's location under `finance_agent/measure_modules/` is mechanical (engine images
flatten `agent_fleet/<engine>/` to `/app`), stated so nobody reads it as architecture; the shared
location is §2's open question.

Related: [[a-mutation-that-wont-die]], [[a-stale-claim-is-pre-authenticated]], R-026(c).

---

## R-030 — A CONTROL MUST SHARE ITS SUBJECT'S GATE

**Ruled by the architect, 2026-09-12, from the v0.8.0 suite run.** The fourth costume of *the
instrument measured its own input*, and the sharpest, **because it would have filed a wrong
attribution against the lane that caught it.**

The suite came back 23 red. To partition mine from pre-existing, I ran master's own copies from a
`git worktree` under `AppData/Local/Temp`. That directory placement changed a **path-derived
precondition**: the tests resolve `doc-tools` relative to their own location, so the control looked
for a sibling that does not exist there.

    control (temp worktree)   2 passed, 50 SKIPPED
    subject (my tree)         failures

**Read naively, that says my branch broke them.** With `DOC_TOOLS_REPO` pointed at the same place
the subject resolves, master fails identically: pre-existing.

**THE RULE. A control differs from its subject in EXACTLY ONE variable — the one under test.** Mine
differed in *where it ran*, which is the one thing a control exists to hold fixed, and the
difference it manufactured pointed at my own branch as the cause.

**THE TELL IS A SKIP COUNT THAT DOES NOT MATCH.** *50 skipped* against a subject that ran those
tests is not a passing control; it is a control that measured a smaller thing. **Compare the RUN
count, not just the verdict** — a control and subject that disagree about how many tests executed
have not been compared at all. This is the same failure as a floor of 14 over 30 images being
unable to distinguish *all present* from *half missing*: the instrument's own scope moved.

**And the placement was not incidental.** A temp-directory worktree is the natural way to get a
clean copy of another ref, and it silently breaks every sibling-repo, relative-path and
untracked-fixture precondition at once. **When controlling with a worktree, assert the skip counts
match before reading the verdicts.**

Related: [[the-instrument-and-the-subject-share-a-surface]],
[[an-absence-assertion-is-worth-its-control]], [[a-sample-is-not-the-population]].

---

## R-031 — A live-model test reports a VERDICT FROM N RUNS, never from one

**Ruled by the architect, 2026-09-12.** A routing test backed by a live model that **passes on
re-run is neither a red nor a pass**, and three of them ride every suite run as coin flips that
read as regressions.

    three of three pass   -> PASS
    otherwise             -> FAIL
    a SINGLE-RUN failure  -> VOID, and the run count must be named in the output

**A void is not a pass and must not print like one.** The output says how many runs were taken and
what they were, so a reader can see the difference between *stable* and *not measured enough*.

**WHY A SINGLE RED IS NOT EVIDENCE HERE.** Determinism is a property these tests do not have.
Against a live model, one failure is a sample of size one from a distribution, and reporting it as
a regression is the same error as reporting one green as coverage — **[[a-sample-is-not-the-population]],
applied to repetitions rather than to rows.** The three observed on 2026-09-12
(`adr0019_engine_o_contract_a` ×2, `classify_route[procedure 1234]`) all passed on re-run in the
same tree that had just reported them red.

**THE COST OF NOT RULING THIS IS THE TRAINING EFFECT, and it is the same one the routing
port-forward guard was built against:** a suite that cries wolf teaches every reader to wave
through red, and **that acquired immunity is what makes the one real red invisible.** Three coin
flips per run is enough to establish the habit.

**This does NOT widen into "retry until green."** N runs with a stated rule, where anything short
of unanimous is a failure — not "best of three". A test that passes once in three is failing, and
the rule must never be able to convert a real regression into a void.

---

## R-032 — A STATUS IS A CLAIM ABOUT WHO HOLDS THE WORK, and a wrong one is MISROUTING

**Named by `invincible-agent-28`, 2026-09-12, from the sixteen-reds audit.** Sixteen reds on master
were carried as *"awaiting rulings"* for two days. **One of sixteen deserved the label.** 74's was a
one-line fix sitting behind a status that told everyone to leave it alone.

**A WRONG STATUS IS NOT MISLABELLING. IT IS MISROUTING.** The same shape as a register entry
crediting the wrong lane — which sends the next request to the wrong door. **`awaiting-ruling`
sends it to nobody**, which is worse: a misattribution reaches someone who can say *"not mine"*,
and a phantom blocker reaches no one at all.

    awaiting-ruling   ->  a decision-maker who does not know they hold it
    unassigned        ->  honest, and visible
    owned, open       ->  actionable

**So `blocked-on:` must name a PARTY, and a status nobody can be paged about is not a status.**
Before writing one, ask the question that settles it: *if this is still here in a week, whose
inbox should it have been in?* If the answer is "nobody's", the row is unassigned, not blocked.

### The audit that produced it, as a template

| kind | n | what it actually needed |
|---|---|---|
| live graph state | 7 | a prime, or a data fix |
| a source defect | 1 | one line, named owner |
| a resolver decision | 3 | the domain-scoping arc's fourth case |
| corpus decisions | 5 | the owning domain's answer |
| **genuinely a ruling** | **1** | the router choosing a verb when the subject did not resolve |

**Fifteen reds nobody is looking at is how a twenty-day CI silence starts.** The audit is cheap —
read each failure's own message — and it is the only thing that converts a wall of red back into
work with owners.

---

## R-033 — A DEFINITION'S BLEED CAN COME FROM A CITED VERB'S NAME, not from prose

**Found by `invincible-agent-28`, 2026-09-12, fixing their row of the sixteen. Filed because the
next author will not be looking for it.**

The seal `test_no_new_sibling_name_bleed_in_definitions` asks whether another class's **label**
appears in a definition's **text** — a definition is retrieval input, so naming a sibling hands
that sibling's questions to you. (`idp:Pipeline` won *"list the datasets in publog"* exactly that
way.)

**The bleed was not a sibling named in prose. It was a camelCase VERB NAME:**

    rdfs:comment  "Output of findOrphanedHazards: ..."
                                    ^^^^^^^^^^^^^^^^
                                    contains `Hazard` — safety:Hazard's own label

**Citing the VERB put the SUBJECT class's name inside the RESPONSE class's embedded text.** The
opening is house style, copied from a neighbouring class.

**The detail that makes it a ruling rather than an anecdote: lowercase `hazards` appears TWICE in
the same definition and matched nothing. The capital did it** — a substring match inside an
identifier, invisible to anyone reading their own file for a *name*.

**AND THE OTHER TWO RESPONSE CLASSES ARE CORRECT BY LUCK.** `assessDeferralRisk` and
`draftRiskAssessment` contain no class label as a substring. One of three fired; the other two
pass for reasons their author did not choose. **A green that depends on how a neighbouring verb
happens to be spelled is not coverage** — cf. [[a-mutation-that-wont-die]] and R-026's
alphabetical-fixture family, which is the same accident wearing different clothes.

**The repair is the precedent already in that seal**: provenance moves to a `#` comment and
`rdfs:comment` becomes a real definition. Same fix as the six build-notes cleared on 2026-08-15 —
moving them out removed the bleed **and** restored an actual definition, *because the two were one
authoring mistake seen from different angles.* Not grandfathered: `KNOWN_SIBLING_BLEED` is a
ratchet whose target is empty.

**Second defect in that TTL this week, after `@prefix mesh: <http://internal/mesh#>` with nine
citations on an invented predicate IRI. Both invisible to review; both caught by seals that read
the RESOLVED artifact rather than the text the author wrote.**

---

## R-034 — A `--set` IS AN INSTRUCTION, NOT A DECLARATION

**Ruled by the architect, 2026-09-12, from a regression I caused rolling `5fb7ae4`.**

My roll **deleted the `engine-lg` deployment.** The fleet went 17 services to 16, and the census
printed:

    OK: all 16 service(s) at 5fb7ae4...
    VERBS: 65 relationship type(s) live.  unchanged since the last snapshot.

**Every word true, and CLEANER than the run before it.**

**THE CAUSE, and it was not what it looked like.** Not a values merge, not a lost `$engines` row —
that row is intact, keyed `graphHost` rather than `engineLg`. Diffing the two releases gives
exactly one dropped key:

    present at rev 112, absent at rev 113:   graphHost.enabled: true

**It lived only in release 112's user-supplied values — passed once as `--set`, never written to a
file.** `upgrade-sandbox.sh` deliberately refuses `--reuse-values` so a value deleted from a file
cannot outlive the commit that deleted it. So the next render computed from the files, found
`enabled: false`, and deleted the deployment.

**THE RULE. A live deployment's existence is declared in a tracked file, or it is not declared.**
A `--set` **survives exactly one release and is invisible to every reader of the repo.**

**`--reuse-values` IS NOT THE FIX AND STAYS REFUSED.** It is the script's deliberate design, and
adopting it would trade this failure for the one it was written against: a stale declaration
outliving the commit that deleted it. The repair is the declaration, not the merge strategy.

### Why it failed at the maximum distance from its cause

**Registration PERSISTS in the graph after its host is gone.** So the verb count read `unchanged`,
and a question routing to `finProgramBrief` or `costLotCostingReview` still resolves, still picks a
verb, and **fails at DISPATCH** — with a clean census and an unchanged verb count standing behind
it. *A reader who checks the verb line for corroboration gets corroboration of the wrong thing.*

### The instrument half, which is the worse defect

**A report that gets CLEANER as its population shrinks is the worst instrument shape on the list.**
`OK: all 16` was true of all sixteen. The missing service left the denominator with it.

**The census now compares the PRESENT set against the LAST CENSUS'S set and names disappearances**
— the same exclusion-not-inclusion rule the verb snapshot already follows, applied to the roster. A
hardcoded expected-fleet list would make today's answer right and go blind the next time an engine
is legitimately added. It returns **3, never 1**: a retirement and a regression are
indistinguishable from there, so it is a *look at this*, not a verdict. Built and sealed with nine
assertions including the corrupt-snapshot control, because *None is not an empty list* and
conflating them would report every service as gone on a truncated write.

### Two errors of mine on the way, recorded because they are the reusable part

* **I grepped for `engineLg:` in `values.yaml`, found nothing, and let a NULL RESULT CONFIRM A
  CONCLUSION.** The key is `graphHost`. I reported the absence as *correct* in a message to another
  lane. [[names-fail-shapes-survive]] — spend verification on identifiers.
* **My settle loop passed on pod status `Running` while engine-lg was `0/1` READY** — the exact
  defect I had warned two lanes about that morning. Running is not Ready.

---

## R-035 — AN INVARIANT BETWEEN DECLARATIONS IS INVISIBLE TO EVERY PER-DECLARATION CHECK

**Ruled into the principles, 2026-09-12. The worked instance is `invincible-agent-81`'s cost
catalogue.**

    "how did the price build up"   declared a SYNONYM of cost_price_composition
                                   declared a SYNONYM of cost_category_breakdown
    "show the burden stack"        declared an ANTI-synonym of cost_category_breakdown
                                   ...the same question, in different words

**Each list was correct read on its own. The contradiction existed only BETWEEN them** — which is
why review never caught it, and why no amount of per-verb rigour could have. A phrase claimed by
two verbs decides nothing, so whichever subject wins chooses the answer.

**THE RULE: the seal has to quantify over PAIRS.** A check that walks declarations one at a time
cannot see a relation between two of them, however careful it is about each.

**AND THE PAIRWISE SEAL MUST RUN IN BOTH DIRECTIONS.** *Merely not claiming a phrase leaves it to
whichever subject wins* — so "A does not claim B's phrase" is half a check. 81's seals, derived
from `CATALOGUE` rather than listed: no phrase claimed by two verbs; no verb declaring a phrase as
both synonym and anti-synonym; the sharpest pair kept apart **in both directions**. Mutation:
restoring the duplicate reds 2 of 3.

**The related case is the class comment.** `cost:ProductionLot`'s `rdfs:comment` omits the price
walk **its own verb routes on** — and the comment is the artefact the classifier reads, so the
verb was unreachable through its own subject for its own primary question. **The corpus row is
written from the MEASURED answer after the comment is fixed, never before**: a row written from
what anyone expects the router to say is a guess wearing a baseline's clothes.


### State the IDENTITY; treat the CONFIDENCE as indicative

**`invincible-agent-81`, re-measuring on a restored and settled fleet.** The same three probes,
identical conditions, minutes apart:

    how does base cost build up to the price      CostCategory    0.86   (was 0.92)
    ... on lot 4                                  ProductionLot   0.97   (was 0.95)
    show the burden stack for lot 4               ProductionLot   0.90   (was 0.95)

**The subject identity is stable. The number is not — it moved by up to 0.06 between identical
runs on a healthy fleet.** The finding rests on *which class wins* and on *the flip when a lot is
named*; neither moved, so it stands.

**QUOTING THOSE TO TWO DECIMALS AS THOUGH THEY WERE PRECISE IS OVERCLAIMING**, and 81 flagged their
own. **A future reader diffing 0.92 against 0.86 goes looking for a cause that is not there** —
precision manufacturing a phantom regression. So: **record the identity as the claim and the
confidence as indicative**, and never seal a threshold against a number that moves this much
unless the threshold has been measured across runs.

This is [[an-authority-ranking-needs-a-scope]] one step earlier: before asking whether a score can
be compared across providers, ask whether it is stable against *itself*.

### Half of a mutual exclusion is a DIFFERENT rule that looks similar

81's sharpening, from building the seal rather than from finding the defect: removing a duplicate
synonym is not enough. **A phrase merely NOT CLAIMED by the neighbour is still available to
whichever subject wins**, so the neighbour must *actively push it away*. **Half of a mutual
exclusion is not a weaker version of it; it is a different rule that happens to look similar.**

**And the detail that makes this a law rather than an anecdote: the catalogue's own comment calls
that pair "the sharpest in the engine."** The author knew the risk, was looking straight at it, and
shipped it anyway — **because attention was on each declaration IN TURN.**

Principle filed by `invincible-agent-91` at `f0fd459` on `lane/91` — **not yet on master**, so it
is cited by COMMIT rather than by path. Citing the path directly turned `test_citation_paths` red
on master (found by `invincible-agent-f3`): **the ruling landed and the artifact it cites did
not.** Same split as a ruling naming a state it was formed against, in the other direction — and
the repair is the same, **name the sha**. Re-point this at the path when `lane/91` merges.

Related: [[every-endpoint-verified-the-join-unasserted]] — the same law found from the other side.

---

## R-036 — A LOCAL SKIP IS NOT A COVERAGE GAP; CHECK CI BEFORE CONCLUDING

**RETRACTED AND REBUILT, 2026-09-12. The instance this was going to be filed on does not exist,
and the retraction is worth more than the ruling it replaced.**

`doc-tools-7f` reported that `test_telemetry_mapping_truth.py` — the only check of a two-tier
telemetry contract — was silently SKIPPING, so a renamed key would emit nothing to Langfuse with
nobody watching. **The skip was real and the conclusion was false.** doc-tools' CI has a
`telemetry-contract` job that installs the leaf explicitly and runs exactly that test **as a
pre-build gate**, with `build-and-push` declaring `needs: telemetry-contract`. It ran on their push
and passed. **The contract has an owner: CI. A mapping drift cannot reach an image there.**

**THEIR NAMING OF THEIR OWN ERROR IS THE RULING:**

> **I measured the venv and concluded about the contract.**

**Which is the same move they had flagged in themselves the day before** — reasoning from a graph
NAME to a vocabulary NAMESPACE — *"in under a day, in the same report where I was pleased about
catching it."* An axis error does not feel like one from the inside: each step is a true
observation about the thing in front of you.

**AND I NEARLY ENSHRINED IT, THEN REPEATED IT.** I had drafted the ruling and swept my own suite
for instances — **using the same instrument that produced the false one.** My sweep found
`test_mesh_mapping_truth_check` RUNS here and theirs skips, and I wrote that up as an asymmetry.
**Both halves of that were about venvs.** We have the identical CI gate: a PR check that
`pip install`s the leaf and runs the test. *Two people made the same axis error about the same
contract, one after the other, and the second was looking for it.*

**THE RULE: a skip in a local venv is a statement about the venv. Before concluding that a
contract is unchecked, read CI** — a cheap pre-build gate installing one dependency is exactly
where a fast contract check belongs, and it will not appear in any local run.

### What the sweep DID find, and it is ours

**Ours is a STEP IN `lint`. There is no `needs:` anywhere in the workflow, so `build` and `lint`
run in PARALLEL.**

    doc-tools    build-and-push  needs: telemetry-contract   -> drift CANNOT reach an image
    ours         lint (step)     no needs:, 0 in the file    -> drift goes RED and the image SHIPS

**The check exists, runs, and gates nothing.** A red telemetry mapping produces a failed `lint` job
beside a successful `build` job, and the image is pushed and rollable — so the defect the check
exists to stop reaches the cluster with a red sitting next to it in the same run.

**That is the genuine instance, and it is the opposite direction from my first sweep**: doc-tools
is better protected than we are, and I had drafted it the other way round. **A check whose result
nothing consumes is a guard that cannot fire, dressed as one that does** — and unlike the usual
form, this one is *green-adjacent* rather than dark: it reports honestly to an audience with no
power to act on it before the artifact ships.

**Filed as work rather than fixed here**, because adding `needs:` to a 15-service build matrix
changes every push's critical path and that is a decision about CI cost, not a defect repair.

---


## R-037 — A SHA ON MAIN IS NOT A RUNNING IMAGE, AND A GATE MUST READ THE CODE

**Ruled from the doc-tools cleanup gate, 2026-09-12.** `doc-tools-7f` pushed the keyless-identity
writer fix (`a314a84`) and **refused to let the cleanup migration be gated on it**:

> *Between now and that image landing, the DEPLOYED emergency re-sync path is still the old
> writer. If the cleanup runs in that window, a re-sync can mint a fifth keyless edge into a graph
> you just cleaned — and your migration would have been correct and still left the defect present.*

**I checked, and the gate was UNSATISFIED.** The check that settled it is the ruling:

    the TAG        doc-tools:latest        identifies nothing
    the DATE       pod started 2026-09-10  two days BEFORE the fix — suggestive, not proof
    the CODE       /app/.../aitool_linker.py:310
                   "tool_urn": props.get("_tool_urn", "")     <- the two-state writer

**and the fixed source names that exact expression as the defect** — `# NOT .get("_tool_urn", "")`.

**READ THE CODE IN THE RUNNING POD.** A tag can lie by design (`:latest`), a date is
circumstantial, a digest is opaque without a registry lookup. **The artifact the process actually
loaded is the only thing that answers "is the fix deployed".** Same rule as reading the task-kind
gate's answer from inside the serving pod rather than from the local tree, which had been wrong
about the cluster twice in one day.

**AND THE PUSH ITSELF IS NOT THE BUILD.** 7f verified their image build had actually started
rather than assuming the push triggered it — on a documented precedent in that repo where a commit
reached main, **no build ever ran, no failure, no skip-ci marker**, and the feature read as shipped
while the stamp existed in no image. The workflow gained `workflow_dispatch` because the recovery
path was otherwise a fake empty commit. **Three separate facts, each of which can be true while the
next is false:** the commit is on main; a build ran; the image is deployed.


### FOUR facts, not three — `doc-tools-7f`'s addition, and they got the third one wrong in my favour

    1  the commit is on main
    2  a build ran
    3  the image reached THE REGISTRY THIS CLUSTER PULLS FROM
    4  the pod is running it

**Each can be true while the next is false**, and **(3) is invisible precisely because it is
usually the same registry.** 7f told me to gate on the Artifactory image, from a standing note that
turns out to be about the **d4 work cluster**. Verified from my side rather than assumed: context
`edge`, server `192.168.1.226`, namespace `sandbox`, **no d4 context configured here at all**. And
the live deployment reads:

    ghcr.io/edgy-solutions/doc-tools:latest   pullPolicy=Always

**No Artifactory hop on this path.** Had I waited on it I would have been waiting on a step that
does not exist for this cluster — *a correct-sounding gate on the wrong artifact hop is
indistinguishable from a gate that has not been met.*

### `:latest` UNDERSTATES it — the exact identifier already exists

I had this filed as *"the tag identifies nothing"*, which implies missing infrastructure. **It is
not missing. CI publishes BOTH, on every build** (`build-container.yml:374-376`):

    ${{ steps.meta.outputs.image }}:${{ steps.meta.outputs.version }}   # "latest" on main
    ${{ steps.meta.outputs.image }}:${{ github.sha }}                   # the exact commit

**An immutable, exact identifier is pushed for every commit and the deployment picks the mutable
one anyway.** So it is a one-line values choice, not an architecture change.

**AND THE CHART COMMENT IS THE TELL** — the same shape as the loud-guard family:

> *`Always` because `:latest` is mutable.*

**Someone SAW the mutability and compensated for its symptom instead of removing the cause.** A
pull policy that re-pulls constantly makes drift *fast* rather than preventing it — and it is
exactly what turned this gate check into archaeology: **reading source inside a running pod to
discover what is deployed, when a sha tag answers it from the outside.**

**That makes it R-034's class precisely: the tag is an instruction, the code is the declaration.**
With `:latest` the tracked file declares nothing about which code runs, and `helm get values` tells
a reader the same `"latest"` it said six months ago. **With the sha, the declaration IS the fact.**

### The consequence found an open red

`test_v02_cutover_diff::test_every_aitool_edge_has_required_properties` — four `mesh:` verbs as
`<no-tool_urn>`, missing `tool_urn` and `provider` — was filed as *"graph state, unassigned"* among
the fifteen. **It is this defect observed from the consuming side**, mechanistically matched to the
deployed `.get("_tool_urn", "")` from both sides of the code. **A red with no owner acquired one by
reading a neighbouring repo's fix** — which is R-032's argument in practice: a row's KIND is
derivable far more often than *"awaiting a ruling"* suggests.

---

## R-038 — A SHARED MECHANISM IS NOT NAMED AFTER ITS FIRST CALLER

**RULED 2026-09-12.** Source: architect, on the SDK's declaration composer. Governs
`iagent_mesh/declarations.py` and every future declaration family. Text routed by
`iagent-mesh-sdk-ca`; number allocated here per R-021.

**The boundary must be STRUCTURAL, not lexical.** The composer began inside `task_kinds` because
task kinds were the first family to need it. Parameterising it *there* would have worked and
would have been wrong: the next family writes `from iagent_mesh.task_kinds import compose` and
**correctly infers a dependency that does not exist.** Decisions are not a kind of task, and the
import line must not say they are.

**This is the same law as a domain name in a platform seed, and it belongs beside it.** In both
cases a comment insisting the thing is generic is a **lexical** boundary; having nothing
domain-shaped to import is a **structural** one.

**The shape:** `declarations.py` holds the mechanism; families delegate with unchanged signatures.
**The seal:** the shared module imports NO family, and no family's suite imports another family's
module — both asserted **from the syntax tree, not by substring scan**, because the forbidden name
legitimately appears in prose.

**THE PROOF THAT IT IS SHARED RATHER THAN BORROWED IS A TEST FACT:** *the new suite imports
`task_kinds` nowhere.* Keep that asserted — if the decisions suite ever needs `task_kinds` to
exercise the composer, **the extraction did not happen, it was only renamed**, and nothing else
would say so.

*A fourth composer is refused by name in the ADR-0039 amendment; this is what makes that refusal
structural rather than a rule people follow.*

### As shipped in v0.8.1, and the names are not what the dispatch said

Verified against the published wheel rather than the description:

    compose_rows(seed_dir, overlay_dirs=(), *, key_field, builder, label=..., error=...)
    load_rows(directory, *, key_field, builder, label=..., error=...)
    read_rows(directory, *, key_field, error=...)

**The dispatch called it `compose(...)`; the shipped export is `compose_rows`.** The *argument* was
right and the *name* was wrong — [[names-fail-shapes-survive]], and the reason to check a
published artifact rather than the message announcing it. `task_kinds.compose` and
`load_task_kinds` keep their exact signatures and delegate, so the pin is the only thing that moves.

---

## R-039 — A COMPOSED DECLARATION NEEDS A READ PATH, OR ITS ONLY CONSUMER IS THE ERROR HANDLER

**RULED 2026-09-12.** Source: architect, from a gap Lane 1 found in its own work. Governs every
composed declaration family: task kinds, graphs, decisions. Text routed by `iagent-mesh-sdk-ca`.

**A declaration made authoritative and exposed nowhere is reachable only by getting it wrong.**
Measured: `verbs_for_kind` appeared once in the gateway, **inside the refusal body**, so a client
could learn a species' menu only by POSTing a verb and being told it was invalid.

> **A declaration whose only reader is the code path that rejects you is not a declaration. It is
> an error message with a schema.**

**Every composed family ships a read surface.** The worked instance is Lane 1's `/task_kinds`
endpoint plus the per-row `declaration` on `/me/human_tasks` — two surfaces, because they answer
different questions: a row serves a queue that *has* tasks, and the endpoint serves a filter, a
legend, or an **empty** queue where no row exists to carry it.

### Why this is worse than an inconvenience on a decision surface

**ADR-0034 archives decision records.** Probing to learn a menu therefore **writes attempted
decisions nobody made** — so discovery-by-failure does not merely annoy the client, it pollutes the
archive that the whole disposition arc exists to keep trustworthy.

### The read path inherits the invariants, and must be checked separately

The first implementation returned the kind-blind global set, so an undeclared kind came back
`accepts: []` with `reason_required: ['accepted', 'acknowledged']` — **two verbs required to carry
a reason on a species that accepts nothing.** A rule that can never fire, served as contract.

`test_reason_required_is_a_subset_of_accepts_on_every_safety_row` was **green throughout**: it reads
the DATA and the read path serves a PROJECTION of it. **An invariant true of a source is not
automatically true of every projection of it** — so re-assert it at the surface, do not inherit it.

---

## R-040 — A COMPUTATION SMUGGLED INTO DATA THROUGH STRING INTERPOLATION

**RULED 2026-09-12. The worked instance is ADR-0039's own clause, broken by its own author three
files later, in good faith, while holding the rule in mind.**

`safety_acceptance_direct` and `safety_acceptance_with_concurrence` name the placeholder
`{level_lower}`. There is no such fact. **It is `level`, lowercased — a transformation performed
inside a template**, which is exactly what ADR-0039 forbids one clause earlier:

> *A condition on something no engine has measured is a VERB TO WRITE, not a formula to add.*

**Interpolation is the side door.** A gateway is visibly a branch and gets refused; `{level_lower}`
looks like a field name. **The rule was written against computation in TABLES and the computation
arrived in TEXT.**

**THE FIX, RULED: the engine emits `risk_level_slug`; the definition interpolates a fact.** One
measure, and the reviewer stays a process owner. Binding `hazard_id` and `level` is the ordinary
half — `config_bindings()` or the trigger; `{level_lower}` is the half that carries the ruling.

**WHY THIS IS RECORDED BESIDE THE CLAUSE RATHER THAN AS A DEFECT.** It is the exact shape the
OpenDDIL pushback will take — *"just let the table compare two numbers"* — and **the author of the
rule broke it first.** That is not a criticism; **it is the strongest argument for the rule.** A
constraint its own author violated within three files, deliberately holding it in mind, is a
constraint that needs a **seal** rather than a paragraph.

**The answer to the pushback, which belongs in the document rather than in a meeting:** the moment
a table computes, its rows stop being reviewable as **policy** and become reviewable as **code**,
and the reviewer changes from a process owner to a developer. A verb emitting
`deadline_missed: true` costs one measure and keeps the reviewer.

**Caught by `test_placeholder_binding`**, whose message already had the diagnosis: *a DEPLOYMENT
defect, not a per-notice one — every run of this definition fails identically.*

---

## R-041 — THE FIXTURE-THAT-CANNOT-FAIL, ALL THREE INSTANCES IN ONE DAY

**R-026's corollary has now appeared three times in three different contexts, found by three
different sessions. Listed together because the shape is only obvious across them.**

| # | fixture | why it could not fail | found by |
|---|---|---|---|
| 1 | `risk_acceptance_high`'s `[accepted, rejected, returned_for_rework]` | **already alphabetical**, so `sorted()` and pass-through return the identical tuple | `invincible-agent-65`, then the same vacuum independently in the SDK, then **seven of eight** rows in the safety overlay |
| 2 | an S3000L-only fixture for `derived` vs `authored` labels | **zero authored labels present**, so a rule marking EVERYTHING derived passes | `doc-tools-7f` |
| 3 | a decision table's `domain` derived from its own rows | every table is **total by construction** | ruled here, built into `policy/decisions/` before the first row |

**NONE OF THE THREE IS FINDABLE BY MUTATION**, and that is what unites them: **the mutant and the
original agree on that fixture.** Mutation testing answers *"can this test tell a change?"* — it
cannot answer *"can this test tell the change it was written for?"*

**THE RULE, RESTATED AS A CHECK YOU CAN ACTUALLY RUN: a seal that defends a choice must assert
that its own fixture DISTINGUISHES the rejected rule** — in the seal, not in the reviewer's head:

    assert declared_order != sorted(declared_order)     # the order fixture
    assert any(row.label_source == "authored")          # the derivation fixture
    assert domain_values > row_values                   # the totality fixture

**And the cause is the same in all three: the vacuum is the NORMAL case.** Most natural verb lists
are alphabetical by accident. Most S3000L classes genuinely lack labels. Most tables' rows do
mention every value someone thought of. **Nobody chooses the degenerate fixture; it is what you get
by reaching for the nearest real example**, which is why "use real data" is not protection here.

---

## R-042 — A MISSING OVERLAY COMPOSES TO SILENCE

**RULED 2026-09-12**, from the `WORKFLOW_DEFINITIONS_DIR` overlay list, and it generalises the
task-kind path's lesson to every composed search path.

**Composition over an absent directory contributes nothing and raises nothing.** The platform
definitions still resolve, every probe is green, the service is healthy — **and a programme's
tailoring is simply not there.** The failure is indistinguishable from a correct single-entry path.

**So the witness must report EVERY directory, including the ones that do not exist.**
`describe_registry` now returns `{"path": ..., "exists": bool}` per entry plus the composed
inventory, and the not-found error names every directory searched — because once there is a search
path, *"not in `<dir>`"* is a true statement answering the wrong question: **a missing overlay and
a misspelled id produce the same message.**

**AND IT EXTENDS THE POD-READ DISCIPLINE BY ONE STEP.** The sequence was: settle, then read the
answer from inside the serving pod. It is now:

    1  settle — terminating count AND non-running count, and READY is not Running
    2  is the OVERLAY DIRECTORY actually in the image?
    3  is the env var set in the pod?
    4  read the gate's own answer from inside the pod

**(2) is the silent one and therefore goes first** — the rule from the rolling runbook: *when two
conditions can each produce the same failure, check the one that fails silently first.* Step 3 is
loud and will announce itself whenever you reach it.

---

## R-043 — A MUTATION UPSTREAM OF BOTH THE SUBJECT AND ITS EXPECTATION CAN NEVER RED

**RULED 2026-09-12**, from the M3.3 parity seal. The general form of a mutation that looked like
a survivor and was never a test.

To check that a card renders verbs **in declared order**, the mutation applied was *re-sort the
declaration*. That fed the card the sorted list **and** compared it against the sorted list:

    declaration ──┬──> the card renders it
                  └──> the expectation is read from it

    a mutation HERE moves both arms together.  Green, always, on any implementation.

**THE MUTATION THAT MEANS ANYTHING IS ON THE SUBJECT ALONE** — mutate the *card's* ordering, hold
the declaration fixed, and a sorting card reds against an order-preserving expectation.

**WHY IT IS CONVINCING AND THEREFORE DANGEROUS.** A mutation that produces green reads as *"the
implementation is robust"* or *"this survivor needs investigation"* — never as *"I mutated a shared
input."* It arrives wearing the clothes of a result, and the instinct it triggers is to look harder
at the code rather than at the experiment.

**THE CHECK: trace the mutation point to every arm of the comparison. If it reaches more than one,
the experiment is void — not negative.**

Same family, now four members:

| instance | what moved together |
|---|---|
| a fixture indistinguishable from its subject | the expectation *was* the subject |
| a test that reconstructs the merge inline | the test recomputed what it was checking |
| a control worktree that changed a path-derived gate (R-030) | subject and control ran different populations |
| **this** | the mutation fed both the render and the expectation |

### It arrived alongside R-041's third context, in the place R-041 predicts

**Every deployed `APPROVAL_TASK` declaration is alphabetical by accident**, so across the whole
population **a sorting card and an order-preserving card are indistinguishable** — and *"rendered
order equals declared order"* was green having measured nothing.

**The fix is a CONSTRUCTED control: a declaration that asserts it differs from its own sorted form
before anything else is asserted.** Not a found example — a built one, because the found ones are
degenerate. **That is what SDK v0.8.0's tuple was cut to make meaningful**: order can only be
preserved if something in the fixture would notice it being lost.

**The vacuum was the normal case, again.** Cf. R-041 — three contexts before this one, and each
time the nearest real example was the degenerate one.

---

## R-044 — A STALE VENV PRODUCES FINDINGS SHAPED EXACTLY LIKE REAL ONES

**Found by `invincible-agent-f3`, 2026-09-12**, and it is a fleet hazard rather than one lane's
accident.

Their worktree's venv held `iagent-mesh` **0.5.0** while `pyproject.toml` pinned **v0.8.1** in two
places. Thirteen task-kind declaration tests failed on a missing `iagent_mesh.task_kinds`.
**Every one of those failures looked exactly like a real defect in newly landed code.**

> **THE TELL IS THAT IT ACCUSES THE NEWEST CODE IN THE TREE.**

That is the diagnostic, and it is the only one available cheaply — because the failure mode is
*correct behaviour against the wrong artifact*. `uv sync --extra agent-fleet` cleared all thirteen.

**WHY IT IS WORSE THAN AN ORDINARY ENVIRONMENT PROBLEM.** A missing dependency fails by IMPORT and
names itself. A **stale** one fails by ABSENCE OF A SYMBOL — indistinguishable from a symbol that
was never written, or was just deleted by the change you are examining. **The investigation it
invites is code archaeology on innocent code**, and the more recently that code landed, the more
plausible the accusation.

**Cf. [[a-scope-that-looks-local-and-is-not]]** — a partial `uv sync` in a shared venv, and the
same class from the other end: there the sync narrowed what was installed, here it left something
old behind. **Both fail by making the tree and the environment disagree while only the tree is
under review.**

**The cheap check before believing any suite result that accuses recent work: confirm the
installed version matches the pin.** One command, and it is the same discipline as reading the
code in the running pod rather than the tag.

---

## R-045 — A DECLARATION IN AN UNPRIMED FILE IS THE FAIL-BY-PASSING CASE

**Ruled from `invincible-agent-f3`'s slice-1 grounding, 2026-09-12.**

ADR-0037 §1 sketched a sibling `mesh_docs.ttl` for the `mesh:DocPage` terms. **They put them in
`mesh_system.ttl` instead, and the reason is the ordering requirement made concrete:**
`mesh_system` is the **sole MESH-domain entry in `CANONICAL_TTL_MANIFEST`**, so it primes. **A
sibling primes only once a manifest row exists** — and until then the terms are declared in a file
nothing reads.

**THE SEAL ASSERTS BOTH HALVES: the terms are declared, AND their file is in the manifest.**
Asserting only the first is the vacuum: the declaration is present, the seal is green, and nothing
is in the graph.

### The fourth prefix instance, caught with the population still at ZERO

**`docs:` was an unregistered prefix** — declared in no TTL and in none of the three Python prefix
tables — while five pages already carried `iri: docs:runbook-…`.

**An unknown prefix is passed through VERBATIM by design.** So every page IRI would have been
stored **compact**, missed the linker's `MATCH` against full-IRI `:OntologyClass` nodes, and
registered **accepted-and-unreachable.** Nothing red.

**`agent_fleet/utils/mesh_registration.py` carries the post-mortems of this shipping three times in
its own table** — `fin:`, `cost:`, and the 2026-08-21 compact-vs-full bug. **This is the fourth,
and the first caught before a single row existed.** Being late would have cost five invisible rows
instead of one.

**f3 asserted the EXPANSION by running it, and the PASS-THROUGH too** — because pass-through is the
mechanism every one of the four instances rode in on. *Sealing the repair without sealing the
mechanism leaves the next prefix free to do it again.*

---

## R-046 — REFUSING A FEATURE IS A DELIVERABLE WHEN THE REASON IS RECORDED

**`invincible-agent-f3` on the literal-property question, 2026-09-12, and the shape of the refusal
is the reusable part.**

**The argument FOR the feature was sound and is not what decided it.** A literal mints no IRI, so
it cannot dangle — true, and irrelevant. **What decides it is that the literal has no GATE:**

    an `explains` IRI       goes RED when it stops resolving
    a literal naming a
    renamed test            keeps reading as TRUE

**A fact with no gate is a stale claim waiting to happen** (R-025), and the join it would have
bought is already served by `git grep`, since seal names live in the same repo as the pages.

**AND THE APPARENT EXCEPTION IS THE WEAKEST INSTANCE, WHICH IS WHY IT DOES NOT REOPEN IT.** The
cross-repo case looks like the one that needs a literal — and it is precisely where the literal is
**least verifiable from here**, so what it actually wants is a contract test. *An exception that is
weakest exactly where it is most tempting is not an exception.*

**Recorded on the page with its reason**, which is what makes it a deliverable: the next author
stops re-deriving a decision someone already made, and can overturn it on the reasoning rather than
on the absence of any.

---

## R-047 — REGISTERED IS NOT PARTICIPATING, AND THE THIRD MECHANISM IS PATH ARITHMETIC

**Found by `invincible-agent-81` on the live cost engine, 2026-09-12, and verified independently
in the pod.** The third distinct way a verb can be registered, healthy, sealed, and **never once
callable where it is registered.**

    /app/scripts   No such file or directory
    /app/dist      No such file or directory

    pathlib.Path('/app/measures.py').resolve().parents  ->  ['/app', '/']
    parents[2]                                          ->  IndexError: 2

**The image flattens `agent_fleet/cost_agent/` to `/app`, so `/app/measures.py` has exactly two
parents.** In the repo the identical line resolves to the repo root and works perfectly — **which
is why every test passes and why this was invisible.**

**AND THE PATH IS ONLY THE FIRST HALF.** Line 757 exists to put `scripts/` on `sys.path` for the
builder, and the builder — **~1,300 lines across a script, a template and a dataset builder** — is
not in the image at all. **The verb's implementation lives outside the container it is registered
in.**

### The three mechanisms, and why the count matters

| # | verb | mechanism |
|---|---|---|
| 1 | Engine F | a payload field |
| 2 | the walk's | a **shadowed** guard |
| 3 | `package_export` | **path arithmetic correct in one layout and impossible in the other** |

**Three different causes, one symptom: nine verbs registered, `/health` green, every seal green,
and one of them unreachable.** A registration is **a claim about reachability that nothing was
checking** — and each time the claim failed by a route the previous fix did not cover, which is
why "registered is not participating" has to be a standing question rather than a fixed list of
checks.

**THE TELL IS A CORRECTNESS THAT DEPENDS ON LAYOUT.** `parents[2]` is not wrong; it is right in
the repo and impossible in the image. **Any expression whose meaning is a function of where the
file sits is a candidate**, and the test suite runs in the layout where it works — so the suite
cannot see it *by construction*, exactly like a control that changes a path-derived gate (R-030).

### The hash that describes an intention rather than an artifact

**The round-trip seal specified for this export required a hash that did not exist.** `locator` is
`content_hash(body)` — a hash of the package **body dict, built from state.** The HTML is written
separately with `dest.write_text(html)`, and **no hash is ever taken of the written file.**

> **The response's hashes describe what the engine INTENDED to write.** A truncated or
> partially-flushed file would report success with a hash computed from memory, and nothing
> anywhere would notice.

**So the repair is a hash of the artifact AS WRITTEN, re-read from disk** — and only then does a
round-trip assert anything. **That is the difference between *wrote a file* and *wrote the file it
says it wrote*,** and it generalises to every manifest this fleet emits.

### A dispatch of mine carried the false premise

I wrote *"`package_export` already builds the 17.6 MB HTML with the `.duckdb` beside it."* **True
in the repo, from a script. Never true of the engine.** I passed on a capability claim without
checking **where it ran** — the same axis error as measuring a venv and concluding about a
contract, and the reason a capability claim must name the process it was observed in.

*(The `.duckdb` half refuses even in the repo — `duckdb` is not installed and is not a declared
engine dependency. That refusal is DESIGNED and carries a clear message, and is not part of this
defect.)*

---

## R-048 — ON A LANE BRANCH IS NOT ON MAIN: the zeroth fact

**`doc-tools-7f`, 2026-09-12**, and they named their own error precisely: *"I wrote that the
converter **exists** while knowing perfectly well I had just pushed it to a lane branch — I had
the fact and still drew the wrong conclusion from it."*

    0  the code is on a LANE BRANCH
    1  the commit is on MAIN
    2  a build ran
    3  the image reached the registry THIS CLUSTER pulls from
    4  the pod is running it

**A prime does not read lane branches.** So a manifest row landing against code that exists only
on a branch points at an artifact no primed deployment can see — which is exactly what
`invincible-agent-f3` held the `DOCS` row back to avoid.

**AND THE ZEROTH IS THE ONE MOST LIKELY TO BE SKIPPED, PRECISELY BECAUSE THE PERSON WHO PUSHED IT
CAN SEE THE CODE.** 7f's observation and the reason it belongs at the front: facts 1–4 are checked
by people looking for a deployment; fact 0 fails for someone looking at their own editor. **The
artifact is on their disk, so "exists" is true of their world and false of everyone else's.**

**The check is the same one as every other step: read `origin/main`, do not take the report** —
including from the author, and it is not a comment on their honesty. 7f asked me to verify it that
way rather than on their word.

---

## R-049 — A TWO-QUESTION PROBE CAN STILL ASK THE SECOND QUESTION WRONG

**`doc-tools-7f` writing the existence check, 2026-09-12 — the confident false negative reappearing
one layer beneath its own fix.**

`invincible-agent-f3` established that an `explains` target may be an `:OntologyClass` **node** or a
**relationship type**, and that a class-only probe reports the relationship-typed half as dangling
**with total confidence.** The obvious repair is to ask both questions. **The obvious way to ask the
second one is wrong:**

    Neo4j relationship types CANNOT CONTAIN COLONS.
    So aitool_linker stores the full namespaced IRI as `r.iri`
    and uses the LOCAL NAME as the type.

    MATCH ()-[r]->() WHERE type(r) = $uri     compares a LOCAL NAME against a FULL IRI
                                              -> finds nothing, every verb "dangling"

**So a probe that asks both questions still reports every relationship-typed target as missing** —
and it *looks* like a correct two-question probe, which is worse than the single-question version
it replaced. Keyed on `r.iri`; a mutation swapping in `type(r)` reds it.

**THE DOUBLE MODELS THE TWO ANSWERS AS INDEPENDENT SETS, NOT ONE BOOLEAN**, and that is the part
that generalises: *a double returning a single boolean cannot express "exists as a relationship,
not as a class" — which is the exact state that breaks the single-question probe.* **A fixture that
cannot represent the bug cannot catch it.** 7f says they would have written the simpler double
first had the 8/8 split not named the state.

**And the refusal returns both answers rather than collapsing them**, because *"not found" is only
trustworthy when the reader can see what was looked for.* A dangling refusal that does not name
both lookups is indistinguishable from a single-question probe reporting a real target. A test
refuses a message that omits either.

**R-015 holds at this layer too and is asserted rather than argued:** an edgeless page issues no
queries at all, so it cannot be refused by a graph that is empty or unreachable — sealed with
`session.run.assert_not_called()`.

---

## R-050 — AN IDENTITY CLAIM IS WORSE THAN A STALE STATUS, BECAUSE IT IS THE ROUTING KEY

**`invincible-agent-28` [09c0fb], 2026-09-13**, volunteered against themselves.

They had told the fleet *"address me as `invincible-agent-74`"* — **true when written, false after a
restart**, and carried forward for two days because **an identity was asserted once and never
re-derived.**

> **A stale status misdescribes work. A STALE ADDRESS MEANS THE CORRECTION NEVER ARRIVES.**

That is the difference in cost. Every other stale claim this week degraded a decision; this one
degrades the **channel** — and a channel failure is silent to both ends, because the sender sees a
successful send and the recipient sees nothing at all.

**`ListAgents` re-derives it in one call**, so carrying an asserted identity forward is a *choice*,
not an absence of means.

### And it is the argument for the roster's key — durability, not uniqueness

**Ratified 2026-09-13: the roster row is keyed on WORKTREE and BRANCH; the address is an
ATTRIBUTE. Where two sessions answer to one name, the row carries the ref and every send uses it.**

**The collision was the evidence; the rename is the reason.** `ia-74`/`lane/74` identified that
lane correctly **straight through a rename that made their own stated address false.** Uniqueness
would have been satisfied by any fresh key. **Durability is what a routing key actually needs**,
and the worktree had it while the name did not.

---

## R-051 — A RULE BINDS THE NEXT SEND, NOT THE NEXT ROSTER EDIT

**Demonstrated by me, 2026-09-13, in the act of ruling it.**

I wrote *"dispatch to the bare name is ambiguous today; I will use refs for both of you"* — **and
sent it to the bare name.** It reached the wrong lane: a dispatch about Engine O's work delivered
to the safety lane, **misrouted by the ambiguity it was ruling on.**

> **A rule that takes effect when a table is updated does not apply to the message announcing it.**

**The gap is between deciding and recording**, and it is exactly where a rule feels already-in-force
to its author. The author has *made* the decision, so the world feels changed; nothing has changed
until the next action conforms.

**So a ruling states which ACTION it first binds, not which artifact it will appear in.** The
cheapest form: **apply it to the message carrying it.** If a rule cannot be obeyed by the sentence
announcing it, that is the first thing it cannot do.

Related: [[a-stale-claim-is-pre-authenticated]], R-032 (a status is a claim about who holds the
work), R-050.

---

## R-052 — A NEGATIVE FROM ONE SEARCH PATTERN IS NOT A NEGATIVE, AND TWO SEARCHES SHARING A FLAW READ AS CORROBORATION

**SEVENTH instance of one component being concluded absent**, and the second and third were mine and `invincible-agent-f3`'s within an hour of each other.

**The component:** `doc_tools/definitions.py:70`, `ontology_sensor` — **factory-constructed** as an
`S3SensorComponent`, not decorated. Verified:

    grep '@sensor' doc_tools/definitions.py   ->  0
    grep 'S3SensorComponent'                  ->  4 (pdf, sustainment, ontology, +import)

**A grep for `@sensor` DECORATORS reported "no ontology sensor exists" while this sensor was
defined and configured.** And AGENTS.md records the sharper half: **the confirming second search
reused the same decorator pattern**, so *two verifications with one shared flaw read as
corroboration.*

> **A second search that shares the first's assumption is not a second search.** It is the same
> search run twice, and its agreement is evidence of nothing except that the pattern is stable.

**MY OWN INSTANCE, AND WHAT SAVED IT.** I read `src/iagent/definitions.py:31` and found
`sensors=[_ers.extraction_review_sensor]` — **correct about that file**, and I reported it as *"I
could not confirm the behaviour you asked me to vouch for"* rather than as *"no such sensor
exists."* **That phrasing is the only reason it was not the third instance.** f3 then checked
rather than accepting a clean negative, and found it in the repo neither of us had looked in.

### What the source proves and what it does not

**Defined, and its configured bucket. NOT running** — that is a runtime question settled by
`DagsterInstance.all_instigator_state()`, and AGENTS.md says so because over-reading a source
finding is the recorded lesson attached to this very component.

### The hazard was LIVE, not architectural

    prefix=""           every object in the bucket
    filter_patterns=[]  no filtering at all
    target_op           ingest_ontology_to_jena

**So a markdown page landing in that bucket is handed to a TTL parser**, and the only thing
between it and the parser was the undeclared-domain refusal. f3 had already moved page bodies to
their own bucket on the principle that **a refusal is not a router** — *without knowing the sensor
existed*, which is the property that made the decision right either way.

**A DECISION THAT DOES NOT DEPEND ON THE ANSWER IS WORTH MORE THAN THE ANSWER.** Relying on the
refusal would have been correct only for as long as someone else's guard kept firing — and an
absence of complaints is also what a disabled sensor produces.

Related: [[a-plausible-negative-is-not-a-considered-one]], [[a-filed-defect-is-a-sample-not-a-census]].

---

## R-053 — A SEAL THAT MOVES AND IS NOT RE-PROVEN HAS ONLY BEEN RELOCATED

**Architect-ruled 2026-09-13 out of the ADR-0051 thread; text and evidence routed by the safety
lane, number allocated here per R-021.**

Drawn from moving `tests/safety/test_concurrence_precedes_acceptance.py` off engine code onto the
composed decision tables.

**THE LOUD FAILURE IS THE SAFE ONE.** A seal left pointing at deleted code errors, and errors get
fixed.

**THE DANGEROUS ONE IS THE SEAL REWRITTEN TO THE NEW SUBJECT THAT PASSES IMMEDIATELY.** It passes
because **the new data is correct today**, not because the assertion can discriminate at the new
address. Those are different facts and only one of them was ever demonstrated.

**And the mutation suite that proved it becomes decorative in the same move.** Its discrimination
was shown against the OLD subject by mutations that **patch a Python name** — and a Python-name
mutation **cannot fail against YAML**. So after the move the assertion is unmeasured and the
mutations cannot fire, **while the file reads exactly like a proven seal**: green test, green
mutation run, same name, same intent.

> **Re-prove at the new address, with mutations that can reach the new subject.** A mutation that
> could not have applied is not a surviving mutant — it is an experiment that never ran.

Cf. R-043 (a mutation upstream of both arms), and the instance where a `sed` that never applied
produced a green indistinguishable from a survivor.

---

## R-054 — CHOICE REMOVED FROM CODE BEFORE ITS TABLE COMPOSES IS CHOICE DELETED, AND IT FAILS PERMISSIVE

**Architect-ruled 2026-09-13; routed by the safety lane, numbered here.**

Moving a decision from engine code onto the definition rail is **two edits, and their order is
load-bearing.**

**Reversed, no layer holds the choice — and the system does not fault.** Deleting a branch does
not produce an error; it produces **the branch's other arm taken unconditionally.**

**For ADR-0051 that window turns every Serious and High acceptance into a DIRECT one:**

    no exception. no log line. no red suite.
    MIL-STD-882E §4.3.7 violated, and the artifact left behind LOOKS COMPLIANT.

**THE GENERAL FORM: when a decision moves between layers, the new layer must be LIVE AND ASSERTED
before the old one is removed** — because **the intermediate state is not "broken", it is
"permissive", and permissive states pass every test written to catch broken ones.**

That is the whole hazard in one line. A test suite is built to notice absence and error; it is not
built to notice that a gate now says yes to everything. **The seal has to assert the gate REFUSES
something**, not merely that it runs.

Related: [[a-guard-that-cannot-fire]] — the WEAKENED form, where the guard runs, its premise is
true, and it answers a weaker question.

## R-055 — THE OTHER HALF OF R-054: THE INTERMEDIATE STATE CAN FAIL ABSENT, AND ABSENCE HAS NO SURFACE

**Architect-ratified 2026-09-14, on Lane 1's measurement, as a correction to the architect's own
ruling.** The ruling given was "split `eligibility_excluded` into `flags` and `excluded`". What
shipped was ADDITIVE — `flags` emitted, `excluded` left whole — and the architect ruled the
amendment better than the original *for the reason it was measured*.

R-054 names the order and one failure mode. This is the second mode, and it inverts the remedy.

**R-054's intermediate state is PERMISSIVE: a gate says yes to everything.** The seal answers by
asserting the gate REFUSES something.

**This one is ABSENT: a fact stops reaching the surface that explains it.** No gate opened. No
arm was taken unconditionally. A row simply stopped being rendered, and *there is nothing to
assert against* — the producer's tests pass because it emits correct data, and the consumer's
tests pass because it correctly renders what it is given.

WHAT WAS MEASURED. `eligibility_excluded` carries rows the arity gate KEPT (`disposal:
"flagged"`) since the H06 ruling of 2026-09-04 stopped it excluding. So a live candidate renders
under a key whose name says it was deleted. Narrowing the producer is obviously right — and
`cortex-ui`'s `readExclusions` has **no `disposal` awareness at all**, and its own comment
records the recent fix for arity rows *being silently discarded there*. Narrowing first would
have re-opened that identical defect **from the producer's side**: the same row vanishing from
the same panel, whose only job is explaining an empty card.

**MISLABEL IS VISIBLE; ABSENCE ISN'T.** A reader who sees "excluded by arity" on a live candidate
can question it, and one day will. A reader who sees nothing has no thread to pull — and neither
end is wrong, so neither end gets a bug report. That is the whole trade, and it decides the order.

**THE RULE.** When a field's MEANING splits across a producer/consumer boundary:

1. The producer emits the new shape **additively**. Both keys carry the rows.
2. The consumer reads the new shape and stops reading the old.
3. **Only then** the producer narrows.

**AND THE TEMPORARY STATE CARRIES ITS OWN EXPIRY.** A seal asserts the producer has *not* narrowed
yet, stating why, and naming itself as the assertion to delete when step 2 lands. Without that,
step 3 is a good idea somebody has in six months with none of this context — which is how the
consumer's original discard defect got written in the first place.

    test_THE_SPLIT_IS_ADDITIVE_UNTIL_THE_CONSUMER_READS_IT   ← deleted BY the change it guards

A temporary state that cannot say it is temporary is just a permanent state nobody chose.

Worked example: `3e0fba2`, `tests/routing/test_the_answer_turn_reads_the_slots_it_bound.py`.

### R-055.1 — "THE CONSUMER READS IT" MEANS THE SERVING SURFACE, NOT `main`

Added 2026-09-14, on the first application of this ruling, which nearly failed at step 3.

The consumer landed steps 1 and 2 and reported step 3 unblocked. It was not. The sandbox was
still serving a build from the previous day:

    version.json          git_sha 435ae7e...   built_at 2026-09-13T03:56Z
    grep "excluded by"            -> found      (CONTROL: grep works on this bundle)
    grep "candidates flagged"     -> nothing

— and the image for the merged commit was **still building**. Narrowing then would have blanked
the panel with both repos' suites green, which is this ruling's own failure mode, reached through
the door the ruling opens.

**MERGED-NOT-DEPLOYED IS THE SAME WINDOW AS NARROWED-NOT-READ, one repo over.** So step 2 is not
"the consumer's change is on main"; it is **"the serving surface answers with the new shape"**,
proven by readback with a positive control, exactly as any other absence assertion.

**AND THE PULL IS ASYMMETRIC, WHICH IS WHY THIS NEEDS WRITING DOWN.** The same session that
refused to take the producer's payload shape from a dispatch — and went and measured it in the
serving pod, correctly — then read its OWN side's readiness off `main`. Nobody was careless. The
instinct to verify someone else's claim is simply stronger than the instinct to verify your own
repo's state, and the second is the one that ships.

### R-055.2 — A FIXTURE WRITTEN FROM AN ACCOUNT OF A PAYLOAD AGREES WITH THE ACCOUNT

**Found by `cortex-ui-60`, in its own work, and reported against itself.**

Its existing fixture in `attemptFailed.test.tsx` carried **no `disposal` field at all** — it had
been built from a description of the payload in a dispatch message rather than from the producer.
It passed. It passed *as a removal*, which is precisely the mislabel this whole packet exists to
fix, and it would have stayed green through a blank panel.

**A fixture written from an account of a payload agrees with the account, not with the payload**
— and it goes green while the thing it models is wrong. It is the same defect as a corpus row
written from what the router SHOULD say, and the same as a docstring standing in for evidence:
a second-hand description acquires the authority of the thing it describes, and tests built on
it verify the description.

This is what makes the ordering law EVIDENCED rather than merely prudent: the consumer's own
test suite could not have caught the narrowing, because its fixture disagreed with the producer
in exactly the field the narrowing turns on.

Related: [[a-docstring-is-not-evidence]]; [[a-stale-claim-is-pre-authenticated]];
[[an-absence-assertion-is-worth-its-control]] — the readback in R-055.1 needed one, and had one.

### R-055.3 — PARTITION, DO NOT FILTER, AND TAKE THE NEW KEY FIRST

Also `cortex-ui-60`'s, and both points improve on the dispatch that asked for them.

**PARTITION.** A `flagged` half computed as "everything not `removed`" absorbs any THIRD disposal
the gate ever adds and renders it as a live candidate — **a claim about a decision, made from not
recognising a word.** Neither half may be derived from the other's absence. Sealed with a
`deferred` row that must land in NEITHER half.

**TAKE THE NEW KEY FIRST.** While both keys carry the same rows, reading both naively lists every
flagged candidate twice and the fix looks like a new defect. Taking `flags` before `excluded`
classifies a doubled row by the KEY rather than by its own field: the same answer today, and the
right one for a flag row that arrives with no `disposal` — a case **only the additive window
makes reachable.** The window does work beyond what it was opened for.

**AN ABSENT `disposal` READS AS REMOVED**, deliberately: every row predating the field meant that,
and by this ruling's own trade a mislabel is visible where a disappearance is not.

Related: R-054 (the permissive arm, same ordering law); [[a-plausible-negative-is-not-a-considered-one]]
— an empty list reads as a deliberate "nothing was excluded"; [[read-the-consumer-of-what-you-fixed]]
— this was found by opening the consumer, and by nothing else.

---

## R-056 — AGREEMENT IS NOT CORROBORATION WHEN THERE IS ONLY ONE WITNESS

**Found 2026-09-14 by Lane 1 and `cortex-ui-60` in the same exchange, each catching the other's
half.** Numbered here because it is an instrument law, not a routing fact.

A consistency check was built between two fields of one record: the arity gate's `flagged`
disposal and the projection's `instance_resolved`. A `flagged` row on an artifact reporting
`instance_resolved: true` would be a record denying itself — a defect nameable on the turn
instead of inferred from a total. It is a good idea. **It cannot fire.**

    gateway.py:3340,3399        "instance_resolved": bool(md.get("subject_instance_id"))
    dynamic_supervisor.py:956   query_is_set = not subject_instance_id
    dynamic_supervisor.py:728   _pre_instance = pre_resolved.get("subject_instance_id")

**Both halves derive from ONE field.** A flag is emitted only when the gate saw no instance,
which means that field is empty, which means `instance_resolved` renders false. The contradiction
is unreachable by construction. (Confirmed exhaustively: `instance_id` is assigned once at
`direct_dispatch.py:198` and read at `:214`, `:374`, `:460` with no rebinding — a reassignment
between the gate's read and the materialization's was the one thing that could have made it
reachable, and there isn't one.)

**AND THE DEFECT THAT PROMPTED ALL OF THIS WOULD NEVER HAVE TRIPPED IT.** On the NP-MERIDIAN
turn, `subject_instance_id` was empty and `instance_resolved` was false. **The two halves AGREED,
and both were wrong**, because the bound value was in the chain's slots where neither looked.

> **A record can be self-consistent and false, and a consistency check is blind to exactly that.
> Agreement is not corroboration when there is only one witness.**

**THE CHEAP INSTRUMENT** (`cortex-ui-60`'s, and it costs a minute): **trace each half of a
comparison back to its SOURCE. If they meet at one variable, it is an identity wearing a check's
clothes.**

**WHY NO TEST RUN FINDS THIS, and this is the part that generalises.** Mutation testing proves
*guard-is-right*; it can never prove *guard-is-reachable*, **because the fixture supplies the
triggering input.** Three mutants were killed here over a proven-green baseline — including an
always-contradicted control, correctly insisted upon, which is precisely the test that catches a
renderer bug and is silent on reachability. A full kill sheet says nothing about whether the
world can produce the row.

**THE DISPOSAL IS RELABEL, NOT DELETE.** Asserting that two declarations of one fact agree is a
JOIN ASSERTION, and the join is what nobody checks — both halves had rendered happily alone since
June. It is worth keeping as a REGRESSION guard: the day someone makes the gate read a different
field than the projection, it is the only thing watching. What it must never be read as is a
partition of the existing population. **A clean result from a check that cannot fail is worse
than no check, because it looks like evidence** — so every surface rendering the stamp carries
`ZERO CONTRADICTED IS NOT EVIDENCE OF ZERO DEFECTS` in the same breath, for the reader in six
weeks who finds a clean panel and banks it.

### R-056.1 — BOTH SESSIONS RAN A BLIND SCAN THE SAME HOUR, AND ONLY A PLANTED CONTROL CAUGHT IT

Two NUL-byte sweeps, two different shells, two silent instrument failures:

    grep -P '\x00'     unsupported in this shell -> matched nothing, reported CLEAN
    grep $'\x00'       collapsed to an EMPTY pattern -> matched every line:
                       "322 NUL-carrying lines" in a 321-line file

**Neither tool errored. Both produced a confident, well-formed, wrong answer** — one a false
all-clear, one a false alarm whose arithmetic was the only tell. In each case the thing that
caught it was a control planted BEFORE the sweep, never the sweep itself.

An absence assertion is worth its control, and **the control has to run through the same
instrument the claim does** — a scan proving a planted NUL is findable, in the same shell, in the
same invocation shape.

Related: [[a-guard-that-cannot-fire]] — the BORN DEAD form;
[[the-instrument-and-the-subject-share-a-surface]]; [[an-absence-assertion-is-worth-its-control]];
[[assert-on-the-claim-not-its-neighbour]]; R-055.2 — a fixture written from an account of a
payload, which is the same substitution at the input end.

---

## R-057 — AN INSTRUMENT THAT CANNOT ASK THE QUESTION ANSWERS ANYWAY, WITH THE REASSURING WORD

**Architect-ruled 2026-09-14: the two instrument instances of this week are ONE LAW.** Filed with
a third, found the same day, which is the most expensive of the three.

    grep -P '\x00'              unsupported in this shell -> matched nothing -> "CLEAN", 1199 files
    grep $'\x00'                collapsed to an EMPTY pattern -> matched every line
    a seal over `bound_slot_sources`   the FIXTURE supplies the field -> 17 green assertions

**None of the three errored.** Each returned a well-formed, confident answer, and in two of them
that answer was the reassuring one. **A tool that cannot reach the question does not say so — it
reports the default outcome of not finding anything, which is indistinguishable from the good
news.** The false-alarm case (the empty pattern) was caught within a minute because its arithmetic
was absurd. The false all-clears were not caught by anything except a planted control.

**THE THIRD INSTANCE IS THE SHAPE AT FULL SIZE.** A gate fix and a provenance-gated promotion were
written, sealed with 17 assertions across two sites, mutation-checked, committed, rolled to the
cluster and REPORTED AS FIXED. Then:

    356 AnswerArtifacts carry `resolved_intent`
      0 carry `bound_slot_sources`
        the field is READ in one place and WRITTEN nowhere but a test fixture

So `turn_is_set_shaped(instance, verb, set())` degrades to exactly `not instance` — the behaviour
it replaced — and `promotable_instance_from_slots(verb, {})` returns `None` on its first line.
**The whole arc is inert in production, and every seal is green because the seals supply the
input the world does not.**

> **This is R-056's law applied to the instrument instead of the guard: a test cannot tell you
> whether the data it fabricates exists.** Mutation testing, coverage and a kill sheet are all
> computed inside the fixture's world.

**THE CHECK, and it is the same one in all three cases: ASK THE INSTRUMENT A QUESTION YOU KNOW
THE ANSWER TO, THROUGH THE PATH THE CLAIM USES.** Plant a NUL and prove the scan finds it. Count
the rows in production that carry the field before trusting a seal that reads it. A control that
reaches the answer by a different route is a second claim, not a control.

**AND THE PRODUCTION COUNT IS THE ONE THAT WAS SKIPPED.** Two reachability traces had already run
on this change — one found the wrong call site, one confirmed the payload was set by the gateway.
Both traced CODE. Neither asked whether any artifact in the database had ever carried the field,
which is one query and would have stopped the work before the first commit.

Related: R-056 (guard-is-right vs guard-is-reachable — this is its instrument half);
[[an-absence-assertion-is-worth-its-control]]; [[a-sample-is-not-the-population]];
[[assert-on-the-claim-not-its-neighbour]].

---

## R-058 — A CITATION IS NOT A SIGNATURE

**Found 2026-09-14 by `invincible-agent-81`, against a misattribution aimed at them.** They were
told their chain-slot loop fix had been inert in production. It was not their fix.

They checked rather than recalled — every file their commits touched — and the set excludes the
entire routing surface. What IS theirs is the MEASUREMENT the code cites: the four-hop walk,
`1m15 / 1m42 / 2m07 / 2m34` against `1m16` in one hop. They reported it, said twice that the loop
was someone else's to fix, and did not touch it. `_accumulated_slots`' docstring then recorded:

    MEASURED 2026-09-12 by invincible-agent-81 on the rolled fleet

> **The credit is correct and it reads as authorship.** A reader looking for an OWNER finds the
> person who took the reading rather than the person who wrote the line — and the citation is
> precise, dated and verifiable, which makes it *more* convincing, not less.

**AND GIT CANNOT CORRECT IT.** Measured on this repo: **every commit in the last forty, across
every lane, is authored `Chris Nogradi <cnogradi@gmail.com>`.** One human identity, many agents.
So `git log --author` disambiguates nothing, `git blame` names the human who owns the machine,
and the only reliable test is the one 81 used — *which files has this lane ever touched.* That is
a reconstruction, not a record, and it works only while a lane is alive to be asked.

Three of the last sixty commit messages name their authoring lane. The fix's own commit
(`8c7422c`) names the measurer in its body and its author nowhere.

**THE RULE.** Attribute the measurement **and** name the author, or the two collapse the first
time somebody needs an owner. A commit that cites a finding should say who wrote the code as
plainly as it says who took the reading — the trailer is the natural place, since `Co-Authored-By`
already names the model and not the lane.

**THE COST WHEN THEY COLLAPSE** is not embarrassment; it is a dispatch sent to someone who cannot
act on it, while the person who can never hears. Here it cost one round trip because the repair
was already built. On a live defect it would have cost the time it took for the wrong lane to
prove a negative about itself.

**AND THE SECOND HALF OF 81'S REPLY IS THE PART TO KEEP:** *"nothing owed from me, and nothing
verified by me either — I have not reviewed `c4f15ab` and should not be recorded as having done
so."* **A correction to a misattribution must not create a second one in the other direction.**
Being named in a thread is not review, and a reader six weeks out cannot tell the difference
unless somebody says so.

### R-058.2 — A WRONG CLAIM CAN BE CHECKED AGAINST THE WORLD; A WRONG ATTRIBUTION CORRUPTS THE CHECK

**Found by the `lane/eo` lane, against their own relay.** Architect-ruled as R-058's mechanism
stated from the inside, which is why it is placed here rather than given its own number.

**⛔ THIS RULING WAS MISATTRIBUTED AT THE MOMENT OF FILING, AND THE ERROR IS THE BEST WORKED
EXAMPLE IT HAS.** Lane 1 credited it to `invincible-agent-28` — a display name shared by TWO live
sessions, one working `lane/eo` and one working `lane/74`. The tool said so on every send ("1
other live session is also named…"), and Lane 1 read a name where an identity was required. So a
ruling whose text is *a wrong attribution corrupts the check* was filed with a wrong attribution,
and the lane it named had to prove a negative about work it had never touched — which is exactly
the cost the ruling describes. **Attribution is now by LANE, the durable key, per R-058.1.**

That lane relayed the architect's `retrieval_mode` ruling to the SDK lane as **"your `retrieval_mode`"**
and built an argument on it: *you already have the HOW axis, do not design the WHETHER axis
separately.* It was never that lane's. They searched five repos, found **zero** occurrences, and
said they nearly took it on that say-so —

> **because being told "this is yours" reads as a reminder rather than as an assertion.**

**THE PERSON NAMED AS THE SOURCE IS THE ONE LEAST LIKELY TO CHECK WHETHER THEY ARE.** An
attribution is what someone uses to decide *whether to check at all*, so a false one spends an
authority that never existed — and it spends it on the one reader positioned to catch it.

**THE TELL IS THAT CORRECTING IT MADE THE RECOMMENDATION STRONGER.** "Do not build two axes
separately" collapses to "there is one decision" once the first axis turns out not to exist. An
attribution whose removal *improves* the argument was load-bearing and unexamined — it was doing
work, and nobody had looked at it.

**REMEDY: name WHO ruled and WHEN, and quote rather than paraphrase. Never let an attribution ride
inside a possessive pronoun.** "Your X" asserts ownership in a word that reads as courtesy.

### R-058.1 — THE REMEDY, RATIFIED 2026-09-14

**`Lane: <worktree>/<branch>` as a trailer on every commit**, e.g. `Lane: ia-01/lane/01`.

**IT NAMES THE DURABLE KEY, NOT THE ADDRESS** — the way the roster does. A session id
(`invincible-agent-65`) dies with the session; the worktree/branch pair outlives it and is what a
later reader can actually check out. `git worktree list` is the registry.

Enforced by `tests/test_every_commit_names_its_lane.py`, which:

  * binds **forward only, by date** — retro-fitting means rewriting published history, which is
    refused here for the same reason a pushed tag is never rewritten;
  * asserts **the premise** (one git identity across all lanes), so the day lanes commit under
    distinct identities somebody finds out there rather than maintaining redundant ceremony;
  * asserts the trailer names a **registered worktree** — one naming a lane that does not exist
    points the next dispatch at nobody, which is worse than silence, because a confident wrong
    answer travels further than none.

**Measurer and reviewer stay distinct from author.** The seal asserts authorship only. Taking a
reading is not writing the line, and being named in a thread is not review.

**THE TRAILER IS READ FROM THE WORKTREE, NEVER DERIVED FROM A SESSION ADDRESS.** Found within the
hour of ratifying it, by `invincible-agent-28`, against my own assertion about them:

    Lane: ia-28/lane/28     <- what I wrote, from the session name
    Lane: ia-74/lane/74     <- what that session actually is

**The session address and the worktree are independent, and neither predicts the other.** The
session address also churns, which is why the roster is not keyed on it. 28 had made the
reciprocal error earlier in the same arc — telling peers to address them as
`invincible-agent-74` because they worked in `ia-74` — and `ListAgents` corrected them. So the
mapping fails in *both* directions and looks reasonable in both.

The seal's registry arm caught it (`ia-28` is in no worktree list), which is the guard firing on
its author. But it checked only the worktree HALF, so `ia-74/lane/01` — two real names that are
not each other's — would have passed. **It checks the PAIR now: mispairing is worse than
inventing, because an invented lane resolves to nobody and a mispaired one resolves to somebody.**

> **When a derivation produces a wrong identifier, fix the derivation, not the row.** A row
> corrected by hand leaves the rule that produced it intact and pointed at the next one.

Related: [[an-authority-ranking-needs-a-scope]] and [[prefix-registries-bite-silently]] — the same
shape, where a plausible key resolves to the wrong thing rather than to nothing.

**AND THE FIRST VERSION OF THE SEAL COULD NOT FIRE.** Its cutoff was a round `23:00` that had not
arrived: every commit exempt, an empty parametrised population, and `1 skipped` — which inside a
run of hundreds reads exactly like a pass. The guard against commits with no recoverable owner
shipped as a guard that could not run, in the same change that argued for reachability. It is now
bound one second before its own implementing commit, so **the rule's first subject is the commit
that created it**, and a trailerless probe was shown to red the file.

Related: [[a-stale-claim-is-pre-authenticated]] — precision makes a claim more trusted, and this
is the same mechanism applied to provenance; R-056 (two declarations that never meet); R-057 (the
cutoff-in-the-future is that law inside the check itself);
[[an-adr-does-not-allocate-a-component-name]] — the other place one name is read as two things.

---

## R-059 — A JUSTIFICATION NOBODY TESTED OUTLIVES WHAT IT JUSTIFIED

**Offered by the `lane/eo` lane against their own work; numbered here per R-021.**

*(Originally filed crediting `invincible-agent-28`, a display name shared by two live sessions.
Corrected to the lane, which is checkable — see R-058.2's note.)*

**A reason is the least-checked sentence in a change.** The claim gets reviewed and the code gets
tested; the justification is read as background. So it survives the thing it was written to
support, and is still being cited after it stops being true.

    "main.py imports rdflib/weaviate/baml at module scope, so NO TEST CAN IMPORT IT"

That justified putting rules in a pure module. It went into **three files, several commit
messages and a lane handoff.** It is false: `tests/test_predicate_hybrid_search.py` stubs those
dependencies and imports it, and that test already existed when the claim was written.

**The design survived on COST** — one stub harness exists, and behavioural assertions belong
there — **but the absolute did not.**

> **AN ABSOLUTE INVITES NO CHECK.** A reader who doubted *"no test CAN import it"* would have to
> prove a negative. Say what you **checked** — *"no test imports it today"*, one grep, and true —
> rather than what is impossible.

**AND PUSHED COMMIT MESSAGES CANNOT BE CORRECTED**, so the correcting commit must NAME the
earlier ones that carry the wrong version. Otherwise the correction is one message against
several, and the several are the ones a reader finds first.

Related: R-058.2 — a reason nobody tested and a source nobody checked, the same week and the same
shape; [[a-docstring-is-not-evidence]]; [[a-justification-invented-downstream-fits-by-construction]]
— there the reason was built to fit a conclusion, here it was true once and never re-read.

---

## R-060 — A SEAL THAT SPEAKS ITS SUBJECT'S DIALECT CANNOT DETECT THAT THE DIALECT IS WRONG

**Found by the `lane/74` lane against their own suite, 2026-09-14.**

Engine S registered one door, `{base}/analyze`, taking the verb in the body as `fn`. The fleet
puts the verb in the PATH — `{base}/measure/{fn}` — so the dispatcher sends `{query, params}` and
every Engine S verb 422'd on arrival: *missing `fn`*.

**THEIR SEAL WAS GREEN THROUGHOUT AND COULD NOT HAVE CAUGHT IT.** It posted to `/analyze` with
`{"fn": ...}` — the engine's own dialect. So the test agreed with the engine, both disagreed with
the fleet, and

> **the agreement is what made it look verified.**

This is *the instrument and the subject share a surface* raised from a STRING to a CONTRACT. A
check written from the same understanding as the thing it checks confirms the understanding, not
the behaviour — and it does so more convincingly the more carefully it is written.

**IT WAS FOUND BY REPLAYING AGAINST THE LIVE POD** with a body rebuilt from a stored artifact,
which is the one reading that could not inherit the dialect, because the pod answers the wire and
not the author.

### The replacement is derived — and took two wrong versions, both failing HONEST data

    v1  required "/measure/" in every endpoint
        -> flagged the /resolve_instance and /enumerate_instances providers, which are CORRECT:
           a provider answers for a whole CLASS, so there is no verb to put in a path.
    v2  still flagged cost's f"{base}/{spec['endpoint']}", also correct — each spec carries its
        own endpoint, so that URL DOES vary.
        -> it had encoded ONE ENGINE'S SPELLING of the property instead of the property.

**The rule is now the property: THE URL MUST VARY PER REGISTRATION.** One interpolation is a
constant path shared by every verb; two or more means something per-registration reaches the
path. Mutation-checked: restoring `{base}/analyze` reds it by name.

**AND THE ARGUMENT WAS ALREADY WRITTEN DOWN IN `engine-cost`:** one endpoint per verb, *because
the registrar BAKES `endpoint_url` per verb* — so a single body-dispatched route gives every verb
the same URL and the mesh has no way to reach one rather than another. The reason existed, in a
neighbouring engine, unread at the time the second shape was chosen.

### The general form, which showed up twice in one engine on one day

**Survey before mint applies to an API exactly as it applies to a class.** `maint:WorkOrder` was
refused because the class already exists under the standard's name (`mro:MaintenanceWorkOrder`);
`{base}/analyze` was refused because the shape already exists under the fleet's. Same rule, one
spelling a vocabulary and one spelling a wire contract.

Related: [[the-instrument-and-the-subject-share-a-surface]]; R-056 (agreement is not corroboration
when there is one witness — here the witness is a shared assumption rather than a shared field);
R-057 (a test cannot tell you whether the data it fabricates exists);
[[a-filed-defect-is-a-sample-not-a-census]] — v1 and v2 were each a sample of the property.

---

## R-061 — A SEAL THAT ASSERTS THE ORDER OF TWO STRINGS CANNOT SEE A `return` BETWEEN THEM

**Found by mutation, 2026-09-14, inside the seal written to prove a guard fires.**

`test_THE_SKIP_RETURN_IS_GONE` asserted that `_writer = get_writer()` appears after
`bundle["status"] = "failed"`. Restoring the defect — a `return` between them — leaves both
strings present, in that order. **The seal passed with the bug back in.**

> **Text order is not control flow.** A check over source can say WHAT appears and in what
> sequence; it cannot say what EXECUTES. The two diverge at exactly one construct — an early exit
> — and that is the construct the seal existed to forbid.

**THE PROPERTY, not the arrangement:** *nothing exits between preparing the write and performing
it.* Asserted by scanning the span between the two statements for `return` / `raise`, which is a
claim about reachability rather than about layout.

**AND ONLY THE MUTATION FOUND IT.** The assertion reads correctly — it names the right two
statements in the right order, and a reviewer checking whether it "tests the fix" would say yes.
Re-reading it produced agreement; restoring the defect produced the truth. A kill sheet is half
the evidence (R-056), and this is the other half doing the work a reading could not.

Cf. [[the-instrument-and-the-subject-share-a-surface]] — there a check matching a STRING could not
see a BEHAVIOUR; here it could not see an EXIT.

---

## R-062 — DO NOT PUSH A RED YOU HAVE NOT READ

**Stated against myself.** `4294b61` was committed and pushed with `1 failed` in the run output.
I had classified it, in the moment, as "probably the boundary touching an adjacent seal" and moved
on.

It was: `test_question_text_on_the_artifact_is_the_users_message` indexed the FIRST
`"question_text":` in `gateway.py`, and the outer boundary had added a second construction site
DEFINED EARLIER in the module — so the seal read the new one and reported a composition defect
against a line that composes nothing. **A seal over a population of one, written when the
population was one.**

The classification was right. That is not the point.

> **A red is a claim you have not evaluated.** Deciding what it probably is, and pushing on that,
> is the fixture-world problem applied to your own judgement: the explanation is supplied by the
> person who most wants it to be benign, and it is never checked against the failure output.

The cost here was nothing, because the guess held. The cost is unbounded when it does not, and
**nothing in the moment distinguishes the two** — which is the whole reason the rule cannot be
"read it when it looks serious."

**Both pre-existing reds and new ones.** A pre-existing failure is a statement about WHO
introduced it, never about what it costs — the docs-corpus drift was carried across six suite runs
on exactly that reasoning and it was the red that refused the prime.

---

## R-063 — A MERGE CAN BRING A NEW SEAL, AND RUNNING ONLY WHAT YOU EDITED WILL NOT FIND IT

**`invincible-agent-81`'s correction to R-0xx's own rule**, found against their own work.

*Choose suites by consequence, not by edit* silently assumes **the suite you need existed when you
last looked at the suite list.** A merge is exactly the moment that assumption breaks: it brings
code you did not write AND checks you have never run, and nothing about the act announces the
second half.

Two of their commits ran `tests/finance/` and `tests/cost/` green — correctly, by the rule as
written — and never ran the trailer seal a master merge had just carried in.

**THE TRAILER WALL PROVED IT FROM TWO LANES AT ONCE**, which is what made it a boundary defect
rather than a lane being behind: `lane/eo` and `lane/91` hit the same check from different
directions within an hour, neither having been able to comply.

### R-063.2 — A MERGE ALSO ENLARGES THE POPULATION OF SEALS THAT ALREADY EXISTED

**Found against my own application of R-063, within the hour of filing it.**

I merged a lane's commit, correctly ran the new seal FILE it brought (`tests/graph_host/…`, 39
passed), and pushed. Master went red on `test_every_import_is_a_declared_dependency` — an OLD
seal, which I did not run, because the merge brought it no changes.

**It did not need to.** That seal scopes over `tests/`, so a new test file joins its population by
existing. The merge added `from typing_extensions import …`, a distribution no pyproject names,
and the seal caught it exactly as designed.

> **"Run what the merge brought" is not "run the files the merge touched."** New code enters the
> populations of every derived seal, and a derived seal's whole point is that it quantifies over
> a set nobody maintains by hand.

**How to apply:** after a merge, run the new files AND the seals that derive their population from
a directory or a glob — those are precisely the ones a merge can break without touching. When in
doubt the full suite is the answer, which is again why a seal's cost decides whether it survives.

**AND THE FIX WAS THE FIXTURE AGREEING WITH ITS SUBJECT.** Both graphs the seal exercises import
`Annotated` and `TypedDict` from `typing`; the test imported them from `typing_extensions`. A
fixture importing what its subject does not is a small version of the stub problem that same seal
was written about — the state type would be built by a different mechanism than the graphs'.

**How to apply:** after a merge, the population of relevant suites is not the one you reasoned
about before it. Run what the merge brought, or run everything — and note that "run everything"
is only sustainable if the seals are cheap, which is why **a seal's cost is part of whether it
survives**: the ancestry predicate at 0.76s replaced a correct one at 134s, and the 134s version
was on its way to being deselected and then deleted.

### R-063.1 — DO NOT CHANGE SOMEONE ELSE'S MECHANISM SO YOUR OWN WORK PASSES

**Both lanes refused it independently, and the refusal is why the defect was diagnosed rather than
absorbed.** `lane/eo` and `lane/91` each hit the trailer seal, each could have swapped its
predicate inside their own branch, and each declined: *"changing someone else's predicate so my own
commits pass is the shape an exclusion list exists to avoid."*

> **It is not the edit that is wrong, it is the direction of fit.** Adjusting a check until the
> data passes is indistinguishable from fixing the check, at the moment you do it, to you. The
> difference only shows up later, in whether the check still refuses anything.

What they did instead is the pattern: **measure, propose, and hand the owner the numbers.** The eo
lane brought 16-bound-by-date against 12-by-ancestry with the difference named; `lane/91` brought
a six-commit partition with four exempt and two genuinely bound. Neither asked for an exception;
both made the owner's decision cheap.

**And that is what turned it from "a lane is behind" into a boundary defect** — two lanes, opposite
directions, the same wall within an hour, neither having moved the wall.

Related: R-030 (published history is not rewritten — the reason the trailer wall could not be
fixed by amending); R-058.1.

---

## R-064 — PRESENT ON THE MACHINE THAT WROTE IT, ABSENT EVERYWHERE IT MATTERS

**The TTL-not-in-the-manifest shape, restated for a BUILD INPUT.**

`cost_agent.package_export` needs the pinned Pyodide runtime. It lived in `.pyodide-cache/` —
**gitignored, zero tracked files.** Every developer who had ever built a package had it; CI had
nothing to copy; every deployed engine refused the export by name, honestly and permanently.

It was not missing. It was *somewhere that is not the place the work happens* — which is exactly
`iof_mro.ttl` on disk and absent from `CANONICAL_TTL_MANIFEST`, and exactly a hand-run Cypher
that no bootstrap reproduces.

> **The act that needs the input fetches it, pinned — a human's disk is never the source.**

Here: CI runs the builder's own `--fetch-runtime` at the pinned `PYODIDE_VERSION`, and git does
not carry 14 MB. The fetch step **refuses** rather than building a crippled image: an image with
the builder and half a runtime passes every test and fails at answer time with a missing-files
list, which is the slow way to learn CI had no network.

**THE TELL is a capability that works for everyone who built it and for nobody else** — and it
reads as working, because the people asking are the people who have it.

---

## R-065 — NO FIXTURE DRAWN FROM THIS REPO CAN DISCRIMINATE TWO RULES A REAL CHECKOUT BOTH SATISFIES

`_repo_root()` was changed from *"does this tree look like a checkout"* (`scripts/` and
`agent_fleet/`) to *"can a package be built here"* (the builder and the runtime). The seal asserted
the new rule. **Restoring the old one under a different variable name killed nothing.**

Two reasons, and the second is the one that generalises:

  1. the assertion matched a STRING, so a rename evaded it; and
  2. **a real checkout satisfies BOTH rules**, so every fixture available in the tree agrees with
     both, and the seal could not have discriminated however it was written.

> **The distinguishing case did not exist in the repository and had to be CONSTRUCTED** — a
> flattened `/app`: `scripts/` holding the builder, `.pyodide-cache/` holding the runtime, and no
> `agent_fleet/` anywhere. The old rule answers None there; the new one resolves.

This is `lane/32`'s stub from the other side. There, a double supplied the property under test and
so could never see its absence. Here, every available fixture satisfied the property under test
and so could never see which rule produced it. **Both are the subject and the instrument agreeing
because they were drawn from the same place.**

**AND IT IS WHY A BUILD SEAL RUNS AGAINST THE IMAGE, NOT THE TREE.** The tree is the one
environment where the question cannot be asked: everything the deployed artifact might lack is
present. The started-service CI seal has the same justification — a liveness check against a pod
asks the service its opinion of itself; a check against the image asks what was shipped.

Related: R-041; [[a-seal-that-defends-a-choice]] — a seal defending a choice must assert its own
fixture distinguishes the rejected rule, which is this law's instruction rather than its
observation; R-057.

---

---

## R-055 — A FAILURE RECORDED HONESTLY WHERE NOBODY READS IS A SUCCESS TO EVERYONE WHO LOOKS

**Three shapes in one day, filed as one entry because they will be recognised faster as a family
than as instances.** In every one the failure **was** recorded, correctly, by code that was doing
its job — and every one produced **a surface that looked fine over something that did not
happen.**

| shape | where the truth was | what the reader saw |
|---|---|---|
| **the LOG** | four WARNING lines: `mint failed 5/5` | `registered 3/3`, pod `1/1 Ready`, mesh empty |
| **the COLUMN** | `status: failed` in the artifact row | a blank card, indistinguishable from an empty success |
| **the WRONG COLUMN** | `routing.excluded[]` named the gate | `resolved_intent` held slots and no verb |

**ALL THREE WERE FOUND BY READING THE ROW RATHER THAN THE SCREEN**, and none was found by the
thing that was supposed to report it.

### The third is the subtlest and cost the most

`artifact-2-1789404372153`, `status: failed` in 191ms, entire intent:

    {"refused_slots": [], "accepted_slots": {"program_id": "NP-MERIDIAN"}}

**The slot that was bound, and not the verb that refused it.** Three reads to learn that
`mesh:finProgramBrief` was excluded on an **arity** gate immediately after an elicitation supplied
its one slot.

**NOTHING WAS LOST. IT WAS UNFINDABLE FROM WHERE A READER STARTS.** The field naming the ACTION had
been dropped from the field recording the INTENT — so a reader who opened `resolved_intent`, *the
field whose name promises exactly that*, saw slots and no verb. **Both halves were recorded
correctly and separately, and nothing named the verb in the field that would have joined them.**

> **Recorded in a column a reader does not start from is the same as not recorded, for anyone
> diagnosing under time.**

### The remedy is not "log more"

Each repair puts the fact **where the person who hits it is already looking**: the registration
returns a result its caller counts; the card names `status` and the exclusion reason; the artifact
carries the verb beside the slots. **None of the three added information — all three moved it.**

### And the method note is the law from the retraction, proven

`invincible-agent-22` misidentified an artifact by selecting on **the fields the ask/answer pair is
built to share** — same question, same subject, same verb, short summaries on both. **One query on
`derived_from_artifact_id` — the RELATION — resolved what three reads on the description could
not.** *Select on the relation between two records, never on their common description.*

## R-066 — A HOOK BROKEN BY ENCODING FAILS TOTALLY AND SILENTLY

**Measured 2026-09-15 while building the pre-push trailer guard.** A Python rewrite converted 100
line endings to CRLF. After it:

    bash -n .githooks/pre-push   ->  syntax error near unexpected token `newline`, line 52
    sh   -n .githooks/pre-push   ->  clean

**Two shells disagreeing about a script that had not changed reads as a syntax bug in the
script.** It is not; it is the file. And the runtime failure is worse than the check's: **git
prints the hook's error and carries on**, so the push succeeds, the rule the hook enforces is
simply off, and nothing anywhere says so. A guard that cannot run is indistinguishable from a
guard that ran and approved.

**THE PIN IS THE FIX, AND THE SEAL ON THE PIN IS WHAT MAKES IT THE REPOSITORY'S.**
`.gitattributes` carries `.githooks/* text eol=lf` beside the `*.sh` pin that was already there
for the same reason; a seal asserts the hook has zero CRLF **and** that the pin exists. Without
the second arm the check passes in this working copy and the hook is broken in the next one —
a property of a checkout rather than of the repository, which is the same distinction as a TTL on
someone's disk (R-064).

### R-066.1 — THREE "NO SUCH FILE" ERRORS FOR A FILE THAT WAS PRESENT

The same build produced three failures in a row, all reporting absence about something present:

    bash -n <Windows path>    backslashes stripped   -> "No such file or directory"
    bash -n C:/...            Git Bash wants /c/...  -> "No such file or directory"
    CRLF in the script        the file is fine       -> a syntax error at line 52

> **An addressing failure and an absence report the same way.** The tool is telling you what it
> could not reach, and a reader hears what is not there.

It is the probe-sent-the-wrong-field-name shape (R-057's instrument half) in a different costume:
the instrument could not ask the question, and its inability was reported in the vocabulary of an
answer.

**How to apply:** when a tool reports a file missing, `ls` it before believing the tool — and when
two tools disagree about one unchanged file, suspect the FILE's encoding before either tool.

### R-066.2 — A CLIENT-SIDE GUARD FAILS OPEN, AND THAT IS NOT R-012 INVERTED

R-012 fails CLOSED: a service with a missing declaration refuses through its readiness probe, and
that refusal is visible, addressed to an operator, and leaves the service up while it is fixed.

**A client-side hook has no such surface.** One that blocks every push on its own missing input —
a shallow clone that lacks the rule commit — is removed within the hour, by `--no-verify` or by
unsetting `core.hooksPath`, and then the rule has NEITHER arm rather than one.

> **A guard that survives is worth more than a guard that is correct and gone.**

So the division is deliberate and asserted: the **seal** is the fail-closed half, refusing in CI
where a refusal is seen and cannot be locally disabled; the **hook's** job is to be PRESENT. The
reason is recorded beside the skip, because the next reader meets fail-open and reaches for R-012.

---

## R-067 — A CHECK THAT A FLAG IS MENTIONED IS NOT A CHECK THAT THE INVOCATION PARSES

The workflow's fetch step contained `--fetch-runtime`. The seal asserted exactly that, and passed.
The command could not run:

    build_cost_package.py: error: the following arguments are required: --recipient

`--recipient` was `required=True` unconditionally, so the flag's own documented standalone use —
*"download the pinned Pyodide runtime into --runtime-dir"* — was unreachable. **The string was
present and the behaviour was absent**, and the build failed at the first push.

> **An assertion satisfied by TEXT rather than by BEHAVIOUR passes for the wrong reason.**

Same family as a slice that runs too wide: neither fails, both agree with something adjacent to
the claim. **The fix is the same in both cases — run the exact thing.** For a CI command that
means invoking it in the seal, or at minimum reading the parser's own declaration rather than the
caller's spelling of it.

---

## R-068 — MOVE WORKTREE ON PURPOSE BEFORE TRUSTING A SEAL

Moving Lane 1 out of the shared tree into `ia-01` was ruled for a different reason entirely — a
branch hazard. It also turned out to be **a population change**, and it found FOUR seals that were
statements about a working copy rather than about the repository, in one afternoon.

`.pyodide-cache/` is gitignored, so it exists in whichever checkout last fetched it and in no
other. Three seals passed only where the runtime happened to sit — **two of them written about
exactly that hazard**, in the same change that named it. The fourth compared a trailer to a
registry that had moved.

> **A worktree move is the cheapest population change available**, and green-wherever-the-
> environment-obliged is invisible until the environment stops obliging.

**How to apply:** a seal that reads the filesystem, git state, or anything outside the tracked tree
has not been tested until it has run somewhere else. A fresh worktree costs one command. It is the
same instrument as a planted control — it asks whether the green was about the subject or about
the room.

Related: R-064 (present on the machine that wrote it); R-065 (no fixture from this repo can
discriminate two rules a real checkout both satisfies) — this is the operational move that makes
both of those findable rather than argued.

---

## R-069 — A TRAILER IS A PAST-TENSE CLAIM; A REGISTRY IS PRESENT-TENSE

`Lane: invincible-agent/lane/ca-m33-cutover` was **correct when it was written**: that lane works
in the shared tree, which was then checked out at their branch. It became "unregistered" the
moment the shared tree was parked back on master — and the pair seal failed correct history.

> **A worktree's branch moves. A trailer does not.** Comparing a record of what WAS to a registry
> of what IS makes true history fail, which is the stale-claim shape running backwards.

**THE FIX IS TO CHECK EACH HALF AGAINST WHAT IS DURABLE ABOUT IT.** The worktree must be one the
registry knows — worktrees are long-lived and that is what catches `ia-28`, a name no worktree has
ever had. The branch must be a ref git knows, local or remote — that is what catches `lane/28`,
which nobody has pushed. `ia-28/lane/28` still fails both, which is the control that keeps the
loosening honest.

**The general form:** when an assertion compares a record to a live source, ask which one is
allowed to change. If the live source is, the assertion is about a moment and must say which.

---

---

## R-070 — A SEAL THAT READS COMMITTED HISTORY IS BLIND AT THE MOMENT IT IS NEEDED

`tests/test_chart_version_tracks_chart_content.py` asserts that chart content did not move after
the last `Chart.yaml` edit. It is a correct rule and it was **GREEN** through `e36aa55`, which
added `GRAPH_HOST_POSTGRES_DSN` to `values.yaml` without a bump. The release workflow refused the
push minutes later.

Nothing was wrong with the seal's logic. Its inputs are `git log` queries, so at the instant the
suite ran — change in the working tree, not yet committed — the newest commit touching `helm/`
*was* still an ancestor of the newest commit touching `Chart.yaml`. **The check ran, its premise
was true, and it answered a question about a state that had already been published.**

> The only person who can fix this cheaply is the one who has not committed yet, and that is
> exactly the person a committed-history seal cannot speak to. Once the commit is pushed, R-030
> forbids rewriting it and the remedy is always a follow-up commit.

Same shape as the Lane trailer, whose exemption list grew four entries in one day before the rule
moved into a pre-push hook (R-058.1): *a check whose remedy is always "record it and move on" is
reporting, not enforcing.*

**THE RULE.** A seal over version control state declares which state it reads. If it reads
committed history, it carries a companion arm over `git status` that fires **before** the commit,
and that arm needs a fixture — it is silent in a clean tree, and silence is indistinguishable
from correctness. Synthetic input, never a touched file: a run that mutates the tree it is
measuring is invalid in both directions.

**AND THE COMPANION ARM'S FIRST DRAFT WAS ITSELF THE BUG IT EXISTS TO CATCH.** It parsed
`git status --porcelain` with a fixed `line[3:]` slice through a helper that `.strip()`s stdout —
which eats the leading space of the two-column status **on the first line only**. The arm
reported `elm/invincible-agent/Chart.yaml` and failed a correctly-bumped tree. A path mangled by
one character is still path-SHAPED, so it read as a finding rather than as a broken instrument.
Parse by separator, not by offset, wherever a helper may have normalised the text.

---

## R-071 — A COMMAND'S COVERAGE AND A SENTENCE'S CLAIM ARE TWO DIFFERENT THINGS

> The defect doesn't live at a scale, it lives in the gap between what the command covered and
> what the sentence claimed. **Say what a command covered in the same breath as what it found,
> and treat a definite article in a finding as a question.**

Three instances in one day, three scales, one habit — recorded by `invincible-agent-28`:

| the command | the sentence |
|---|---|
| `limit 200` over 21,547 rows, unordered | a claim about the population |
| three of eleven grep hits read | a claim about all eleven |
| `kubectl -A` against ONE cluster | *"the cluster"* |

**THE SAMPLE WAS BIASED TOWARD THE ANSWER IT COULD NOT SHOW.** An unordered `limit` returns
whichever shard segment answers first, which in that case was the segment least likely to contain
what was being looked for. A sample is not merely partial — it can be partial in the direction
that hides the thing.

***"The cluster"* is the world you hold credentials for.** The fleet has at least two and one sits
behind the work-cluster fence, so a definite article silently promoted a scoped read into a
universal claim. That is why the rule is about the ARTICLE and not about the flag.

**THE DISPOSITION: NARROW, DO NOT RETRACT.** All three operational conclusions survived the
narrowing. In the NetworkPolicy case the useful statement split into two — *the chart carries no
manifest, so it cannot apply one anywhere* (checkable everywhere) and *ca's lint is the only
instrument in any deployment the chart governs* (true where credentials reach) — and both are
true once separated. A finding that overclaims is usually a true finding wearing a borrowed scope,
and deleting it loses the measurement along with the error.


**AND THE SAME GAP OPENS WHEN THE SENTENCE IS ABOUT THE WORK RATHER THAN THE INSTRUMENT.** Two
instances the same day, neither with any instrument pointed at it:

* **Lane 1's, cost an exchange.** Declined to take a stale-xfail fix off another lane on the
  stated reason *"it collides on their rebase in a file they are actively holding"*. Never
  measured. The other lane believed it for a full exchange and did not measure it either;
  `git diff --name-only origin/master...HEAD` then showed five commits, seven files, no overlap.
  The deferral bought nothing but a day of the hole staying open.
* **`invincible-agent-28`'s, cost a VIOLATION.** Bumped the SDK pin for engine-o alone, reasoning
  *"moving fifteen pins is a fleet change with a roll behind it, not a lane's."* `test_lock_coherence`
  refused the result: **the fleet pin is a single value by construction.** So "bump one engine" was
  not a smaller, safer version of the act — it WAS the act, done wrongly.

> **Restraint was not the conservative option; it was the only wrong one available.**

**THE TELL IS IDENTICAL IN BOTH AND IT IS WHY THIS BELONGS IN THE REGISTER:** both would have
checked a claim about the CODE. Neither checked a claim about the SHAPE OF THE WORK — *what this
lane may do*, *what belongs to someone else*, *what is too big to attempt* — because a reason for
doing LESS does not feel like something that needs evidence. A positive claim proposes an action
and the action draws review; an obstacle proposes nothing, closes the question, and leaves no
reviewer. It also reads as caution, so challenging it looks reckless rather than rigorous.

**The rule, therefore, covers both halves:** state what a command covered beside what it found,
AND state a blocker as a checkable claim and check it. Where it cannot be checked cheaply, say
*"I believe X blocks this and have not verified it"* — so the other party knows a load-bearing
premise is untested rather than settled.

See [[a-sample-is-not-the-population]], [[assert-on-the-claim-not-its-neighbour]].

---

## R-072 — THREE WAYS A WRITTEN CLAIM GOES WRONG, IN ORDER OF COST

`iagent-mesh-sdk-ca`'s taxonomy, ruled to sit beside R-055:

> meaning where nobody reads it · a claim that **BECAME** false · a claim that was **NEVER** true

**THE ORDERING IS THE INSIGHT.** The first two had a moment when checking would have worked. The
third never did — it was born wrong and aged into authority, which makes it the cheapest to have
caught and the longest-lived.

Their three instances, all from one day:

1. **Meaning where nobody reads it.** A tripwire whose docstring said exactly what its red meant,
   triaged as flakiness twice. The explanation existed and was not where the reader was.
2. **A claim that became false.** A handoff line — *"`caller=` was not adopted because that
   parameter does not exist in dag-tools yet"* — true when written, still being read as the
   current reason. See [[a-stale-claim-is-pre-authenticated]].
3. **A claim that was never true.** An allowlist seal whose OPENING SENTENCE asserted that a
   NetworkPolicy exists. It would have failed the first time anybody looked, and nobody did.

**A SEAL'S OPENING SENTENCE INHERITS THE AUTHORITY OF EVERY GREEN RUN UNDER IT.** That is what
makes the third kind expensive: the file accumulates credibility from its passing arms, and the
prose at the top is read as having been verified by them. It was not. Nothing in a suite checks a
docstring's first line.

**So the fix belongs at the SEAL, not in a docstring beside it** — an arm that asserts the thing
the sentence claims, or the sentence rewritten to claim only what an arm covers. Correcting the
prose alone leaves the same shape one edit later.

Compare R-070: a seal blind at the moment it is needed is the mechanism failing; this is the
PROSE failing while the mechanism is fine. Both report green.

---

## R-073 — `unsummarised`: A FOURTH DISPOSITION THAT RETIRES BY TEST

The NP-MERIDIAN brief (`artifact-10-1789516344356`) rendered three rows, two of which read
*"reported (see artifact)"*. That is not a finding and not a hole, and **none of the three
existing dispositions names it.** The caller is entitled, the verb RAN, the hop artifact exists
and the brief genuinely derives from it — what is missing is a quotable verdict.

The producer's own contract table says why the near neighbours are wrong
(`agent_fleet/presentation_agent/main.py:527`, mirroring `cortex-ui/.../NamedHole.contract.ts`):

    unentitled   the caller may not invoke this panel's verb   -> NAMED_HOLE
    unavailable  the verb failed, timed out, or was refused    -> whole-board refusal
    empty        the verb answered and legitimately has nothing -> the panel's own rowless card

> "the card refuses anything but `unentitled` … drawing a hole for those would erase the
> distinction between three different answers."

**Drawing it as `unentitled` tells a reader they lack an entitlement they have. Drawing it as
`empty` erases a distinction the comment above exists to keep — there IS content. Drawing nothing
hides a row that has a source.** Raised by `cortex-ui-60` before the payload existed rather than
read off the wire afterwards, which is the only cheap moment to settle a vocabulary term.

**THE RULING.** A fourth disposition, `unsummarised` — *content exists, verdict absent* — rendered
as the FINDING row with its artifact link and the label *"no verdict emitted by
`<verb>`"*, **never as a hole**.

**IT IS TEMPORARY BY CONSTRUCTION, AND THAT IS THE LOAD-BEARING HALF.** Its repair lives on the
producer: once the verbs emit a verdict line the way `fin_burn_rate` does, nothing can produce it.
So the seal that lands WITH the disposition asserts that **no built-in verb produces
`unsummarised`** — the term retires by TEST rather than by somebody remembering it was meant to be
temporary. A vocabulary term with no expiry mechanism is permanent whatever its docstring says;
compare R-072's third kind, a claim that was never true aging into authority.

**OWNERS, and each half is refused by the others if it lands alone:**

| who | what |
|---|---|
| `cortex-ui-60` | adds it to `NamedHole.contract.ts` — they own the contract |
| presentation producer | accepts it at `main.py:527`, in the same act |
| lane 32 | emits it on the brief row instead of printing "see artifact" |
| lane 91 | makes it unreachable: the verbs emit a verdict (favourable / adverse / none stated) |

**AND THE DISPOSITION IS THE FIELD, NOT THE NAME.** *"Carry the hole by name"* was the original
wording and it is underspecified: `{hole: "cost_variance"}` leaves the card choosing among states
with three different repairs and three different readers, and the honest guess is no render at all.
A row carries `{row: "cost_variance", disposition: "unsummarised", artifact: "..."}` or it carries
nothing a card can draw. Same absent-versus-empty rule as `disposal` and `failure_cause`.

---

## R-074 — A CONCLUSION IS TRUSTED OR REJECTED WHOLE; A MEASUREMENT CAN BE COMBINED

`invincible-agent-28`'s, and it is a property of how three lanes worked rather than of the thing
they were working on.

The fleet pin was dispatched as `v0.9.0`. It landed on `v0.9.1`, and **three lanes each supplied
one reason none of the others had:**

| lane | the half they had actually looked at |
|---|---|
| `iagent-mesh-sdk-ca` | the fastapi guard is absent from 0.9.0, and 0.9.0 is already on PyPI and immutable |
| `invincible-agent-28` | 0.9.0 carries `version: str`, the marker shape that was ruled against |
| `ia-01/lane/01` | 0.9.0 is an ANCESTOR of the SDK's master, and the resolved artifact carries neither |

**None of the three could have produced the other two.** Each was independently sufficient, and
each came from someone who had run a different command for a different reason.

> **Had any one of us reported only the conclusion — "pin 0.9.1" — the other two reasons would
> have been invisible and the target would have rested on whoever spoke first.** That is how a
> wrong pin reaches sixteen packages with everyone nodding.

**THE ASYMMETRY IS THE RULE.** A conclusion is atomic: a reader can accept it or reject it, and
nothing in it can be checked against what they already know. A MEASUREMENT has parts — a command,
a population, a number — so a second reader can test it against their own, notice it covers a
case theirs does not, or find it contradicts something only they can see. **Measurements
accumulate; conclusions compete.**

This is the constructive form of R-071. That entry says to state what a command covered beside
what it found; this one says why it pays even when nobody doubts you: **the reason you report is
the only one anybody else can build on.**

### The corollary: remove the inference, do not warn about it

The same exchange produced its own best illustration. 28 measured that Weaviate preserves
`creationTimeUnix` across a replace-on-deterministic-UUID — 132 of 132 Predicate rows, one 81-day
gap — and **expected a caveat to be added to `marker_is_stale`**. The ruling instead renamed the
predicate to `marker_predates_collection` and declared freshness **out of scope in the contract**.

> **A name that overclaims is read; a docstring that corrects it is not.**

A caveat leaves the wrong inference available and asks each reader to remember the correction.
Narrowing the name removes the inference. Same disposition as R-071's *narrow, do not retract* —
the marker still proves model identity and dimension with two witnesses; only the freshness claim
goes. See R-072: an implied guarantee nobody stated is the third kind waiting to be born.

---

## R-075 — IF A MESSAGE STRING ENUMERATES ANYTHING, THE ENUMERATION IS A FIELD

`cortex-ui-60`'s, and the sentence that makes it a rule is theirs:

> **A card can build prose from data and cannot reliably recover data from prose.**

Three instances in one night, which is what makes it a class rather than three fixes:

| | the flattening | what it cost |
|---|---|---|
| `expert_response.candidates` | verb IRIs written into a sentence | the field has no reader in cortex; candidates render as prose |
| `not_in_model` available dates | a list written into "Available dates: …" | a menu's worth of information arrives as a paragraph |
| *"carry the hole by name"* | a name with no disposition | **caught BEFORE the payload existed** — became R-073 |

**THE THIRD IS THE ONE THAT WENT RIGHT, AND THE ONLY DIFFERENCE WAS TIMING.** It was raised while
the payload was still being written. The other two were found after the wire had already carried
prose, and one of them had a producer that got it right — the cost engine emits
`{"refused": True, "outcome": kind, "reason": message, "available": [...]}`, with `available` as a
FIELD and its own comment saying *"same key as VintageRequired above, so a consumer reads one field
for what may I say instead."* **The flattening happened downstream of a producer that had already
done the right thing**, which is why nobody on either end saw it.

**This is R-055's shape at the presentation layer.** R-055 is meaning recorded where nobody reads
it; this is meaning recorded in a form nobody can read *back*. A sentence listing options is a menu
that has been flattened, and the flattening is lossy in exactly the direction that matters.

**How to apply.** When writing a message that names more than one of anything — options, dates,
candidates, verbs, reasons — the list goes in a field and the message may quote it. Never the other
way round. The test is whether a consumer would have to parse the sentence to act: if so, the
sentence is carrying data and the data has no home.

**And the cheap moment is before the payload exists.** All three were the same defect; only the one
raised during design cost nothing. See R-073, which exists because the disposition question was
asked while the shape was still being decided.

---

## R-076 — A PRODUCER CAN DO THE RIGHT THING, DOCUMENT IT, AND THE CONSUMER IS NEVER WRITTEN

R-075's corollary, and the half that rule does not reach.

R-075 catches a producer that flattens a list into a sentence. **This is a producer that got it
right** — emitted the enumeration as a field, and wrote a comment naming who would read it —
**and a reader that does not exist.**

    cost_agent    {"refused": true, "outcome": "not_in_model", "reason": "...",
                   "available": [...]}
                  with the comment: "same key as VintageRequired above, so a CONSUMER READS ONE
                  FIELD for what may I say instead"

    src/iagent            grep '"available"'  ->  ZERO hits
    presentation_agent    grep '"available"'  ->  no match
    cortex-ui             nothing to read, because nothing sends it

> **Both ends correct, the wire empty.** `available` was never flattened downstream. It was never
> read at all, since the day it was added, and nothing failed for as long as that lasted.

**THE DOCUMENTED CONSUMER IS WHAT MAKES IT EXPENSIVE.** A field emitted with no comment is an
open question. A field emitted with *"a consumer reads one field for…"* reads as a wired contract
to everyone downstream of it — the producer's own confidence is what stops the next person
looking. This is [[a-stale-claim-is-pre-authenticated]] applied to a claim that was never true
rather than one that became false: the sentence describes an arrangement that did not exist when
it was written.

**AND IT COMPOUNDS WITH THE SHAPE SPLIT.** The same refusal kind arrived BOTH WITH and WITHOUT the
field — `NotInModel` could not always compute the list, `CompositionError` recomputed it — so any
consumer eventually written against one branch would have been wrong about the other. **A field
with no reader has no pressure keeping its shape consistent.**

### The seal

The one already ruled for `bound_slot_sources`: **a field a producer emits for a consumer has a
reader in the tree, or the emission is a claim.** Assert the reader exists; a grep for the field
name outside the producer is enough, and it fails the day the emission is added without one.

### How it was found, and that is the reusable part

`cortex-ui-60` was told the field was renderable today. **They traced it instead of building on
the claim** — each grep run to completion, each exit code checked — and reported that the location
was one layer further out than the person who told them had put it. Second time in one session
that tracing rather than accepting produced the finding; the first was the `main.py` that was
pushed on a branch nobody had looked at.

Compare R-074: a conclusion is trusted or rejected whole. **"You can render that today" is a
conclusion.** The measurement behind it — *which files read the field* — is the thing that could
be checked, and checking it cost four greps and saved a renderer built against a field that cannot
arrive.

---

## Why this file exists at all

Two lanes independently refused work today on the grounds that a cited ruling could not be
found, and both were right. The failure was not that the rulings were wrong — they were the
architect's and they were sound — but that **a decision recorded in a conversation does not
constrain anything.** It cannot be cited, cannot be checked, and reaches a lane as a relay that
the lane is then obliged to treat as a proposal.

Same shape as the mirror script's false promise, the stale charter clause, and the ADR comment
that described a fix instead of making it: *a lesson written beside a list does not maintain the
list*, and a ruling written beside a conversation does not govern a repo.

