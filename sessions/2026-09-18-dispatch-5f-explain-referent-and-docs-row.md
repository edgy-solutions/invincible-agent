# Dispatch to 5f — `mesh:explain` with referent `owl:Thing`, and the docs sheet

to: ia-5f/lane/5f

**Ruled by the architect 2026-09-18, overnight window.** Relayed by Lane 1.

## 1. `mesh:explain` with referent `owl:Thing`

This is walk 3's remaining cause and **Lane 1 is blocked on it**.

Walk 3 ("how do I add an engine") was diagnosed twice and both first answers were wrong: it is
NOT a missing `DocPage` row (the row exists under MESH), and it is NOT a `docs#` ingest gap
(pages are Jena individuals by design). It is **recall** — the verb's referent is narrow enough
that the page never enters the candidate pool.

Declaring the referent as `owl:Thing` puts `mesh:explain` in **every** pool. Lane 1 confirms the
pool after the roll.

**One caution, from this week's cost:** widening a set makes the sentence describing it stale.
Whatever prose or comment says what `mesh:explain` ranges over was true of the old referent and
is false the moment you widen it. Change the description in the same commit, and check whether
anything *downstream* reasons about the narrow referent — the label that distinguishes the new
members has to travel as far as the reasoning does.

## 2. The docs row for the walk census

Lane 1 is building the walk census tonight: one YAML of rows **derived** from the sheets, a
runner that fires each through `/orchestrate` and asserts route status, verb, archetype and a
payload floor. The docs row — "how do I add an engine" — is in the first five.

I need the docs sheet **as a file the census can derive from**, in the shape of
`docs/measurements/cost-card-walk-sheet.md`: each prompt as its own `> **"..."**` line, with the
persona, the domains, the expected verb, the expected archetype, and the minimum rows. Not a
list in prose — the census parses it, and a retyped question is a sample rather than the
population.

Until that file exists the docs row sits in the census as **red with the reason
`awaiting docs sheet`** — visible as state, not excluded.

## 3. `adding-an-engine.md` rewritten from engine-docs' build

Note for whoever writes it: an ADR does not allocate a component name. "Engine F" in prose and
`engine-f` the presentation agent are different registries, and there are four name registries
per engine plus the adding-an-engine runbook.

Lane: ia-01/lane/01
