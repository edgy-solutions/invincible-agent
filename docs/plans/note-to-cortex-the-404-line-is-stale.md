# Note to cortex — the 404 line is stale, and three things to know before you test

**Date:** 2026-08-26 · **From:** Lane 1 · **Verified against the deployed BFF, not the source**

## 1. Both endpoints exist. Delete the 404 note.

Cortex's note says `/plan/state_version` and `/canvas/seed` **404 until Lane 1 lands them**.
Both are live. Read out of the running pod's own OpenAPI spec:

```
/canvas/seed
/seed/portfolio_canvas
/plan/measure/{fn}
/plan/state_version
/plan/scenario
/plan/scenario/{scenario_id}/op
/plan/scenario/{scenario_id}/reschedule
/plan/scenario/{scenario_id}/commit
/plan/baseline/op
```

`client.ts:431` posts to `/canvas/seed`, which is the one that exists. Nothing to change on your
side — but leave the stale line in place and the next person spends an afternoon chasing
endpoints that are already deployed.

**Reproduce it yourself in one command:**

```bash
kubectl --context edge exec -n sandbox deploy/iagent-cortex-bff -- python -c \
"import urllib.request,json; s=json.loads(urllib.request.urlopen('http://localhost:8090/openapi.json').read()); \
print(sorted(p for p in s['paths'] if p.startswith('/plan') or 'seed' in p))"
```

## 2. `comp.valid_as_of` is undefined BY CONSTRUCTION — the card will never show a timestamp

Not a bug, and not something Lane 1 is going to fix, so it is worth knowing where to look.

Engine P produces **no** `valid_as_of`. It emits `state_ref` and `state_version` on the measure
envelope, and the projector now carries both onto every planning component. The **artifact**
carries `valid_as_of` — the gateway stamps it at evaluation, and `InterpretationStrip` reads
`artifact.valid_as_of`.

So `<IntervalTimeline valid_as_of={comp.valid_as_of} …>` receives `undefined`, and this renders:

```tsx
{valid_as_of && <>valid as of {valid_as_of}</>}          // never
{state_version !== undefined && <>state v{state_version}</>}  // "state v2"
```

**The card footer shows `state v2` and no timestamp.** Watch the STRIP for freshness and the
CARD for the version. Staring at the card footer waiting for a timestamp reads as a broken
refresh loop when nothing is broken.

If a component-level evaluation stamp is genuinely wanted, that is a producer change (Engine P
would have to emit one) — say so and Lane 1 will do it. Synthesising it in the projector was
deliberately refused: it would stamp PROJECTION time onto a field whose contract says
EVALUATION time, and those differ by exactly the interval the refresh loop exists to detect.

## 3. A single-tab drag does NOT test the poller

`commitDrag` calls `announcePlanChanged`, which notifies watchers **immediately in the tab that
did the drag**. So the single-tab path is: write → announce → re-request. The 15s poll never
enters it, and that path passes identically with the poller broken — which is exactly how the
scenario-blindness defect survived until yesterday.

**The honest test needs two sessions.** Open the same canvas in a second browser or profile,
drag in the first. The second tab has no announce and can only learn by polling; it should
update within ~15s. Nobody has run this yet.

## 4. And one for whatever you seed today

A **partial** seed composes a board that is wrong and plausible: `/canvas/seed` strips nulls
(your loop cannot iterate a hole), which re-shifts the slots the implementation aligned. Every
card is real, nothing errors, and the anchor holds whatever survived.

The tell is server-side only:

```bash
kubectl --context edge logs -n sandbox deploy/iagent-cortex-bff --tail=200 | grep -i "PARTIAL seed"
```

`seeded == total` (5/5) means slot order is trustworthy. Anything else means **do not conclude
anything from which card is in which slot** — including "the anchor renders the timeline".

Full reasoning, and the open product question about whether a partial seed should compose at
all, in `seed-route-ruling-and-the-partial-seed-hazard.md`. That ruling is the eval agent's.
