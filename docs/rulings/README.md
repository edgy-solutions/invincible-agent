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

**Blocked behind [R-005](#r-005-shared_slots-are-template-scoped).** `lens` lands with the
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
| a | **Author's visibility audience** — `risk_assessment_author:SUSTAINMENT`, view-only, granted at draft time. The existence-oracle protects against **outsiders, not authors**; that sentence is the rule it instantiates. | §5:290 |
| b | **`rejected` is reason-required too**, not only `accepted` — both verbs. Seal 6 mutates them **separately**, because one mutation covering both passes with one still wired. | §5:312 |
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

