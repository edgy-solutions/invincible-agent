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

**§10.3 is struck through rather than deleted**, so a reader can tell *answered* from *never
asked*. Neither remaining §10 question blocks increments 0–4; **§10.2 gates a claim, not a
build**.

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

## R-010 — NOT RECORDED — the number is allocated and its content is not in hand

**A GAP, ENTERED DELIBERATELY.** The architect's dispatch said "commit R-009 through R-013"; the
rulings supplied were R-011, R-012 and R-013, and R-009 arrived separately through cortex-ui-60.
**No content for R-010 reached Lane 1.**

Recorded as an explicit hole rather than skipped, because a register that silently jumps from
R-009 to R-011 reads as complete — and the next lane to want a number would take R-010 and create
a genuine collision with whatever it already is. **An absent entry that looks deliberate is the
failure this file was built to stop.** If R-010 was never allocated, strike this and say so; if it
was, it needs writing down before it can be cited.

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

## Why this file exists at all

Two lanes independently refused work today on the grounds that a cited ruling could not be
found, and both were right. The failure was not that the rulings were wrong — they were the
architect's and they were sound — but that **a decision recorded in a conversation does not
constrain anything.** It cannot be cited, cannot be checked, and reaches a lane as a relay that
the lane is then obliged to treat as a proposal.

Same shape as the mirror script's false promise, the stale charter clause, and the ADR comment
that described a fix instead of making it: *a lesson written beside a list does not maintain the
list*, and a ruling written beside a conversation does not govern a repo.
