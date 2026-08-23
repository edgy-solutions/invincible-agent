---
id:         timeline-library-spike
status:     open
owner:      unassigned
blocked-on:
closed-by:
code-site:  ../cortex-ui/src/components/planning
repo:       cortex-ui
summary:    SPIKE RECORDED 2026-08-22. Phase 1 §4 requires evaluating 2-3 OSS timeline components and recording choice + rejects. CHOICE: `@svar-ui/react-gantt` (MIT) — the only candidate that is React-native rather than a self-wrapped vanilla-JS library, and the only one whose API expresses ADR-0042's drag-optimistic/drop-evaluated rule directly (`api.intercept("move-task")` cancels/defers before application; `api.exec("provide-data")` re-renders from server-returned data). Hierarchical grouping (initiative -> phase -> project) is in the FREE tier — PRO's "grouping" is RESOURCE grouping, a different feature. REJECTS: vis-timeline and frappe-gantt, both vanilla-JS needing a hand-written React wrapper; frappe-gantt's main React wrapper was last published ~5 years ago. SCOPE LIMIT, STATED: this is a DOCUMENTATION evaluation, not a built prototype. The two decisive claims (controlled-component mode, interceptable move) come from SVAR's docs and MUST be confirmed by a throwaway prototype before INTERVAL_TIMELINE's contract is written. Custom bar styling was NOT verified.
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

## SCOPE LIMIT — read before relying on this

**This is a documentation evaluation, not a built prototype.** The two claims the decision rests
on — controlled-component mode and interceptable `move-task` — are read from SVAR's docs and
have not been executed. **Custom bar styling, one of the four named criteria, was not verified
at all.**

That distinction matters here more than usual: this session has already produced three
instruments that reported numbers for work that never happened. A library evaluation read from
documentation is the same species of claim — plausible, unexecuted — and calling it a completed
spike would be the same error in a new place.

## What closes this packet

1. A throwaway prototype rendering ~20 tasks in two nesting levels, driven entirely from React
   state, where `move-task` is intercepted, **cancelled**, and the bar snaps back — proving the
   parent can refuse a drag. That single behaviour is the whole architectural bet.
2. Custom bar styling confirmed sufficient for phase bands and a risk flag.
3. Then, and only then, `INTERVAL_TIMELINE.contract.ts` + `DERIVED_BINDINGS` row + ontology
   class + `KNOWN_ARCHETYPES` entry — the four registries, batched into ONE prime with
   `DECISION_RECORD` if that unblocks, because a prime is ~50 minutes.
