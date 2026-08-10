# OPEN — why a resolvable MPN composes as `subject_unresolved`

**Not a defect in the dispatch path.** The dispatch behaved exactly as designed: no resolved subject
⇒ no `graph_write` ⇒ the task carries the re-link provenance instead, and `completed success` is
honest. All eight historical `DispatchItem` records show the identical shape
(`state_written: false, subject_unresolved: true`) — **no dispatch in this system's history has ever
written disposition state, and every one was correct not to.** The composer's own seam-diff seal
witnessed this branch on real-shaped `IPCN25300X` input ("2 resolve, 1 abstains → kept for re-link,
not dropped").

## The question

`resolve_subject_via_engine_o("NSR01L30NXT5G")` called directly from engine-a **right now** returns
`http://internal/components/NSR01L30NXT5G`. Yet the batch those items were composed from recorded
them as unresolved. Same MPN, same graph, different answer.

Consequence, and why it is worth a session: a composed batch can carry `subject: None` for an MPN
the system *can* resolve, which silently converts a graph-writing dispatch into a task-only one. The
effect still lands (the task), so nothing is lost — but the graph never receives the disposition,
and nobody is told the difference was a resolution miss rather than a design branch.

## Three hypotheses, in the order that discriminates them

1. **Frozen at composition time** (stored-value class). `subject` is a resolution *result* recorded
   into `batch_items`, and the world moved under it — the components entered the graph after the
   batch was composed. Cheapest check: compare the component IRIs' arrival against the batch's
   composition timestamp.
2. **Call-site difference.** The composer's seam and a direct call differ in parameters or graph
   scope. Check: diff the composer's `resolve_subject_via_engine_o` invocation against a direct one.
3. **Entitlement-scoped resolution** — the one the architecture predicts and neither obvious reading
   covers. `/resolve` domain-scopes to the **caller's** entitled domains (witnessed in the routing
   arc: alice's un-granted MAINTENANCE query grounded to UNKNOWN while the subject existed). If the
   composer resolves under an identity whose domain scope differs from the reader's, the same MPN
   abstains for one and resolves for the other. That would be the
   entitlement-gap-absorbed-silently class arriving at the **composition** layer, and it is a real
   finding about *whose entitlements author a batch*.

Discriminating read is cheap: the composer's call-site identity and parameters vs. a direct call,
plus the IRIs' arrival time relative to composition.

## The follow-up either way

The design anticipated resolution arriving late — that is what the task's re-link provenance is
*for*. So the standing question is whether anything ever **exercises** the re-link: does a later
resolution ever cause the disposition to reach the graph, or does the provenance sit unread? That is
a parked item, not a defect.

## Not autonomy-specific

The supervised path shares the identical composer, plan and dispatch. Nothing here touches the
trust-table promotion, and it would be wrong to demote over it.
