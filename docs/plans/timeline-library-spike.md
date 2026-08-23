---
id:         timeline-library-spike
status:     open
owner:      unassigned
blocked-on:
closed-by:
code-site:  ../cortex-ui/src/components/planning
repo:       cortex-ui
summary:    SPIKE RECORDED 2026-08-22. Phase 1 §4 requires evaluating 2-3 OSS timeline components and recording choice + rejects. CHOICE: `@svar-ui/react-gantt` (MIT) — the only candidate that is React-native rather than a self-wrapped vanilla-JS library, and the only one whose API expresses ADR-0042's drag-optimistic/drop-evaluated rule directly (`api.intercept("move-task")` cancels/defers before application; `api.exec("provide-data")` re-renders from server-returned data). Hierarchical grouping (initiative -> phase -> project) is in the FREE tier — PRO's "grouping" is RESOURCE grouping, a different feature. REJECTS: vis-timeline and frappe-gantt, both vanilla-JS needing a hand-written React wrapper; frappe-gantt's main React wrapper was last published ~5 years ago. PROTOTYPE EXECUTED 2026-08-22 and the bet HOLDS — 4/4 including a negative control: intercepting the commit and returning false leaves the task unmoved, while the same exec without the intercept DOES move it. Executing also CORRECTED the documentation-derived claim: `move-task` is TREE REORDER, not time movement; the data commit is `update-task` and the pixel drag is `drag-task`, both carrying `inProgress` — which is a BETTER fit for drag-optimistic/drop-evaluated than the docs suggested. Custom bar styling confirmed via the `taskTemplate` prop. Remaining: hierarchy proven headlessly, not visually.
---

# Timeline library spike — choice and rejects

Phase 1 §4 timeboxes this at 3h and names four criteria: **drag-to-move, row grouping, custom
bar styling, controlled-component mode**. Operator ruling 2026-08-22 set the licence constraint
to **MIT/Apache only** and confirmed all three candidates pass under their correct names.

## The licence trap, sealed before evaluation

| package | licence | |
|---|---|---|
| `vis-timeline` | Apache-2.0 OR MIT | eligible |
| `frappe-gantt` | MIT | eligible (its GPL association is ERPNext, not the library) |
| `@svar-ui/react-gantt` | **MIT** | eligible |
| `wx-react-gantt` | **GPL-3.0** | **BANNED** |

The last two are the same project either side of a rename. `cortex-ui`'s
`src/dependencyLicense.guard.test.ts` fails the build if the GPL name appears in `package.json`
**or in the lockfile**, because the difference between safe and contaminating is a package name
and no diff would show it.

## Choice: `@svar-ui/react-gantt`

Won on the two criteria that interact with this architecture, not on general merit.

**1. Controlled-component mode — the one that decides it.** ADR-0042 §3/§4 require that drag is
optimistic (only the BAR moves; arrangement is UI-master) while **drop is evaluated server-side
and the strips redraw from server rows**. A component that owns its task state internally
fights that rule on every drop.

SVAR's docs describe the parent holding `useState` and passing tasks/links down — the component
does not own a store. More directly, its event API expresses our exact sequence:

```
api.intercept("move-task", …)   // intercept BEFORE application; cancel or defer
api.exec("provide-data")        // re-render from server-returned data
```

> **CORRECTED BY THE PROTOTYPE — `move-task` IS THE WRONG ACTION.** Left visible rather than
> rewritten, because the error is the informative part: this snippet is SVAR's generic docs
> example, and it reads as confirmation of our use case while naming a different one.
> `move-task` reorders the TREE. The data commit is **`update-task`**. See the executed
> section below; the conclusion survives, the mechanism named here does not.

That is drag-optimistic/drop-evaluated in the library's own vocabulary rather than something we
have to defeat the library to achieve.

**2. React-native, no wrapper.** The other two are vanilla-JS libraries wrapped by hand. A
hand-written imperative wrapper is the worst possible home for a `.contract.ts`-first component:
the contract describes a declarative payload, and the wrapper would be the one place where that
payload turns into imperative mutation calls, un-typed and un-tested.

**3. Hierarchy is in the FREE tier**, and this needed checking rather than assuming — the plan
requires rows grouped initiative -> phase -> project. Open-source edition lists *"summary tasks
and milestones"* and *"hierarchical view of sub-tasks"*. **PRO's "grouping" is RESOURCE
grouping**, an unrelated feature, and confusing the two would have been exactly the mid-build
trap the operator warned about.

PRO-only (none of it needed): critical path, baselines, auto-scheduling, working calendars,
split tasks, WBS codes, resource management, undo/redo, export/import.

## Rejects, with reasons

**vis-timeline** — dual Apache-2.0/MIT, most battle-tested, and the plan's designated fallback.
Rejected only because it is vanilla-JS with no official React binding, so the controlled-
component behaviour above would be ours to build and maintain. **Still the fallback**: if the
prototype below disproves SVAR's controlled-component story, take vis-timeline and move on
rather than shopping further.

**frappe-gantt** — MIT and pleasant, but every React wrapper is third-party and the most-cited
one (`react-frappe-gantt`) was last published roughly five years ago. Adopting an unmaintained
wrapper for the marquee interaction of the demo trades a build problem for a maintenance one.

## PROTOTYPE EXECUTED — the bet holds, and executing corrected the reading

`cortex-ui/src/components/planning/__spike__/ganttIntercept.spike.test.tsx`, **4/4**:

| assertion | result |
|---|---|
| `init` hands the parent an api with `intercept` + `exec` | pass |
| hierarchy renders — `tasks.byId(3).$level > 0`, free tier | pass |
| **THE BET** — intercept the commit, return `false`, task unmoved **and the intercept ran** | pass |
| **NEGATIVE CONTROL** — same exec WITHOUT the intercept DOES move the task | pass |

The negative control is what makes this a result. "Unchanged" alone is also true of a library
that silently ignores `exec`, which would read as cancellation while proving the opposite.

### What executing corrected — the doc-derived claim was WRONG

The evaluation above said to intercept **`move-task`**. That came from SVAR's generic docs
example and is wrong for this use. The real actions:

| action | payload | what it is |
|---|---|---|
| `move-task` | `{id, target?, mode: "before"\|"after"\|"up"\|"down"\|"child"}` | **TREE REORDER** — row ordering |
| `drag-task` | `{id, left, top, width, inProgress}` | the **pixel** drag |
| `update-task` | `{id, task, inProgress?, diff?}` | the **DATA COMMIT** |

So the interception target is `update-task`. Firing `move-task` with time-shaped params threw
`Cannot read properties of undefined (reading '$level')` — it was trying to reorder a tree.

**This is BETTER than the documentation suggested.** The library already separates the visual
drag from the data commit, and BOTH carry `inProgress` — so "let the bar move, refuse the
commit until the server disposes" is expressible without fighting the library. That is
ADR-0042 §4 in the vendor's own vocabulary, and it was not visible from the docs.

### Two environment gaps — NOT library defects

jsdom has no layout, so the first two runs died on things that say nothing about SVAR:

* `canvas.getContext("2d")` returns **null** in jsdom (SVAR draws its background grid as a
  canvas pattern) — `Cannot read properties of null (reading 'translate')`;
* `ResizeObserver` is undefined — SVAR's Layout observes its container.

Both are standard shims. Recording them because "SVAR fails to render in React" was the
available wrong conclusion, and it would have rejected the ruled library for jsdom's missing
2d context.

### One more correction, same species

`getState()._tasks` is the **visible flattened** list — with the root collapsed it has length 1
and children live in `data[]`. The addressable store is the tree: `tasks.byId(id)`. An
assertion against `_tasks` reported `undefined` for a task that was present the whole time —
a shape assumption reading as an absence.

### Criteria status

| criterion | state |
|---|---|
| drag-to-move | **proven** — `drag-task` / `update-task` with `inProgress` |
| controlled-component mode | **proven** — intercept cancels the commit, negative-controlled |
| row grouping | **proven** — `$level > 0`, free tier |
| custom bar styling | **confirmed by API** — `taskTemplate?: FC<{data, api, onaction}>` renders the bar |

Bar styling is confirmed at the type surface, not visually. That is enough to build the
contract against; it is not enough to claim the phase bands look right.

## What closes this packet

1. `INTERVAL_TIMELINE.contract.ts` + `DERIVED_BINDINGS` row + ontology class +
   `KNOWN_ARCHETYPES` entry — the four registries, batched into ONE prime with
   `DECISION_RECORD` if that unblocks, because a prime is ~50 minutes.
2. A visual confirmation of phase bands and the risk flag through `taskTemplate` — the one
   criterion still standing on a type signature rather than a render.
