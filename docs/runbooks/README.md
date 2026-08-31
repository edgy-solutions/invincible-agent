# Runbooks — index

**You have a task and you want the page that gets you through it.** Every entry below says *you
want this when…* and whether it exists. **Nine of eleven do not exist yet, and are listed anyway**
— an index of names with one page behind it is honest and useful; eleven stub pages would be the
stub-mill [ADR-0037 §5](../adr/ADR-0037-ratified-docs-corpus-help-surface-grounding.md) refuses.
A name here is a slot waiting, not a promise.

**Writing one:** copy [`_TEMPLATE.md`](_TEMPLATE.md). The shape was extracted from
[`adding-an-engine.md`](adding-an-engine.md), which earned it by being written during the work and
then corrected by someone running it. The rule the template is built on: **if you had to discover
it, it goes in.**

---

## Platform-side — things done TO the platform

You are adding a capability to the mesh itself.

| you want this when… | page | status |
|---|---|---|
| You are standing up a **new engine** — domain ontology, typed verbs, registration, deployment, the four namespaces its name occupies | [`adding-an-engine.md`](adding-an-engine.md) | **written** — §0–§10 + appendix, worked from Engine F, corrected by a run |
| You have an engine and are **adding one verb to it** — no new deployment, no new identity, but registration is still Contract D and still atomic | — | not written |
| You have a verb whose output nothing can **draw**, and you need a card type / archetype binding | — | not written · **cross-repo** (`cortex-ui` holds `DERIVED_BINDINGS`; see the known gap in the engine runbook's appendix and [`engine-f-archetype-bindings`](../plans/engine-f-archetype-bindings.md)) |
| Your agent runs and you cannot see **what it did** — traces, spans, the identity a span carries | — | not written |
| You are adding a **whole domain** — a new vocabulary graph, its prime-manifest entry, its partition | partial: [`personas-and-domains.md` §Adding a domain](../architecture/personas-and-domains.md) covers the *policy* half (config, no recompile). The ontology + manifest half is in [`adding-an-engine.md`](adding-an-engine.md) §1–§2. Neither is a task page. | not written |
| You are adding a **persona** | partial: [`personas-and-domains.md` §Adding a persona](../architecture/personas-and-domains.md) — a real how-to living inside an architecture doc | not written *as a runbook* |
| You are authoring a **workflow definition** — the process documentation that is also the process | — | not written · wakes on the first definition a process owner authors (ADR-0037 §1, gate granularity) |

## Consumer-side — things done WITH the platform

You are a user of the mesh, not a builder of it. **None of these exist, and none should be written
from imagination** — see the authoring rule below.

| you want this when… | page | status |
|---|---|---|
| You have data somewhere and want it **in the mesh** — catalogued, addressable, askable | — | not written |
| You want to publish what you have as a **data product** others can find and depend on | — | not written |
| You have a dataset and want to **ask questions of it** in English — and to know when the answer is honest | partial: [`../corpus/cortex-capabilities-primer.md`](../corpus/cortex-capabilities-primer.md) explains *what exists* (a `reference` doc, not a how-to) | not written |
| You want a **dashboard** — a board of answers rather than one answer | — | not written |
| Someone needs **access** to a persona · domain cell | partial: the git rail is `policy/` in-repo; the live Topaz write is a **human action**, not an agent one | not written |

## Not runbooks, though they are named like one

- [`../demo-day-runbook.md`](../demo-day-runbook.md) and
  [`../reference/work-demo-runbook.md`](../reference/work-demo-runbook.md) are **operational
  checklists for a specific event** — what to check before someone watches, what to press in what
  order. They sequence around problems rather than teaching a task, and they carry no
  `explains` edges. Different genre, deliberately kept separate.

---

## Two things to know before adding an entry

### Runbooks do NOT inherit the coverage gate

ADR-0037 §1's bidirectional gate — *every registered verb needs a `concept` doc or CI goes red* —
is **verbs only in v1, deliberately**. Runbooks sit on a different axis: they are about **tasks**,
and there is no enumerable population of tasks to gate against. So this index **cannot** claim
coverage and must not pretend to. What a runbook *can* do is declare `explains` targets — which
makes it retrievable by anchor (ADR-0037 §3, rung 1) without claiming to cover anything.

The consequence is that **this index being incomplete is a fact, not a failure**, and nothing will
go red about it. The honest signal is the `status` column above.

### Do not write a page for a task nobody here has done

[`adding-an-engine.md`](adding-an-engine.md) is good because it was written from execution and then
corrected by a run — which found five defects in it. A consumer-side page written from imagination
would be exactly the artifact this corpus exists to replace: **correct at writing, stale at the
first change, and nothing fails when it lies.** Those pages get written when someone walks the task
with an agent recording, which is roughly a half-day each and is the same exercise as onboarding
anyone else.

**Which is why the two halves of this index fill at different rates, and whoever picks this up
should know where the effort actually goes.** The **platform-side** pages come *free* as lanes
work: a lane adding a verb, a card type or telemetry is already doing the task and hitting the
walls, so its runbook is a by-product of work that was happening anyway — the cost is remembering
to write the page while the discoveries are still in hand. The **consumer-side** pages have no such
lane. Nobody here has yet got data into the mesh as a user, built a dashboard as a user, or asked
questions of a dataset as a user, so those pages need someone to **deliberately walk the task with
an agent recording**. That is the difference between a corpus that fills itself and one that waits
for a documentation project: the first half is scheduling, the second half is a decision to spend
half a day each.

---

## Frontmatter — inert today, on purpose

Each runbook declares its own IRI and its `explains` targets, per
[ADR-0037 §1](../adr/ADR-0037-ratified-docs-corpus-help-surface-grounding.md).

**Nothing reads it yet.** `mesh:explains` and `mesh:DocPage` have zero occurrences in this repo,
and the markdown→triples converter lives in **doc-tools** — a sibling repo whose CI is silent on
push ([`doctools-ci-silent-on-push`](../plans/doctools-ci-silent-on-push.md)), which is why
ADR-0037's own scope correction rules that build out of "packet-sized". Declaring the frontmatter
now costs nothing and means that when the converter lands these pages are already graph citizens
rather than a migration, and the vector index (ADR-0037 §3, rung 2) picks them up for free as a
projection of a corpus they are already in.

**`audience_hint` takes a value from [`policy/personas.yaml`](../../policy/personas.yaml),
lowercased** — `PORTFOLIO_LEAD, DATA_STEWARD, DATA_ENGINEER, ARCHITECT, MECHANIC, ANALYST`. That
file is the canonical enum and the vocabulary the Topaz sync tool refuses a grant against.
ADR-0037 §1's original `data-engineer | reviewer | leader` **is superseded** — two of the three are
not personas in this system, and a hint carrying `reviewer` would be display-routing on a persona
no group can grant, failing silently rather than loudly. Ruled in the ⛔ CORRECTED 2026-08-30 block
in [ADR-0037 §1](../adr/ADR-0037-ratified-docs-corpus-help-surface-grounding.md).
[`adding-an-engine.md`](adding-an-engine.md) declares `architect` accordingly.
