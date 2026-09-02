---
id:         a-rebind-does-not-replace
status:     open
owner:      agent (Engine F lane) — BLOCKED on a decision: 4 stale rows need deleting
blocked-on: user approval for a targeted delete of 4 Weaviate Predicate rows
repo:       invincible-agent
ruled-by:   ADR-0017 (rendersAs); ADR-0006 Addendum (the registrar is the sole writer); ADR-0019 (Contract D)
code-site:  src/iagent/gateway.py:~4347 (the frontend registration name), agent_fleet/utils/mesh_registration.py (register_presentation_to_mesh), agent_fleet/mesh_registrar/v2_substrate.py:579 (sweep_stale_weaviate_predicate_rows — verb-keyed, does not cover presentations), agent_fleet/presentation_agent/capability_registry.py:263 (first-match-wins)
summary:    REBINDING A SUBJECT TO A DIFFERENT ARCHETYPE LEAVES THE OLD BINDING LIVE, AND THE OLD ONE WINS. The presentation registration NAME encodes the archetype — `presentation_{archetype}_for_{slug}__{frontend_id}` — so it becomes a different tool_urn, and the compensate-on-rescope sweep (keyed on tool_urn + verb_iri) never sees the predecessor. Measured 2026-09-02 after rebinding two fin classes from PERIOD_SERIES to MULTI_SERIES: BOTH menus now hold BOTH bindings, all four rows `registration_complete: True`, and `select_archetype` returns the FIRST match — which is the stale PERIOD_SERIES. So the rebind materialised perfectly and changed nothing a card can see. The verb path does NOT have this defect: the same sweep correctly deleted `fin#Program` when finBurnRate's subject moved, because a verb's name does not encode its input_uri. TWO SECONDARY FINDINGS: the gateway's inline slug puts a COLON inside a DataHub URN (`presentation_multi_series_for_fin:burnrateseries__cortex-ui-desktop`) — the same defect fixed in the presentation agent and only there — and the BFF logged `failed_count: 2, gateway-rejected-REFUSED` for two registrations the registrar logged as SUCCEEDED.
---

# A rebind does not replace — and the old binding wins

## What was measured

Two finance classes were rebound from `PERIOD_SERIES` to `MULTI_SERIES` (ontology minted, admission
word added, projector entry added, capability table updated, cortex's payload regenerated and
re-registered). Every step reported success. Then:

```
class                    archetype              frontend            complete?
BurnRateSeries           MULTI_SERIES           cortex-ui-desktop   True
BurnRateSeries           PERIOD_SERIES          cortex-ui-desktop   True     ← stale, still live
PerformanceIndexSeries   MULTI_SERIES           cortex-ui-desktop   True
PerformanceIndexSeries   PERIOD_SERIES          cortex-ui-desktop   True     ← stale, still live
```

and the same pair in `__system_default__`. **All four complete. All four served.**

```
select_archetype("cortex-ui-desktop", fin#BurnRateSeries)  ->  PERIOD_SERIES
```

`select_archetype` returns the **first** capability whose subject matches. With two live bindings
for one subject, which one wins is Weaviate's return order — and it is currently the one the
rebind was meant to retire.

## Why the sweep did not fire, and why the verb path is fine

The registrar's compensate-on-rescope sweep deletes rows matching `(tool_urn, verb_iri)` whose
`input_uri` differs from the one being written. That is what makes a re-registration an **upsert**.

**For a presentation, the archetype is part of the name, and the name is the `tool_urn`:**

```
presentation_period_series_for_burnrateseries__cortex-ui-desktop     ← urn A
presentation_multi_series_for_burnrateseries__cortex-ui-desktop      ← urn B
```

Different urn ⇒ the sweep never considers A while writing B. **The rebind is an INSERT that looks
like an update**, and nothing anywhere reports the duplicate.

**The verb path does not have this defect**, and the contrast is the proof. From the same run:

```
[saga] sweep_stale_weaviate_predicate_rows: verb_iri=mesh:finBurnRate
       deleted 1 stale row(s): ['http://invincible-agent/fin#Program']
```

A verb's registration name does not encode its `input_uri`, so moving a verb's subject upserts
correctly. **The same mechanism is correct on one path and inert on the other, because of a naming
choice made for a different reason** — the archetype went into the name so one subject could hold
several bindings, which is exactly what makes retiring one impossible.

## What is needed, and why I have not done it

**Four rows must be deleted** — the two `PERIOD_SERIES` presentation rows in each menu, by exact
`tool_urn`. That is a destructive write to a live store, and the standing protocol in this repo is
that a targeted delete gets explicit approval rather than agent judgement, however small. **Filed,
not executed.**

There is no non-destructive path: the selector takes the first match, the order is not
controllable, and re-registering the correct binding again only adds another row.

**The durable repair is separate and larger:** either the sweep learns about presentations (match
on `subject_uri` + `frontend_id` + predicate rather than `tool_urn`), or the archetype comes out of
the name and a subject's binding becomes genuinely one row. The second is the honest model — ADR-0017
says the predicate is constant, so `(subject, frontend)` is the identity and the archetype is the
*value* — but it changes an identity scheme other things read.

## Two secondary findings from the same run

**1. The gateway puts a colon inside a DataHub URN.**

```
urn:li:mlModel:(urn:li:dataPlatform:mesh,presentation_multi_series_for_fin:burnrateseries__cortex-ui-desktop,PROD)
```

`src/iagent/gateway.py` builds its own slug with `subject_uri.rsplit('#', 1)[-1].lower()`, and a
**compact** CURIE has no `#`, so the whole `fin:BurnRateSeries` survives. This is the identical
defect fixed in `presentation_agent`'s `capability_slug` — **and I fixed one site of two.** My own
five-registries lesson, committed again inside the week I wrote it up. The presentation-agent fix
stands; the gateway's inline copy was never touched because nothing pointed at it.

**2. The BFF reported REFUSED for registrations that succeeded.**

```
cortex-bff : failed_count: 2, reason_class: gateway-rejected-REFUSED  (both MULTI_SERIES rows)
registrar  : Registered presentation_multi_series_for_fin:burnrateseries__cortex-ui-desktop
             (verb=mesh:rendersAs) via v0.2 saga: retries=3 elapsed=0.60s
```

Both rows exist and are `registration_complete: True`, so the registrar is right and the BFF's
classification is wrong. A `DataHub emit failed AFTER saga succeeded` warning sits between them and
is the likely cause, but **that is a hypothesis and it is not diagnosed here.** Recorded because it
is a **false red** — `[[a-succeeded-run-reported-as-failed]]`, second instance, and the worse
direction: it would have sent the next person to fix a registration that was already correct.

## Related

* `[[period-series-is-a-cost-curve]]` — why the rebind was needed.
* `[[a-degradation-must-name-itself]]` — the duplicate is silent at every layer: no warning on
  write, no warning on read, and a card that draws the wrong archetype confidently.
* `[[a-namespace-is-declared-in-four-places]]` — the colon finding is that packet's shape again.
